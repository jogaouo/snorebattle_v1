"""清單式、資料驅動的固定劇本教學；沿用正式Game與對戰畫面。"""
from copy import deepcopy
import json
import math
import pygame
from .core import Game,Command
from .scoring import slap_points

GOLD=(247,204,113)
CYAN=(89,216,211)
TEXT=(231,238,249)
MUTED=(151,169,194)
PANEL=(25,37,60)
GREEN=(141,205,153)
ACTION_LABELS={'score':'取得分數','slap':'打巴掌！','to_cards':'前往出牌階段','play':'出牌並補滿'}


def load_lessons(root):
    data=json.loads((root/'data/tutorial/lessons.json').read_text(encoding='utf-8-sig'))
    if data.get('schema')!=1:raise ValueError('教學劇本版本不支援')
    lessons={}
    for lesson in data['lessons']:
        if lesson['id'] in lessons:raise ValueError('教學關卡ID重複')
        if not lesson['steps'] or lesson['steps'][-1]['kind']!='finish':raise ValueError('教學缺少完成步驟')
        if any(s['kind'] not in ('info','command','select','auto','observe','finish','showcase') for s in lesson['steps']):raise ValueError('未知的教學步驟')
        lessons[lesson['id']]=lesson
    return lessons


def build_game(app,lesson):
    config=dict(amplitude=50,period=12,interval=1.5,duration=30,initial_hand=3,
                hand_limit=3,preview=9,slaps=3,snore_score=10,snore_turn_score=0,
                slap_base=1.05,wave_fade=.5)
    config.update(lesson['scenario'].get('config',{}))
    catalog=deepcopy(app.catalog)
    for card in catalog.values():card['copies']=6
    game=Game(config,catalog,seed=20261125)
    pool=sorted(game.draw_pile+game.discard+sum([p.hand for p in game.players],[]),key=lambda c:c.uid)
    def take(kind):
        card=next((c for c in pool if c.definition==kind),None)
        if card is None:raise ValueError('教學缺少卡牌：'+kind)
        pool.remove(card);return card
    for player in (0,1):game.players[player].hand=[take(kind) for kind in lesson['scenario']['hands'][str(player)]]
    next_draws=[take(kind) for kind in lesson['scenario'].get('draw_order',[])]
    game.draw_pile=pool+list(reversed(next_draws));game.discard=[]
    return game


class Tutorial:
    def __init__(self,app):
        self.app=app;self.lessons=load_lessons(app.root)
        self.page='home';self.lesson=None;self.role=0;self.step_index=0
        self.applying=False;self.drawing_controls=False
        self.block_until=0;self.next_action=0;self.animation=None;self.phase_banner=None;self.pending_step_until=0
        self.auto_index=0;self.announced=False;self.auto_label='';self.feedback='';self.error='';self.focus_started=0;self.graph_geometry=None
        app.lab_mode=None;app.scene='tutorial';app.game=None
        app.message='';app.message_until=0;app.log_open=False

    @property
    def current(self):
        if self.lesson is None:return None
        return self.lesson['steps'][self.step_index]

    @property
    def completed(self):
        return set(self.app.preferences.get('tutorial_completed',[])) & set(self.lessons)

    def start_lesson(self,lesson_id):
        lesson=self.lessons[lesson_id]
        try:game=build_game(self.app,lesson)
        except (ValueError,KeyError) as error:
            self.app.notify('教學資料有誤：'+str(error));return
        self.lesson=lesson;self.role=lesson['role']
        self.return_page='cards' if lesson['group']=='cards' else 'home'
        self.step_index=0;self.block_until=0;self.animation=None;self.error='';self.phase_banner=None;self.pending_step_until=0
        a=self.app;a.game=game;a.scene='battle';a.lab_mode=None
        a.selected=None;a.inspect_tool=False;a.detail_scroll=0;a.hand_offset=0
        a._preview_key=None;a._preview_wave=None;a.log_open=False
        a.seen_events=len(game.events);a.message='';a.message_until=0
        a.camera_duration=650;a.camera_x=a.camera_from=a.camera_target=game.x
        self.enter_step()

    def hidden_opponent(self):
        return bool(self.lesson and self.lesson['id'] in ('snorer','slapper') and self.app.game.active!=self.role)

    def banner_active(self):
        return bool(self.phase_banner and pygame.time.get_ticks()<self.phase_banner['start']+self.phase_banner['duration_ms'])

    def ready(self):
        return not self.pending_step_until and not self.banner_active() and not self.app.camera_moving() and pygame.time.get_ticks()>=self.block_until and not self.error

    def card_uid(self,kind):
        return next(c.uid for c in self.app.game.players[self.app.game.active].hand if c.definition==kind)

    def enter_step(self):
        self.focus_started=pygame.time.get_ticks()
        self.feedback='';self.auto_index=0;self.announced=False;self.auto_label=''
        self.next_action=pygame.time.get_ticks()+700
        if self.current['kind']=='select':
            self.app.selected=None
            if not self.current.get('quiz'):
                uid=self.card_uid(self.current['card'])
                index=next(i for i,c in enumerate(self.app.game.players[self.role].hand) if c.uid==uid)
                self.app.hand_offset=max(0,index-3)

    def advance(self):
        self.step_index+=1;self.enter_step()

    def illustrate_button(self,label):
        # 顯示真正的規則資格；教學步驟是否接受點擊仍由 button_enabled 控制。
        return bool(label=='打巴掌！' and self.lesson and self.lesson['id']=='slapper'
                    and self.app.game.active==self.role and self.app.game.eligible())

    def button_enabled(self,label):
        if self.drawing_controls:return True
        step=self.current
        if step and step.get('confirm_on_play') and label==ACTION_LABELS['play']:return self.ready()
        return bool(self.ready() and step and step['kind']=='command' and label==ACTION_LABELS.get(step['action']))

    def allow_command(self,action,uid):
        if self.applying:return True
        step=self.current
        if self.ready() and step and step.get('confirm_on_play') and action=='play':
            if uid is None:return False
            if uid!=self.card_uid(step['card']):
                self.feedback='不對喔，再想想吧！看看紫色預覽，哪張能讓下次落點達到得分區域？'
                return False
            self.advance()
            return True
        if not self.ready() or not step or step['kind']!='command' or self.app.game.active!=self.role:return False
        return action==step['action'] and (action!='play' or uid==self.card_uid(step['card']))

    def allow_selection(self,uid):
        step=self.current
        if not self.ready() or not step or self.app.game.active!=self.role:return False
        if step['kind']!='select' and not (step['kind']=='command' and step['action']=='play'):return False
        card=next((c for c in self.app.game.players[self.role].hand if c.uid==uid),None)
        if card is None:return False
        return bool(step.get('quiz') or card.definition==step['card'])

    def after_select(self):
        step=self.current
        if step['kind']=='select':
            if step.get('confirm_on_play'):
                self.feedback='';return
            if self.app.selected==self.card_uid(step['card']):self.advance()
            elif self.app.selected is not None:
                self.feedback='這張牌還不能達成目標。看下次落點的預覽，再比較其他牌。'
        elif step['kind']=='command' and step['action']=='play' and self.app.selected is None:
            self.step_index-=1;self.enter_step()

    def after_command(self,actor,action,uid):
        now=pygame.time.get_ticks();game=self.app.game
        if action in ('score','slap') and not (self.lesson['id'] in ('snorer','slapper') and actor!=self.role):
            kind='snore_scored' if action=='score' else 'slapped'
            event=next(e for e in reversed(game.events) if e['type']==kind)
            self.animation=dict(kind='score',text=f'+{event["points"]} 分',start=now)
            self.block_until=now+650
        elif action=='play' and not (self.lesson['id'] in ('snorer','slapper') and actor!=self.role):
            event=next(e for e in reversed(game.events) if e['type']=='card_played' and e['card_uid']==uid)
            self.animation=dict(kind='card',text=game.catalog[event['card_id']]['name'],start=now)
            self.block_until=now+750
        if action=='play' and self.lesson['id'] in ('snorer','slapper') and actor!=self.role:self.animation=None
        if action=='slap' and not self.applying:
            self.pending_step_until=now+3500
            return
        if not self.applying:self.advance()
        if self.lesson['id'] in ('snorer','slapper') and game.active==self.role and (action=='to_cards' or actor!=self.role):
            title='出牌階段' if game.phase=='cards' else '行動階段'
            hint='換你出牌了。試著替下一次落點創造機會吧！' if game.phase=='cards' else ('輪到你了！看看這次落點，能不能打巴掌？' if self.role==1 else '又輪到你了！看看這次的落點，能不能取得分數？')
            self.phase_banner=dict(title=title,hint=hint,start=now+650 if self.app.camera_moving() else now,duration_ms=2400)


    def tick(self):
        if self.pending_step_until:
            if pygame.time.get_ticks()>=self.pending_step_until:
                self.pending_step_until=0;self.advance()
            return
        if self.current and self.current['kind']=='showcase':
            if self.ready() and pygame.time.get_ticks()-self.focus_started>=self.current['duration_ms']:
                self.advance()
            return
        if not self.current or self.current['kind']!='auto' or not self.ready() or pygame.time.get_ticks()<self.next_action:return
        actions=self.current['actions']
        if self.auto_index>=len(actions):self.advance();return
        item=actions[self.auto_index]
        try:
            uid=self.card_uid(item['card']) if item.get('card') else None
            if uid is not None and not self.announced and not self.hidden_opponent():
                self.app.selected=uid;self.announced=True
                self.auto_label='示範出牌：'+self.app.game.catalog[item['card']]['name']
                self.next_action=pygame.time.get_ticks()+700;return
            self.app.selected=uid;self.applying=True
            revision=self.app.game.revision
            self.app.command(item['action'])
            if self.app.game.revision==revision:raise ValueError('劇本操作沒有成功：'+item['action'])
            self.auto_index+=1;self.announced=False;self.auto_label=''
            self.next_action=pygame.time.get_ticks()+650
        except (ValueError,KeyError,StopIteration) as error:
            self.error=str(error)
        finally:self.applying=False

    def acknowledge(self):
        if self.ready() and self.current['kind'] in ('info','observe'):self.advance()

    def return_to_list(self):
        a=self.app
        self.page=self.return_page;self.lesson=None
        a.game=None;a.scene='tutorial';a.selected=None;a.inspect_tool=False;a.log_open=False
        a.camera_x=a.camera_from=a.camera_target=0
        self.animation=None;self.error='';self.feedback='';self.pending_step_until=0

    def complete(self):
        if not self.ready() or self.current['kind']!='finish':return
        done=list(self.app.preferences.get('tutorial_completed',[]))
        if self.lesson['id'] not in done:done.append(self.lesson['id'])
        self.app.preferences['tutorial_completed']=done
        self.app.preferences['tutorial_done']=True
        try:self.app.save_preferences()
        except OSError as error:self.app.notify('完成標記無法儲存：'+str(error))
        self.return_to_list()

    def back(self):
        if self.lesson is not None:self.return_to_list()
        elif self.page=='cards':self.page='home'
        else:
            a=self.app;a.tutorial=None;a.game=None
            a.set_scene('menu')

    def text_context(self):
        g=self.app.game
        return dict(height=f'{g.y:+.1f}',slap_points=slap_points(g.y,g.config['slap_base'],g.stat('score_bonus',self.role)) if g.y>0 else 0,
                    slaps_left=g.slaps_left,slap_base=f'{g.config["slap_base"]:g}',
                    hand_limit=g.stat('hand_limit',self.role),preview=f'{g.stat("preview",self.role):g}',
                    interval=f'{g.stat("interval",self.role):g}',duration=f'{g.stat("duration"):g}')

    def format_text(self,text):
        return text.format(**self.text_context())

    def next_landing(self):
        a=self.app;g=a.game;interval=g.stat('interval',self.role)
        card=next((c for c in g.players[g.active].hand if c.uid==a.selected),None)
        if card:
            for effect in g.card_effects(g.catalog[card.definition]):
                if effect['kind']=='interval' and effect.get('target','all') in ('self','all'):
                    interval=max(.5,interval+effect['amount'])
        x=g.x+2*interval
        wave=a.selected_wave_preview() if a.selected is not None else None
        return x,(wave or g.wave).value(x)

    def draw_intro(self):
        a=self.app;done=self.completed
        a.text('新手教學' if self.page=='home' else '關於卡牌',65,50,38,CYAN)
        a.wrap('選一關親自操作。手牌、對手出牌和落點都已安排好；選對才能往下。',68,115,1120,20,MUTED)
        if self.page=='home':
            entries=[('snorer','關於打呼者','從不能得分開始，用出牌創造下一次得分，再自己答一次。'),
                     ('slapper','關於打巴掌者','先保留低分機會，出牌創造高點，再挑戰第二次出手。'),
                     ('cards','關於卡牌','分關體驗波型、建立優勢、時間與特殊效果。')]
        else:entries=[(l['id'],l['title'],l.get('summary','點選開始演示，依序認識卡牌效果。')) for l in self.lessons.values() if l['group']=='cards']
        for i,(id,title,description) in enumerate(entries):
            y=(205+i*125) if self.page=='home' else (175+i*125)
            a.panel((65,y,1150,108))
            a.text(title,90,y+16,26)
            a.text(description,92,y+62,18,MUTED)
            if id=='cards':
                total=sum(l['group']=='cards' for l in self.lessons.values())
                count=sum(l['group']=='cards' and l['id'] in done for l in self.lessons.values())
                finished=count==total
                badge=f'已完成 {count}/{total}' if finished else f'{count}/{total} 已完成'
            else:
                finished=id in done;badge='已完成' if finished else '未完成'
            if finished:
                pygame.draw.circle(a.canvas,GREEN,(766,y+31),11,2)
                pygame.draw.lines(a.canvas,GREEN,False,[(760,y+31),(765,y+36),(773,y+25)],2)
            a.text(badge,788 if finished else 755,y+22,18,GREEN if finished else MUTED)
            fn=(lambda:self.show_cards()) if id=='cards' else (lambda key=id:self.start_lesson(key))
            a.button('選擇教學' if id=='cards' else '重玩' if id in done else '開始演示',(950,y+27,240,48),fn,accent=True)
        a.button('返回上頁',(65,740,210,48),self.back)

    def show_cards(self):self.page='cards'

    def draw_overlay(self):
        a=self.app;g=a.game;step=self.current
        if self.pending_step_until:
            a.panel((305,80,670,70),PANEL)
            a.text('打巴掌！波形重置，直接換打呼者行動。',330,100,25,GOLD)
            self.draw_animation()
            return
        if self.banner_active():
            self.draw_phase_banner(self.phase_banner)
            return
        if step.get('presentation')=='locate_chances':
            self.draw_chance_location()
            return
        spotlight=bool(step.get('focus'))
        presentation=step.get('presentation')
        if spotlight:self.draw_spotlight(a.canvas.copy())
        elif presentation=='role_intro':self.draw_role_intro()
        elif presentation=='action_banner':self.draw_phase_banner()
        elif presentation in ('locate_score','locate_slap'):self.draw_score_location()
        a.panel((30,8,1220,102),PANEL)
        a.text(f'{self.lesson["title"]} · {self.step_index+1}/{len(self.lesson["steps"])}',48,17,22,GOLD)
        a.text(f'打呼 {g.players[0].score}：{g.players[1].score} 巴掌',770,19,19,CYAN)
        hint=('示範暫停，請返回清單重試。' if self.error else self.feedback or self.auto_label or (step.get('title','') if spotlight else step.get('hint')) or step.get('title',''))
        a.text('旁白',48,55,17,CYAN)
        a.wrap(self.format_text(hint),104,53,919,18,TEXT,line_height=25,max_lines=2)
        self.drawing_controls=True
        try:
            if step['kind']!='info':
                a.button('返回清單',(1060,20,165,36),self.return_to_list)
            a.text('依提示親自操作',1066,73,16,MUTED)
            if step['kind'] in ('observe','finish'):
                label='完成教學' if step['kind']=='finish' else '下一步'
                rect=(970,752,250,50) if spotlight or presentation=='role_intro' else (850,475,380,46)
                a.button(label,rect,self.complete if step['kind']=='finish' else self.acknowledge,enabled=self.ready(),accent=True)
        finally:self.drawing_controls=False
        if not spotlight:self.draw_focus()
        self.draw_animation()
        if step['kind']=='info':self.draw_info_card()

    def draw_role_intro(self):
        a=self.app
        shade=pygame.Surface((1280,840),pygame.SRCALPHA);shade.fill((0,0,0,155));a.canvas.blit(shade,(0,0))
        box_x=95 if self.role==0 else 220
        a.panel((box_x,205,960,320),PANEL)
        pygame.draw.rect(a.canvas,GOLD,(box_x,205,960,320),3,border_radius=18)
        a.text(self.current['title'],box_x+35,240,37,GOLD)
        a.wrap(self.format_text(self.current.get('hint',self.current.get('body',''))),box_x+35,318,870,24 if self.current.get('presentation')=='story' else 27,TEXT,line_height=36 if self.current.get('presentation')=='story' else 42,max_lines=4)
        a.text(self.current.get('footer','' if self.current.get('presentation')=='story' else '到終點時，分數比較高的人獲勝。'),box_x+35,460,25,CYAN)
        a.draw_character(1175 if self.role==0 else 105,660,self.role==0,awake=True)

    def draw_phase_banner(self,banner=None):
        a=self.app;step=banner or self.current
        started=step.get('start',self.focus_started)
        t=min(1,max(0,(pygame.time.get_ticks()-started)/step['duration_ms']))
        if t<.22:
            v=t/.22;v=1-(1-v)**3;x=-1280*(1-v)
        elif t>.8:
            v=(t-.8)/.2;x=1280*v*v*v
        else:x=0
        shade=pygame.Surface((1280,840),pygame.SRCALPHA);shade.fill((0,0,0,65));a.canvas.blit(shade,(0,0))
        banner=pygame.Surface((1280,150),pygame.SRCALPHA);banner.fill((*PANEL,245))
        pygame.draw.line(banner,GOLD,(0,1),(1279,1),3)
        pygame.draw.line(banner,GOLD,(0,148),(1279,148),3)
        title=a.assets.font(55).render(step.get('title','行動階段'),True,GOLD)
        subtitle=a.assets.font(21).render(step.get('hint',''),True,TEXT)
        banner.blit(title,title.get_rect(center=(640,53)))
        banner.blit(subtitle,subtitle.get_rect(center=(640,118)))
        for side in (120,170,1070,1120):
            pygame.draw.line(banner,GOLD,(side,40),(side-30,110),5)
        a.canvas.blit(banner,(round(x),285))

    def draw_chance_location(self):
        a=self.app
        rect=pygame.Rect(780,20,190,50)
        border=GOLD if math.sin((pygame.time.get_ticks()-self.focus_started)/180)>0 else CYAN
        pygame.draw.rect(a.canvas,border,rect.inflate(12,12),4,border_radius=12)
        a.panel((440,135,700,110),PANEL)
        a.text('剩餘的巴掌機會，在這裡！',465,151,27,GOLD)
        a.wrap('先記住它在戰鬥畫面上的位置。',465,197,650,21,TEXT,line_height=28,max_lines=1)
        self.draw_arrow((850,130),(875,80))

    def draw_score_location(self):
        a=self.app
        elapsed=pygame.time.get_ticks()-self.focus_started
        rect=pygame.Rect(45,475,150 if self.role==0 else 225,46)
        border=GOLD if math.sin(elapsed/180)>0 else CYAN
        pygame.draw.rect(a.canvas,border,rect.inflate(12,12),4,border_radius=12)
        a.panel((280,455,760,112),PANEL)
        pygame.draw.rect(a.canvas,GOLD,(280,455,760,112),2,border_radius=12)
        a.text(self.current['title'],305,467,26,GOLD)
        a.wrap(self.current['hint'],305,508,710,20,TEXT,line_height=28,max_lines=2)
        self.draw_arrow((278,500),(205 if self.role==0 else 270,499))

    def draw_spotlight(self,background):
        """只放大正式畫面截圖，不改遊戲座標、落點或操作範圍。"""
        a=self.app;step=self.current;focus=step['focus']
        elapsed=max(0,pygame.time.get_ticks()-self.focus_started)
        t=min(1,elapsed/650);ease=t*t*(3-2*t)
        shade=pygame.Surface((1280,840),pygame.SRCALPHA)
        shade.fill((0,0,0,int(165+25*ease)));a.canvas.blit(shade,(0,0))
        if focus in ('score_button','slap_button','slap_chances'):
            target=pygame.Rect(770,15,210,70) if focus=='slap_chances' else pygame.Rect(35,465,170 if focus=='score_button' else 245,66)
            dest=pygame.Rect(95,235,560,217)
        else:
            inner=self.graph_geometry[0]
            target=pygame.Rect(inner.centerx-300,inner.top,600,inner.height)
            dest=pygame.Rect(140,145,1000,400)
        wide=target.inflate(int(target.width*.35),int(target.height*.35))
        crop=pygame.Rect(*(round(v+(end-v)*ease) for v,end in zip(wide,target))).clip(background.get_rect())
        picture=pygame.transform.smoothscale(background.subsurface(crop),dest.size)
        a.canvas.blit(picture,dest)
        pygame.draw.rect(a.canvas,GOLD,dest.inflate(8,8),3,border_radius=12)
        if focus in ('score_button','slap_button','slap_chances'):
            self.draw_symbol('？' if focus=='score_button' else '！',590,175+int(math.sin(elapsed/170)*5))
            a.text('灰色：現在還不能按' if focus=='score_button' else '剩餘的出手機會' if focus=='slap_chances' else '亮起來：現在可以打！',175,485,24,GOLD)
            bubble=pygame.Rect(700,200,510,310)
            a.panel(bubble,PANEL)
            pygame.draw.rect(a.canvas,GOLD,bubble,2,border_radius=14)
            if self.role==0:pygame.draw.polygon(a.canvas,PANEL,[(1120,505),(1160,570),(1180,505)])
            a.text(step['title'],725,225,30,GOLD)
            a.wrap(self.format_text(step['hint']),725,290,460,23,TEXT,line_height=34,max_lines=6)
            a.draw_character(1175 if self.role==0 else 105,660,self.role==0,awake=True)
        else:
            inner,left_x,pps,scale,cy=self.graph_geometry
            marker_y=a.game.wave.value(a.camera_x) if a.camera_moving() else a.game.y
            def screen(x,y):return (dest.x+(x-crop.x)*dest.width/crop.width,dest.y+(y-crop.y)*dest.height/crop.height)
            mx,my=screen(inner.centerx,cy-marker_y*scale)
            upper=screen(inner.left,cy-a.game.config['amplitude']*scale)[1]
            lower=screen(inner.left,cy+a.game.config['amplitude']*scale)[1]
            if self.role==1:
                zero=screen(inner.left,cy)[1]
                if focus=='positive_landing':
                    glow=pygame.Surface(dest.size,pygame.SRCALPHA)
                    alpha=int(40+60*(.5+.5*math.sin(elapsed/240)))
                    pygame.draw.rect(glow,(*GOLD,alpha),(0,0,dest.width,max(0,min(dest.height,int(zero-dest.y)))))
                    a.canvas.blit(glow,dest)
                pygame.draw.line(a.canvas,GOLD,(dest.left,round(zero)),(dest.right,round(zero)),2)
                a.text('0：上方是正值',dest.left+20,round(zero)+8,22,GOLD)
                pygame.draw.circle(a.canvas,GOLD,(round(mx),round(my)),int(24+3*math.sin(elapsed/180)),3)
                self.draw_arrow((round(mx)-100,round(my)-80),(round(mx)-25,round(my)-20))
            elif focus=='next_landing':
                nx,ny=self.next_landing()
                px=inner.left+(nx-left_x)*pps
                mx,my=screen(px,cy-ny*scale)
                pygame.draw.circle(a.canvas,GOLD,(round(mx),round(my)),int(24+3*math.sin(elapsed/180)),3)
                self.draw_arrow((round(mx)-100,round(my)-90),(round(mx)-20,round(my)-20))
                a.text(f'下次輪到你：{ny:+.1f}',dest.x+25,dest.y+18,25,GOLD)
            elif focus=='landing':
                pygame.draw.circle(a.canvas,GOLD,(int(mx),int(my)),int(24+3*math.sin(elapsed/180)),3)
                self.draw_arrow((400,205),(int(mx)-45,int(my)-40))
                a.text('看這個數字',225,170,25,GOLD)
            else:
                glow=pygame.Surface(dest.size,pygame.SRCALPHA)
                alpha=int(35+85*(.5+.5*math.sin(elapsed/240)))
                up=max(0,min(dest.height,int(upper-dest.y)))
                down=max(0,min(dest.height,int(lower-dest.y)))
                pygame.draw.rect(glow,(*GOLD,alpha),(0,0,dest.width,up))
                pygame.draw.rect(glow,(*GOLD,alpha),(0,down,dest.width,dest.height-down))
                a.canvas.blit(glow,dest)
                a.text('可以得分！',dest.x+30,dest.y+18,25,GOLD)
                a.text('這裡也可以！',dest.x+30,int(lower)+25,25,GOLD)
            for y,label in (() if self.role==1 else ((upper,'+50'),(lower,'-50'))):
                pygame.draw.line(a.canvas,GOLD,(dest.left,int(y)),(dest.right,int(y)),2)
                a.panel((dest.right-82,int(y)-27,74,25),(15,22,40),4)
                a.text(label,dest.right-70,int(y)-27,20,GOLD)
            box_x=65 if self.role==0 else 300
            a.panel((box_x,575,915,170),PANEL)
            pygame.draw.rect(a.canvas,GOLD,(box_x,575,915,170),2,border_radius=14)
            a.text(step['title'],box_x+25,592,29,GOLD)
            a.wrap(self.format_text(step['hint']),box_x+25,640,860,22,TEXT,line_height=30,max_lines=3)
            a.draw_character(1175 if self.role==0 else 105,660,self.role==0,awake=True)

    def draw_symbol(self,symbol,x,y):
        font=self.app.assets.font(55)
        previous=font.get_bold()
        try:
            font.set_bold(True)
            picture=font.render(symbol,True,GOLD)
        finally:font.set_bold(previous)
        for dx,dy in ((0,0),(1,0),(0,1),(1,1)):
            self.app.canvas.blit(picture,(x+dx,y+dy))

    def draw_arrow(self,start,end):
        pygame.draw.line(self.app.canvas,GOLD,start,end,4)
        angle=math.atan2(end[1]-start[1],end[0]-start[0])
        points=[end]+[(end[0]-18*math.cos(angle+offset),end[1]-18*math.sin(angle+offset)) for offset in (-.5,.5)]
        pygame.draw.polygon(self.app.canvas,GOLD,points)

    def draw_focus(self):
        if not self.ready():return
        step=self.current;a=self.app;focus=[]
        if step['kind']=='command':
            rects={'score':(45,475,150,46),'slap':(45,475,225,46),'to_cards':(1010,475,225,46),'play':(650,475,180,46)}
            focus=[rects[step['action']]]
        elif step['kind']=='select':
            if step.get('quiz'):focus=[(205,576,610,185)]
            else:
                uid=self.card_uid(step['card']);index=next(i for i,c in enumerate(a.game.players[self.role].hand) if c.uid==uid)
                focus=[(249+(index-a.hand_offset)*134,576,120,185)]
        for rect in focus:pygame.draw.rect(a.canvas,GOLD,pygame.Rect(rect).inflate(8,8),3,border_radius=10)

    def draw_info_card(self):
        a=self.app;step=self.current
        if step.get('presentation')=='story':
            self.draw_role_intro()
            a.buttons=[]
            self.drawing_controls=True
            try:a.button('下一步',(510,642,260,46),self.acknowledge,enabled=self.ready(),accent=True)
            finally:self.drawing_controls=False
            return
        shade=pygame.Surface((1280,840),pygame.SRCALPHA);shade.fill((0,0,0,150));a.canvas.blit(shade,(0,0))
        a.buttons=[]
        a.panel((190,145,900,565),PANEL)
        pygame.draw.rect(a.canvas,GOLD,(190,145,900,565),3,border_radius=14)
        a.text(step['title'],220,175,29,GOLD)
        image=a.assets.tutorial_image(step.get('image'))
        if image is not None:
            ratio=min(840/image.get_width(),180/image.get_height())
            picture=pygame.transform.smoothscale(image,(max(1,int(image.get_width()*ratio)),max(1,int(image.get_height()*ratio))))
            a.canvas.blit(picture,picture.get_rect(center=(640,320)))
        else:
            a.panel((220,235,840,165),(34,48,72))
            a.wrap(step.get('emphasis',''),250,290,780,28,GOLD,line_height=36,max_lines=2)
        a.wrap(self.format_text(step['body']),225,435,830,21,TEXT,line_height=29,max_lines=6)
        self.drawing_controls=True
        try:
            a.button('下一步',(510,642,260,46),self.acknowledge,enabled=self.ready(),accent=True)
        finally:self.drawing_controls=False

    def draw_graph_hint(self,inner,left_x,pps,scale,cy,preview):
        self.graph_geometry=(inner.copy(),left_x,pps,scale,cy)
        if self.error or self.current['kind'] not in ('select','command') or self.app.game.active!=self.role:return
        a=self.app;g=a.game;x,y=self.next_landing()
        if x>min(g.stat('duration'),a.camera_x+g.stat('preview',self.role)):return
        px=inner.left+(x-left_x)*pps;py=cy-y*scale
        if not inner.collidepoint(px,py):return
        for top in range(inner.top,inner.bottom,12):pygame.draw.line(a.canvas,GOLD,(px,top),(px,min(top+6,inner.bottom)),1)
        pygame.draw.circle(a.canvas,GOLD,(int(px),int(py)),6)
        text=f'下次輪到你 x={x:g}  {y:+.1f}'
        width,height=a.assets.font(15).size(text)
        lx=min(inner.right-width-6,max(inner.left+6,px+10));ly=max(inner.top+5,py-height-10)
        a.panel((lx-3,ly-2,width+6,height+4),(15,22,40),4);a.text(text,lx,ly,15,GOLD)

    def draw_animation(self):
        if not self.animation:return
        elapsed=pygame.time.get_ticks()-self.animation['start']
        if elapsed>=750:return
        t=elapsed/750
        if self.animation['kind']=='score':self.app.text(self.animation['text'],555,215-int(t*45),32,GOLD)
        else:
            t=t*t*(3-2*t);center=(int(310+330*t),int(660-360*t));size=(int(120-35*t),int(185-85*t))
            ghost=pygame.Surface(size,pygame.SRCALPHA);ghost.fill((*PANEL,int(220*(1-t))))
            pygame.draw.rect(ghost,(*GOLD,int(255*(1-t))),ghost.get_rect(),2,border_radius=10)
            title=self.app.assets.font(16).render(self.animation['text'],True,GOLD);title.set_alpha(int(255*(1-t)))
            ghost.blit(title,title.get_rect(center=(size[0]//2,size[1]//2)));self.app.canvas.blit(ghost,ghost.get_rect(center=center))
