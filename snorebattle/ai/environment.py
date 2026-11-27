"""唯一接觸完整遊戲的邊界；策略只接收經遮罩的 observation。"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from snorebattle.core import load_data

def settings(game_root):
    config,catalog=load_data(game_root)
    path=Path(game_root)/'saves/settings.json'
    if path.exists():
        saved=json.loads(path.read_text(encoding='utf-8-sig'))
        config.update(saved['config'])
        for key,count in saved['copies'].items():
            if key in catalog: catalog[key]['copies']=max(0,int(count))
    config.pop('slap_divisor',None)
    return config,catalog

def stable_seed(*parts):
    return int(hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest()[:12],16)

def observe(g):
    p=g.players[g.active]
    blind=bool(g.stat('blackout',g.active))
    legal=[]
    if g.phase=='action':
        legal.append(('to_cards',None))
        if g.eligible():
            legal.extend([('score',None),('bonus_draw',None)] if g.active==0 else [('slap',None)])
        if g.tool_ready(): legal.append(('use_tool',None))
        if p.tool: legal.append(('discard_tool',None))
    elif g.phase=='cards':
        legal.append(('skip',None))
        for card in p.hand:
            definition=g.catalog[card.definition]
            legal.append(('discard',card.uid))
            if 'tool' not in definition or p.tool is None: legal.append(('play',card.uid))
    hand=[dict(uid=c.uid,id=c.definition,definition=deepcopy(g.catalog[c.definition])) for c in p.hand]
    # 與 GUI 相同，不能看穿預覽範圍或關燈。
    end=min(g.stat('duration'),g.x+g.stat('preview',g.active))
    xs=[] if blind else [g.x+(end-g.x)*i/10 for i in range(1,11)]
    future=[(x,g.wave.value(x)) for x in xs]
    # 只評估 GUI 可見範圍內的兩個假設落點；對手出牌改變波形仍屬未知。
    def landing_values(wave):
        return {who:wave.value(x) if not blind and x<=end+1e-9 else None
                for who,x in (('opponent',g.x+g.stat('interval',g.active)),
                              ('self',g.x+2*g.stat('interval',g.active)))}
    landings=landing_values(g.wave)
    landing_previews={}
    previews={}
    if not blind:
        for card in p.hand:
            if card.definition in previews: continue
            wave=g.preview_wave(card.uid)
            if wave:
                previews[card.definition]=[(x,wave.value(x)) for x in xs]
                landing_previews[card.definition]=landing_values(wave)
    tempo_previews={}
    for card in p.hand:
        effects=g.card_effects(g.catalog[card.definition])
        if not any(e['kind'] in ('interval','duration') for e in effects):continue
        interval=max(.5,g.stat('interval',g.active)+sum(e.get('amount',0) for e in effects if e['kind']=='interval' and e.get('target','all') in ('self','all')))
        duration=max(0,g.stat('duration')+sum(e.get('amount',0) for e in effects if e['kind']=='duration'))
        x=g.x+interval
        # 結束後沒有對手落點；其餘遵守目前可見範圍，不偷看新落點。
        tempo_previews[card.definition]=(0.0 if x>duration+1e-9 else g.wave.value(x) if not blind and x<=end+1e-9 else None)
    return dict(role=g.active,phase=g.phase,x=g.x,y=None if blind else g.y,
                blind=blind,legal=legal,hand=hand,future=future,previews=previews,tempo_previews=tempo_previews,
                preview_length=g.stat('preview',g.active),landings=landings,landing_previews=landing_previews,
                scores=[q.score for q in g.players],opponent_hand_count=len(g.players[1-g.active].hand),
                threshold=g.config['amplitude'],interval=g.stat('interval',g.active),
                duration=g.stat('duration'),hand_limit=g.stat('hand_limit',g.active),
                bonus=g.stat('score_bonus',g.active),opponent_bonus=g.stat('score_bonus',1-g.active),snore_score=g.config['snore_score'],
                turn_score=g.config.get('snore_turn_score',1),slap_base=g.config.get('slap_base',1.05),
                slaps_left=g.slaps_left,role_used=g.role_used,tool_used=g.tool_used,
                tool=None if p.tool is None else dict(definition=deepcopy(g.catalog[p.tool.card.definition]),remaining=p.tool.remaining))
