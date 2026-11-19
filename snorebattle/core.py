"""獨立規則核心：UI／未來網路端只送 Command，不可直接改狀態。"""
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import random
import uuid
from .effects import Effect, WAVE_HANDLERS, TOOL_HANDLERS, STAT_KINDS, IMMEDIATE_KINDS
from .wave import Wave
from .achievements import Achievements
from .errors import RuleError
from .scoring import calculate_points, slap_base_points, slap_points

ROLES = ('打呼者','打巴掌者')

@dataclass(frozen=True)
class Command:
    player: int
    action: str
    card_uid: int | None = None
    expected_revision: int | None = None

@dataclass
class Card:
    uid: int
    definition: str

@dataclass
class Tool:
    card: Card
    equipped_turn: int
    remaining: int | None

@dataclass
class Player:
    hand: list = field(default_factory=list)
    score: int = 0
    tool: Tool | None = None
    turns: int = 0

def load_data(root):
    root = Path(root)
    config = json.loads((root/'data/config.json').read_text(encoding='utf-8'))
    cards = json.loads((root/'data/cards.json').read_text(encoding='utf-8'))
    return config, {c['id']:c for c in cards}

def validate(config, cards):
    for key in ('amplitude','period','interval','duration','hand_limit','initial_hand','preview','slaps'):
        value = config[key]
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'config: {key} 必須為正數')
    for key in ('hand_limit','initial_hand','slaps'):
        if not isinstance(config[key],int):
            raise ValueError(f'{key} 必須為整數')
    base=config.get('slap_base',1.05)
    if isinstance(base,bool) or not isinstance(base,(int,float)) or not math.isfinite(base) or base<1:
        raise ValueError('slap_base 必須為至少 1 的有限數字')
    turn_score=config.get('snore_turn_score',1)
    if isinstance(turn_score,bool) or not isinstance(turn_score,int) or turn_score<0:
        raise ValueError('snore_turn_score 必須為非負整數')
    if not cards:
        raise ValueError('至少需要一種卡牌')
    for key, card in cards.items():
        if not isinstance(card['copies'],int) or card['copies']<0:
            raise ValueError(f'{key}: copies 必須為非負整數')
        for effect in card['effects']:
            kind = effect['kind']
            if effect.get('when','always') not in ('always','landing_nonnegative','landing_negative'):
                raise ValueError(f'{key}: 未註冊的效果條件')
            if 'clear_on_slap' in effect and not isinstance(effect['clear_on_slap'],bool):
                raise ValueError(f'{key}: clear_on_slap 必須為布林值')
            if kind not in WAVE_HANDLERS and kind not in STAT_KINDS and kind not in IMMEDIATE_KINDS:
                raise ValueError(f'{key}: 未註冊效果 {kind}')
            if kind=='sin_add' and effect['period']<=0:
                raise ValueError(f'{key}: 週期必須為正')
            if kind in ('base_amplitude','base_period') and effect['factor']<=0:
                raise ValueError(f'{key}: 基礎倍率必須為正')
            if effect.get('duration',1)<=0:
                raise ValueError(f'{key}: 持續時間必須為正')
        if 'tool' in card:
            t = card['tool']
            if t['kind'] not in TOOL_HANDLERS or (t['uses'] is not None and t['uses']<=0):
                raise ValueError(f'{key}: 道具能力／次數不合法')

class Game:
    def __init__(self, config, catalog, save_dir=None, seed=None):
        validate(config,catalog)
        self.config, self.catalog = dict(config), catalog
        self.config.setdefault('snore_turn_score',1)
        self.config.setdefault('slap_base',1.05)
        self.config.pop('slap_divisor',None)
        self.seed = seed if seed is not None else config.get('seed')
        if self.seed is None:
            self.seed = random.SystemRandom().randrange(2**32)
        self.rng = random.Random(self.seed)
        self.id = uuid.uuid4().hex
        self.players = [Player(), Player()]
        self.active = 0
        self.turn = 1
        self.players[0].turns = 1
        self.phase = 'landing'
        self.x, self.y = 0., 0.
        self.first_landing = True
        self.role_used = False
        self.tool_used = False
        self.effects = []
        self.wave = Wave(config['amplitude'], config['period'], config.get('wave_fade',1.0))
        self.slaps_left = config['slaps']
        self.draw_pile, self.discard = [], []
        self.events = []
        self.revision = 0
        self.points = []
        self.save_dir = Path(save_dir) if save_dir else None
        if self.save_dir:
            (self.save_dir/'logs').mkdir(parents=True, exist_ok=True)
        self.achievements = Achievements(self.save_dir/'achievements.json' if self.save_dir else None)
        uid=0
        for card_id, definition in catalog.items():
            for _ in range(definition['copies']):
                self.draw_pile.append(Card(uid,card_id))
                uid+=1
        self.card_count=uid
        self.rng.shuffle(self.draw_pile)
        self.emit('game_started', seed=self.seed, config=self.config,
                  catalog=catalog, deck=[asdict(c) for c in self.draw_pile])
        for player in (0,1):
            self.draw(player,config['initial_hand'])
        self.land()

    def emit(self, kind, player=None, **data):
        event=dict(seq=len(self.events)+1,game_id=self.id,
                   timestamp=datetime.now(timezone.utc).isoformat(),
                   type=kind,player=self.active if player is None else player,
                   turn=self.turn,x=self.x,revision=self.revision,**data)
        self.events.append(event)
        self.achievements.consume(event)
        if self.save_dir:
            with (self.save_dir/'logs'/f'{self.id}.jsonl').open('a',encoding='utf-8') as file:
                file.write(json.dumps(event,ensure_ascii=False)+'\n')

    def stat(self, kind, player=None):
        defaults = dict(interval=self.config['interval'], duration=self.config['duration'],
                        hand_limit=self.config['hand_limit'], preview=self.config['preview'],
                        score_bonus=0,blackout=0)
        result=defaults[kind]
        for effect in self.effects:
            if effect.kind==kind and effect.active(self.x) and (effect.target is None or effect.target==player):
                result+=effect.params.get('amount',1)
        if kind=='interval': return max(.5,result)
        if kind=='duration': return max(0,result)
        if kind=='hand_limit': return max(0,int(result))
        if kind=='preview': return max(0,result)
        return result

    def draw(self, player, count):
        drawn=[]
        for _ in range(max(0,int(count))):
            if not self.draw_pile:
                if not self.discard: break
                self.draw_pile,self.discard = self.discard,[]
                self.rng.shuffle(self.draw_pile)
                self.emit('deck_shuffled', order=[c.uid for c in self.draw_pile])
            card=self.draw_pile.pop()
            self.players[player].hand.append(card)
            drawn.append(asdict(card))
        if drawn: self.emit('cards_drawn',player=player,cards=drawn)
        return len(drawn)

    def eligible(self):
        if self.phase!='action' or self.role_used: return False
        return (abs(self.y)+1e-8>=self.config['amplitude'] if self.active==0
                else self.y>0 and self.slaps_left>0)

    def tool_ready(self):
        p=self.players[self.active]
        return (self.phase=='action' and p.tool is not None and not self.tool_used
                and p.turns>p.tool.equipped_turn)

    def _require(self, condition, message):
        if not condition: raise RuleError(message)

    def dispatch(self, command):
        self._require(command.player==self.active,'不是此玩家的操作回合')
        self._require(command.expected_revision in (None,self.revision),'操作已過期，請重新讀取狀態')
        handlers=dict(land=self.land,score=self.score,bonus_draw=self.bonus_draw,
                      slap=self.slap,use_tool=self.use_tool,discard_tool=self.discard_tool,
                      to_cards=self.to_cards,play=self.play,discard=self.exchange,
                      skip=self.skip,next=self.next_turn)
        self._require(command.action in handlers,'未知操作')
        # 各操作先驗證再修改；失敗操作不產生事件或消耗狀態。
        handlers[command.action](command.card_uid) if command.action in ('play','discard') else handlers[command.action]()
        self.revision+=1
        self.emit('command_applied', action=command.action,actor=command.player,card_uid=command.card_uid)

    def award_score(self, player, base_points, *, source, rounding='truncate'):
        """所有得分的共用入口；source 是穩定的來源識別，不是卡名。"""
        self._require(player in (0,1),'未知得分玩家')
        bonus=self.stat('score_bonus',player)
        points=calculate_points(base_points,bonus,rounding=rounding)
        self.players[player].score+=points
        self.emit('score_awarded',player=player,source=source,base_points=base_points,
                  bonus=bonus,rounding=rounding,points=points,total=self.players[player].score)
        return points

    def land(self):
        self._require(self.phase=='landing','目前不是落點階段')
        next_x=0 if self.first_landing else self.x+self.stat('interval',self.active)
        self.first_landing=False
        if next_x>self.stat('duration')+1e-8:
            self.finish()
            return
        self.x=next_x
        self.effects=[e for e in self.effects if e.end is None or e.end>self.x]
        self.y=self.wave.value(self.x)
        self.points.append(dict(x=self.x,y=self.y,player=self.active))
        self.phase='action'
        self.emit('landed',y=self.y)
        if self.active==0 and self.config['snore_turn_score']>0:
            points=self.award_score(0,self.config['snore_turn_score'],source='snore_turn')
            if points:
                self.emit('snore_turn_scored',points=points)

    def score(self):
        self._require(self.active==0 and self.eligible(),'目前不能取得打呼分數')
        points=self.award_score(0,self.config['snore_score'],source='snore_action')
        self.role_used=True
        self.emit('snore_scored',points=points,y=self.y)

    def bonus_draw(self):
        self._require(self.active==0 and self.eligible(),'目前不能額外補牌')
        self.draw(0,1)
        self.role_used=True
        self.emit('bonus_draw_taken')

    def slap(self):
        self._require(self.active==1 and self.eligible(),'落點須為正且仍有巴掌機會')
        base_points=slap_base_points(self.y,self.config['slap_base'])
        points=self.award_score(1,base_points,source='slap',rounding='ceil')
        self.slaps_left-=1
        self.emit('slapped',points=points,y=self.y,remaining=self.slaps_left)
        for player,p in enumerate(self.players):
            if p.tool:
                self.discard.append(p.tool.card)
                self.emit('tool_removed',player=player,card_id=p.tool.card.definition,reason='slap')
                p.tool=None
        removed=[e for e in self.effects if e.clear_on_slap]
        self.effects=[e for e in self.effects if not e.clear_on_slap]
        self.wave.publish(self.x,self.effects)
        self.emit('effects_cleared',removed=[asdict(e) for e in removed],
                  retained=[asdict(e) for e in self.effects])
        self.end_turn(0)

    def use_tool(self):
        self._require(self.tool_ready(),'道具尚未就緒或本回合已使用')
        p=self.players[self.active]
        tool=p.tool
        data=self.catalog[tool.card.definition]['tool']
        TOOL_HANDLERS[data['kind']](self,self.active,data)
        self.tool_used=True
        if tool.remaining is not None: tool.remaining-=1
        self.emit('tool_used',card_id=tool.card.definition,y=self.y,remaining=tool.remaining)
        if tool.remaining==0:
            self.discard.append(tool.card)
            p.tool=None
            self.emit('tool_removed',card_id=tool.card.definition,reason='exhausted')

    def discard_tool(self):
        p=self.players[self.active]
        self._require(self.phase=='action' and p.tool is not None,'目前沒有可棄掉的道具')
        card=p.tool.card
        self.discard.append(card)
        p.tool=None
        self.emit('tool_removed',card_id=card.definition,reason='discard')

    def to_cards(self):
        self._require(self.phase=='action','目前不是行動階段')
        self.phase='cards'
        self.emit('action_finished')

    def find_card(self, uid):
        card=next((c for c in self.players[self.active].hand if c.uid==uid),None)
        self._require(self.phase=='cards' and card is not None,'請在出牌階段選擇自己的手牌')
        return card

    def make_effect(self, spec):
        """預覽與正式出牌共用同一份效果資料建構邏輯。"""
        target={'self':self.active,'opponent':1-self.active,'all':None}[spec.get('target','all')]
        end=self.x+spec['duration'] if 'duration' in spec else None
        params={k:v for k,v in spec.items() if k not in ('kind','duration','target','clear_on_slap','when')}
        return Effect(spec['kind'],self.x,end,target,params,spec.get('clear_on_slap',True))

    def card_effects(self, definition):
        """在操作當下選定分支；預覽與正式出牌共用，不依卡牌名稱寫例外。"""
        conditions={'always':True,'landing_nonnegative':self.y>=0,'landing_negative':self.y<0}
        selected=[]
        for spec in definition['effects']:
            if not conditions[spec.get('when','always')]:
                continue
            effect=dict(spec)
            # 分類規則集中處理，未來新增功能牌不必逐張設定例外。
            if definition['category']=='功能':
                effect['clear_on_slap']=False
            selected.append(effect)
        return selected

    def preview_wave(self, card_uid):
        """純查詢：任何階段均能預覽自己手牌，不抽牌、不發事件或改規則狀態。"""
        card=next((c for c in self.players[self.active].hand if c.uid==card_uid),None)
        if card is None:
            return None
        specs=[e for e in self.card_effects(self.catalog[card.definition]) if e['kind'] in WAVE_HANDLERS]
        if not specs:
            return None
        preview=deepcopy(self.wave)
        operations=list(self.effects)+[self.make_effect(spec) for spec in specs]
        preview.publish(self.x,operations)
        return preview

    def apply_effect(self, spec):
        target={'self':self.active,'opponent':1-self.active,'all':None}[spec.get('target','all')]
        if spec['kind']=='reshuffle':
            count=len(self.players[target].hand)
            self.discard.extend(self.players[target].hand)
            self.players[target].hand=[]
            self.draw(target,count)
            self.emit('hand_reshuffled',target=target,count=count)
            return
        effect=self.make_effect(spec)
        self.effects.append(effect)
        self.emit('effect_added',effect=asdict(effect))

    def play(self, uid):
        card=self.find_card(uid)
        definition=self.catalog[card.definition]
        p=self.players[self.active]
        self._require('tool' not in definition or p.tool is None,'道具欄必須為空，請先在行動階段棄掉舊道具')
        selected_effects=self.card_effects(definition)
        p.hand.remove(card)
        if 'tool' in definition:
            p.tool=Tool(card,p.turns,definition['tool']['uses'])
        # 一般牌在結算後才進棄牌，避免重洗效果把正在使用的牌抽回。
        for effect in selected_effects: self.apply_effect(effect)
        if 'tool' not in definition: self.discard.append(card)
        if any(e['kind'] in WAVE_HANDLERS for e in selected_effects):
            self.wave.publish(self.x,self.effects)
        self.emit('card_played',card_id=card.definition,card_uid=card.uid,landing_y=self.y,
                  selected_effects=deepcopy(selected_effects))
        self.draw(self.active,max(0,self.stat('hand_limit',self.active)-len(p.hand)))
        if self.x>self.stat('duration')+1e-8:
            self.finish()
        else:
            self.end_turn(1-self.active)

    def exchange(self,uid):
        card=self.find_card(uid)
        self.players[self.active].hand.remove(card)
        self.discard.append(card)
        self.emit('card_discarded',card_id=card.definition,card_uid=card.uid)
        self.draw(self.active,2)
        self.end_turn(1-self.active)

    def skip(self):
        self._require(self.phase=='cards','目前不是出牌階段')
        self.emit('card_skipped')
        self.end_turn(1-self.active)

    def end_turn(self,next_player):
        self.emit('turn_ended')
        self.active=next_player
        self.phase='handoff'
        self.next_turn()

    def next_turn(self):
        self._require(self.phase=='handoff','目前不是換人階段')
        self.turn+=1
        self.players[self.active].turns+=1
        self.role_used=self.tool_used=False
        self.phase='landing'
        self.emit('turn_started')
        self.land()

    def finish(self):
        self.phase='ended'
        a,b=[p.score for p in self.players]
        self.emit('game_ended',scores=[a,b],winner=None if a==b else (0 if a>b else 1))

    def view(self,player):
        """網路擴充邊界：未來由權威端執行命令，再傳此玩家可見資料。"""
        return dict(revision=self.revision,active=self.active,phase=self.phase,x=self.x,y=self.y,
                    scores=[p.score for p in self.players],
                    hand=[asdict(c) for c in self.players[player].hand],
                    opponent_hand_count=len(self.players[1-player].hand),
                    slaps_left=self.slaps_left,
                    interval=self.stat('interval',player),duration=self.stat('duration'),
                    preview=self.stat('preview',player),blackout=bool(self.stat('blackout',player)),
                    hand_limit=self.stat('hand_limit',player))
