"""固定盤面的互動教學；操作仍透過正式 Command，不保存教學對局。"""
import pygame
from .core import Game, Command

GOLD=(247,204,113)
CYAN=(89,216,211)
TEXT=(231,238,249)
MUTED=(151,169,194)
PANEL=(25,37,60)


def demo_game(role):
    config=dict(amplitude=50,period=12,interval=1.5,duration=24,
                initial_hand=3,hand_limit=3,preview=9,slaps=2,
                snore_score=10,snore_turn_score=1,slap_base=1.05,wave_fade=0.5)
    catalog={
        'ripple_reverse':dict(id='ripple_reverse',name='夢中逆流',category='波形',copies=5,
            description='未來18秒疊加一個起始朝下的波；只改變未來。',
            effects=[dict(kind='sin_add',amplitude=-45,period=5,duration=18)]),
        'swell':dict(id='swell',name='呼聲加倍',category='波形',copies=5,
            description='未來6秒將整體波形放大2倍。',effects=[dict(kind='scale',factor=2,duration=6)]),
        'quiet':dict(id='quiet',name='輕聲細語',category='波形',copies=5,
            description='未來6秒將整體波形縮小為0.5倍。',effects=[dict(kind='scale',factor=.5,duration=6)])}
    game=Game(config,catalog,seed=20261124)
    if role==0:
        game.apply_effect(dict(kind='base_amplitude',factor=1.4))
        game.apply_effect(dict(kind='scale',factor=-1))
        game.wave.publish(0,game.effects)
    # 用正式流程走到示範起點：打呼者 x=3、打巴掌者 x=1.5。
    for _ in range(2 if role==0 else 1):
        game.dispatch(Command(game.active,'to_cards',expected_revision=game.revision))
        game.dispatch(Command(game.active,'skip',expected_revision=game.revision))
    player=game.players[role]
    pool=game.draw_pile+game.discard+player.hand
    player.hand=[]
    desired=('ripple_reverse','quiet','swell') if role==0 else ('swell','ripple_reverse','quiet')
    for kind in desired:
        card=next(c for c in pool if c.definition==kind)
        pool.remove(card);player.hand.append(card)
    game.draw_pile=pool;game.discard=[]
    for p in game.players:p.score=0
    game.achievements.new.clear()
    return game


class Tutorial:
    def __init__(self,app):
        self.app=app;self.stage='intro';self.role=0
        self.target_uid=None;self.applying=False;self.drawing_controls=False
        self.block_until=0;self.next_action=0;self.opponent_actions=[]
        self.animation=None
        app.lab_mode=None;app.scene='tutorial'
        app.message='';app.message_until=0;app.log_open=False

    def start_lesson(self,role):
        app=self.app;self.role=role
        game=demo_game(role)
        app.game=game;app.scene='battle'
        app.selected=None;app.inspect_tool=False;app.detail_scroll=0;app.hand_offset=0
        app._preview_key=None;app._preview_wave=None;app.log_open=False
        app.seen_events=len(game.events)
        app.camera_duration=650
        app.camera_x=app.camera_from=max(0,game.x-1.5)
        app.camera_target=game.x;app.camera_started=pygame.time.get_ticks()
        self.target_uid=game.players[role].hand[0].uid
        self.stage='snore_score' if role==0 else 'slap_cards'
        self.block_until=0;self.opponent_actions=[];self.animation=None

    def ready(self):
        return not self.app.camera_moving() and pygame.time.get_ticks()>=self.block_until

    def expected(self):
        return {
            'snore_score':('score','取得分數'),
            'snore_cards':('to_cards','前往出牌階段'),
            'snore_play':('play','出牌並補滿'),
            'slap_cards':('to_cards','前往出牌階段'),
            'slap_play':('play','出牌並補滿'),
            'slap_hit':('slap','打巴掌！')}.get(self.stage)

    def button_enabled(self,label):
        if self.drawing_controls:return True
        expected=self.expected()
        return bool(self.ready() and expected and label==expected[1])

    def allow_command(self,action,uid):
        if self.applying:return True
        expected=self.expected()
        return bool(self.ready() and expected and action==expected[0]
                    and (action!='play' or uid==self.target_uid))

    def allow_selection(self,uid):
        return (self.ready() and self.stage in ('snore_select','snore_play','slap_select','slap_play')
                and uid==self.target_uid)

    def after_select(self):
        prefix='snore' if self.role==0 else 'slap'
        self.stage=prefix+('_play' if self.app.selected==self.target_uid else '_select')

    def after_command(self,actor,action,uid):
        now=pygame.time.get_ticks()
        if action in ('score','slap'):
            kind='snore_scored' if action=='score' else 'slapped'
            event=next(e for e in reversed(self.app.game.events) if e['type']==kind)
            self.animation=dict(kind='score',text=f'+{event["points"]} 分',start=now)
            self.block_until=now+650
        elif action=='play':
            event=next(e for e in reversed(self.app.game.events) if e['type']=='card_played' and e['card_uid']==uid)
            self.animation=dict(kind='card',text=self.app.game.catalog[event['card_id']]['name'],start=now)
            self.block_until=now+750
        if self.applying:return
        transitions={'snore_score':'snore_cards','snore_cards':'snore_select',
                     'snore_play':'snore_done','slap_cards':'slap_select',
                     'slap_play':'slap_opponent','slap_hit':'slap_done'}
        self.stage=transitions.get(self.stage,self.stage)
        if self.stage=='slap_opponent':
            self.opponent_actions=['score','to_cards','skip']
            self.next_action=now+1000

    def tick(self):
        if self.stage!='slap_opponent' or not self.ready() or pygame.time.get_ticks()<self.next_action:return
        action=self.opponent_actions.pop(0)
        self.applying=True
        try:self.app.command(action)
        finally:self.applying=False
        self.next_action=pygame.time.get_ticks()+750
        if not self.opponent_actions:self.stage='slap_hit'

    def finish(self):
        app=self.app
        app.preferences['tutorial_done']=True
        error=None
        try:app.save_preferences()
        except OSError as exc:error=exc
        app.tutorial=None;app.game=None;app.scene='menu'
        app.start_game()
        if error:app.notify('教學已結束，但無法儲存完成紀錄：'+str(error))

    def cancel(self):
        self.app.tutorial=None;self.app.game=None
        self.app.set_scene('menu')

    def draw_intro(self):
        a=self.app
        a.text('先玩兩段互動教學',65,65,38,CYAN)
        a.wrap('親自點按鈕、選牌與出牌。盤面已準備好，跟著金色提示完成即可。',68,126,1120,21,MUTED)
        lessons=[('1  打呼者','落點低於 -50，也能得分。','親自得分 → 選牌預覽 → 出牌補牌 → 自動換人。'),
                 ('2  打巴掌者','先出牌，為自己的下一次落點鋪路。','選牌加倍 → 觀看對手回合 → 在正值落點打巴掌。')]
        for i,(title,line,flow) in enumerate(lessons):
            x=65+i*590
            a.panel((x,220,555,280))
            a.text(title,x+25,250,29,GOLD)
            a.wrap(line,x+25,313,505,22)
            a.wrap(flow,x+25,370,505,19,MUTED)
        a.wrap('這是獨立示範，不計成就，也不改你儲存的對局設定。隨時可以跳過，之後從主選單重看。',68,545,1120,19,MUTED)
        a.button('開始互動教學',(65,650,310,60),lambda:self.start_lesson(0),accent=True)
        a.button('跳過教學，直接開始',(405,650,330,60),self.finish)
        a.button('返回主選單',(765,650,280,60),self.cancel)

    def draw_overlay(self):
        a=self.app;g=a.game
        hints={
            'snore_score':('1/5  落點與得分','現在落點是 -70，低於 -50。打呼者在 +50 以上或 -50 以下，都能選擇得分。請按「取得分數」。'),
            'snore_cards':('2/5  進入出牌階段','得分已增加！超閾值也可以改選額外補牌。這次已得分，請按「前往出牌階段」。'),
            'snore_select':('3/5  選牌看預覽','請點選「夢中逆流」。紫色虛線是出牌後的預覽，青色線保留目前的波型。'),
            'snore_play':('4/5  出牌改變未來','這張牌只改變接下來的波型，過去不會被改寫。請按「出牌並補滿」。'),
            'snore_done':('5/5  補牌與自動換人','出牌後已補牌、自動換人並落點。你完成了「落點 → 行動 → 出牌 → 換人」！'),
            'slap_cards':('1/5  先為下一回合鋪路','目前落點為正，可以打巴掌，但次數有限。這次先按「前往出牌階段」，準備更高的落點。'),
            'slap_select':('2/5  選擇加倍牌','請點選「呼聲加倍」，比較紫色預覽與青色原波型；它將放大未來的波型。'),
            'slap_play':('3/5  把威脅留到下一次落點','這次輪到自己時，高度還不會立刻改變。按「出牌並補滿」，觀察下一次落點如何變高。'),
            'slap_opponent':('4/5  對手正在示範','打呼者會先得分，再略過出牌。等鏡頭回到你，就能看到加倍後的落點。'),
            'slap_hit':('4/5  正值落點打巴掌','輪到你了！正值落點可以打巴掌，越高得分越多。請按「打巴掌！」，看看得分與清除效果。'),
            'slap_done':('5/5  打完直接換人','得分後會清除可重置效果和道具，直接交回打呼者，不再出牌。巴掌用完仍會繼續到終點。')}
        step,hint=hints[self.stage]
        a.panel((30,8,1220,102),PANEL)
        pygame.draw.rect(a.canvas,GOLD,(30,8,1220,102),3,border_radius=14)
        a.text(('教學 1/2｜打呼者' if self.role==0 else '教學 2/2｜打巴掌者')+' · '+step,48,17,22,GOLD)
        a.text(f'打呼 {g.players[0].score}：{g.players[1].score} 巴掌',770,19,19,CYAN)
        a.wrap(hint,48,53,975,17,TEXT,line_height=23,max_lines=2)
        self.drawing_controls=True
        try:
            a.button('跳過教學',(1060,20,165,36),self.finish)
            a.text('照金色框操作',1073,73,16,MUTED)
            if self.stage=='snore_done':
                a.button('前往打巴掌者示範',(850,475,380,46),lambda:self.start_lesson(1),enabled=self.ready(),accent=True)
            elif self.stage=='slap_done':
                a.button('完成教學，開始遊戲',(850,475,380,46),self.finish,enabled=self.ready(),accent=True)
        finally:self.drawing_controls=False
        focus=[]
        if self.stage in ('snore_score','slap_hit'):
            focus=[(40,119,1200,300),(45,475,150 if self.role==0 else 225,46)]
        elif self.stage in ('snore_cards','slap_cards'):
            focus=[(1010,475,225,46)]
        elif self.stage in ('snore_select','snore_play','slap_select','slap_play'):
            index=next(i for i,c in enumerate(g.players[g.active].hand) if c.uid==self.target_uid)
            focus=[(249+(index-a.hand_offset)*134,576,120,185)]
            if self.stage.endswith('_play'):focus.append((650,475,180,46))
        if self.ready():
            for rect in focus:pygame.draw.rect(a.canvas,GOLD,pygame.Rect(rect).inflate(8,8),3,border_radius=10)
        self.draw_animation()

    def draw_graph_hint(self,inner,left_x,pps,scale,cy,preview):
        if self.stage not in ('slap_select','slap_play'):return
        a=self.app;g=a.game
        x=g.x+2*g.stat('interval',g.active)
        if x>min(g.stat('duration'),a.camera_x+g.stat('preview',g.active)):return
        y=(preview or g.wave).value(x)
        px=inner.left+(x-left_x)*pps;py=cy-y*scale
        if not inner.collidepoint(px,py):return
        for top in range(inner.top,inner.bottom,12):
            pygame.draw.line(a.canvas,GOLD,(px,top),(px,min(top+6,inner.bottom)),1)
        pygame.draw.circle(a.canvas,GOLD,(int(px),int(py)),6)
        text=f'下次輪到你 {y:+.1f}'
        width,height=a.assets.font(15).size(text)
        label_x=min(inner.right-width-6,max(inner.left+6,px+10))
        label_y=max(inner.top+5,py-height-10)
        a.panel((label_x-3,label_y-2,width+6,height+4),(15,22,40),4)
        a.text(text,label_x,label_y,15,GOLD)

    def draw_animation(self):
        if not self.animation:return
        elapsed=pygame.time.get_ticks()-self.animation['start']
        if elapsed>=750:return
        t=elapsed/750
        if self.animation['kind']=='score':
            a=self.app
            a.text(self.animation['text'],555,215-int(t*45),32,GOLD)
        else:
            t=t*t*(3-2*t)
            center=(int(310+330*t),int(660-360*t))
            size=(int(120-35*t),int(185-85*t))
            ghost=pygame.Surface(size,pygame.SRCALPHA)
            ghost.fill((*PANEL,int(220*(1-t))))
            pygame.draw.rect(ghost,(*GOLD,int(255*(1-t))),ghost.get_rect(),2,border_radius=10)
            title=self.app.assets.font(16).render(self.animation['text'],True,GOLD)
            title.set_alpha(int(255*(1-t)));ghost.blit(title,title.get_rect(center=(size[0]//2,size[1]//2)))
            self.app.canvas.blit(ghost,ghost.get_rect(center=center))
