"""回放與人機測試沿用正式 GUI；不改正式成就或設定存檔。"""
import json
import random
import sys
import time
from pathlib import Path
import pygame
from .core import Game,Command
from .ai.controller import ComputerController
from .replay import Replay,Recorder

def bot_root(app): return app.root.parent/'snorebot'

def bot_modules(app):
    path=bot_root(app)
    if not (path/'botlab/policy.py').exists():
        from .ai.policy import Policy,load_profile
        from .ai.environment import observe,stable_seed
        return Policy,load_profile,observe,stable_seed
    if str(path) not in sys.path: sys.path.insert(0,str(path))
    from botlab.policy import Policy,load_profile
    from botlab.environment import observe,stable_seed
    return Policy,load_profile,observe,stable_seed

def install_game(app,game):
    app.tutorial=None
    app.game=game; app.scene='battle'
    app.camera_x=app.camera_from=app.camera_target=game.x
    app.selected=None;app.inspect_tool=False;app.detail_scroll=0;app.hand_offset=0
    app._preview_key=None;app._preview_wave=None
    app.seen_events=len(game.events);app.log_open=False
    app.message='';app.message_until=0

class BotMode(ComputerController):
    kind='bot'
    def __init__(self,app,profile_path,human_role):
        Policy,load_profile,self.observe,stable_seed=bot_modules(app)
        self.app=app;self.human_role=int(human_role)
        self.profile_path=Path(profile_path)
        self.profile=load_profile(profile_path)
        if self.profile['role']==self.human_role: raise ValueError('請選擇另一角色的策略')
        game=Game(app.config,app.catalog,seed=random.SystemRandom().randrange(2**32))
        super().__init__(app,human_role,Policy(self.profile,stable_seed(game.seed,self.profile['role'])),self.observe)
        self.recorder=Recorder(game,dict(mode='human_vs_bot',human_role=human_role,profile=self.profile))
        self.saved=False;self.next_action=0;self.message=''
        install_game(app,game)
    def after_command(self,player,action,uid):
        self.recorder.append(self.app.game,Command(player,action,uid))
        self.recorder.data['commands'][-1]['decision']=self.agent.last_reason if player!=self.human_role else '人類操作'
        self.next_action=pygame.time.get_ticks()+450
        if self.app.game.phase=='ended': self.save()
    def save(self):
        if self.saved: return
        folder=bot_root(self.app)/'human_games' if bot_root(self.app).exists() else self.app.root/'saves/test_replays'
        path=folder/f'{self.app.game.id}.json'
        self.recorder.save(path,self.app.game);self.saved=True
        self.app.notify('人機測試回放已儲存。')
    def banner(self):
        role=('打呼者','打巴掌者')[self.human_role]
        self.app.text(f'人機測試（不影響正式成就）｜你：{role}｜AI：{self.profile["name"]}',42,95,14,(151,169,194))

class ReplayMode:
    kind='replay'
    def __init__(self,app,path):
        self.app=app;self.replay=Replay(path);self.playing=False;self.speed=1;self.next_action=0
        self.applying=False;self.error=''
        self.upcoming_uid=None
        self.upcoming_label=''
        self.card_names={}
        uid=0
        for definition in self.replay.data['catalog'].values():
            for _ in range(definition['copies']):
                self.card_names[uid]=definition['name'];uid+=1
        install_game(app,self.replay.game)
        self.prepare_upcoming()
    def after_command(self,*args): pass
    def is_bot_turn(self): return False
    def describe_card_command(self,item):
        role=('打呼者','打巴掌者')[item['player']]
        verb={'play':'出牌','discard':'棄牌','use_tool':'使用道具'}.get(item['action'],item['action'])
        name=self.card_names.get(item.get('card_uid'),'')
        return f'{role} {verb}：{name}'

    def prepare_upcoming(self):
        """只預告回放的下一步，不呼叫 dispatch，也不消耗卡牌。"""
        a=self.app;r=self.replay
        self.upcoming_uid=None;self.upcoming_label=''
        a.selected=None;a.inspect_tool=False;a.detail_scroll=0
        if r.cursor>=len(r.data['commands']): return
        item=r.data['commands'][r.cursor]
        if item['action'] in ('play','discard'):
            hand=a.game.players[a.game.active].hand
            index=next((i for i,c in enumerate(hand) if c.uid==item.get('card_uid')),None)
            if item['player']==a.game.active and index is not None:
                self.upcoming_uid=item['card_uid']
                self.upcoming_label='下一步｜'+self.describe_card_command(item)
                a.selected=self.upcoming_uid
                if index<a.hand_offset: a.hand_offset=index
                elif index>=a.hand_offset+4: a.hand_offset=index-3
        elif item['action']=='use_tool' and a.game.players[a.game.active].tool:
            a.inspect_tool=True
            tool=a.game.players[a.game.active].tool
            self.upcoming_label='準備使用道具：'+a.game.catalog[tool.card.definition]['name']
        # 即使倍速播放，卡牌也至少顯示 0.6 秒。
        delay=max(600,int(850/self.speed)) if self.upcoming_label else int(850/self.speed)
        self.next_action=pygame.time.get_ticks()+delay

    def last_card_label(self):
        for item in reversed(self.replay.data['commands'][:self.replay.cursor]):
            if item['action'] in ('play','discard'):
                return '剛才：'+self.describe_card_command(item)
        return ''
    def move(self,delta=1,automatic=False):
        if not automatic: self.playing=False
        previous=self.app.game.x
        try:
            if delta<0:
                self.replay.seek(self.replay.cursor-1)
                self.app.game=self.replay.game
                self.app.camera_x=self.app.camera_from=self.app.camera_target=self.app.game.x
            else:
                if not self.replay.step(): self.playing=False;return
                self.app.game=self.replay.game
                if self.app.game.x!=previous:
                    self.app.camera_from=self.app.camera_x;self.app.camera_target=self.app.game.x
                    self.app.camera_started=pygame.time.get_ticks()
            self.app.selected=None;self.app.inspect_tool=False;self.app.hand_offset=0
            self.app.events()
            self.prepare_upcoming()
        except Exception as error:
            self.error=str(error);self.playing=False;self.app.notify('回放停止：'+str(error))
    def restart(self):
        self.playing=False;self.replay.reset();install_game(self.app,self.replay.game)
        self.prepare_upcoming()
    def toggle(self):
        if self.error:return
        self.playing=not self.playing
    def cycle_speed(self):
        self.speed={1:2,2:4,4:1}[self.speed];self.app.camera_duration=int(650/self.speed)
    def tick(self):
        if self.playing and not self.app.camera_moving() and not self.app.log_open and pygame.time.get_ticks()>=self.next_action:
            self.move(automatic=True)
    def banner(self):
        self.app.text(f'回放：{self.replay.path.stem}｜空白鍵播放／暫停，左右鍵逐步｜不影響成就',42,95,14,(151,169,194))
    def controls(self):
        a=self.app;r=self.replay
        a.button('上一步',(45,475,130,46),lambda:self.move(-1),r.cursor>0)
        a.button('暫停' if self.playing else '播放',(185,475,130,46),self.toggle,r.cursor<len(r.data['commands']))
        a.button('下一步',(325,475,130,46),self.move,r.cursor<len(r.data['commands']))
        a.button('重新播放',(465,475,130,46),self.restart)
        a.button(f'速度 {self.speed}x',(605,475,130,46),self.cycle_speed)
        a.text(f'操作 {r.cursor} / {len(r.data["commands"])}',795,486,20,(247,204,113))
        label=self.upcoming_label or self.last_card_label()
        item=r.data['commands'][r.cursor] if self.upcoming_label else (r.data['commands'][r.cursor-1] if r.cursor else {})
        reason=item.get('decision','')
        detail=(label+' ｜ '+reason) if label and reason else label or reason
        if detail:
            a.text(detail[:78],45,523,13,(247,204,113) if self.upcoming_label else (151,169,194))

def start_bot(app,path,human_role=0):
    mode=BotMode(app,path,human_role);app.lab_mode=mode;app.camera_duration=650

def start_replay(app,path):
    mode=ReplayMode(app,path);app.lab_mode=mode;app.camera_duration=650

class LabMenu:
    def __init__(self,app):
        self.app=app;self.page='home';self.offset=0;self.human_role=0;self.entries=[]
    def scroll(self,delta): self.offset=max(0,min(max(0,len(self.entries)-9),self.offset+delta))
    def profiles(self,human_role):
        self.human_role=human_role;self.page='profiles';self.offset=0;self.entries=[]
        root=bot_root(self.app)
        paths=list((self.app.root/'data/ai').glob('*.json'))+list((root/'profiles').glob('*.json'))+list((root/'results').glob('*/profiles/*.json'))
        for path in sorted(paths,reverse=True):
            try:
                data=json.loads(path.read_text(encoding='utf-8-sig'))
                if data.get('role')==1-human_role:
                    self.entries.append((f'{data["name"]}  /  {path.parent.parent.name}  /  {path.stem}',path))
            except (OSError,ValueError,KeyError): continue
    def replays(self):
        self.page='replays';self.offset=0;self.entries=[]
        root=bot_root(self.app)
        paths=list((self.app.root/'saves/replays').glob('*.json'))+list((self.app.root/'saves/test_replays').glob('*.json'))+list((root/'human_games').glob('*.json'))
        latest=root/'results/latest.json'
        if latest.exists():
            run=Path(json.loads(latest.read_text(encoding='utf-8'))['path'])
            paths+=list((run/'replays').glob('*.json'))
        for path in sorted(paths,reverse=True):
            try:
                data=json.loads(path.read_text(encoding='utf-8-sig'))
                result=data.get('metadata',{}).get('result',{})
                scores=data.get('final',{}).get('scores',[])
                label=f'{path.stem[:14]}  /  {result.get("snorer","人機")} vs {result.get("slapper","AI")}  /  {scores}'
                self.entries.append((label,path))
            except (OSError,ValueError): continue
    def open(self,path):
        try:
            if self.page=='profiles': start_bot(self.app,path,self.human_role)
            else: start_replay(self.app,path)
        except (ValueError,OSError,KeyError) as error: self.app.notify(str(error))
    def home(self): self.page='home';self.offset=0
    def draw(self):
        a=self.app
        a.text('測試 AI ／ 對局回放',45,35,32,(89,216,211))
        if self.page=='home':
            a.wrap('開發者工具：可選內附模型、本機回放；有 snorebot 時也會列出訓練模型與測試結果。此處的試打與回放不影響成就。',45,100,1110,20)
            a.button('我當打呼者，選 AI',(45,230,460,65),lambda:self.profiles(0),accent=True)
            a.button('我當打巴掌者，選 AI',(45,315,460,65),lambda:self.profiles(1))
            a.button('選擇回放',(45,400,460,65),self.replays)
            a.text('歷代策略可重複試打；回放包含每一步狀態校驗，規則版本不符會停止。',45,530,18,(151,169,194))
            a.button('返回主選單',(45,760,200,48),lambda:a.set_scene('menu'))
        else:
            a.text('選擇策略' if self.page=='profiles' else '選擇回放（最新實驗及人機對局）',45,100,23)
            a.text('滾輪捲動；舊實驗也可用 snorebot 的回放啟動檔開啟。',45,140,17,(151,169,194))
            if not self.entries: a.text('目前沒有可用檔案。',45,230,21)
            for i,(label,path) in enumerate(self.entries[self.offset:self.offset+9]):
                a.button(label[:90],(45,190+i*57,1185,48),lambda p=path:self.open(p))
            a.button('返回測試選單',(45,760,220,48),self.home)
            a.text(f'{len(self.entries)} 個檔案',1040,773,17,(151,169,194))
