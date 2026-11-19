from copy import deepcopy
from pathlib import Path
import json
import math
import pygame
from .assets import Assets
from .core import Game,Command,RuleError,ROLES,load_data
from .scoring import slap_points
from .achievements import Achievements,DEFINITIONS

WIDTH,HEIGHT=1280,840
BG=(15,22,40); PANEL=(25,37,60); LINE=(53,70,98)
TEXT=(231,238,249); MUTED=(151,169,194); CYAN=(89,216,211)
CORAL=(255,146,124); GOLD=(247,204,113); PREVIEW=(220,159,255)
CATEGORIES={'波形':CYAN,'功能':(146,180,255),'特殊':(200,157,247),'道具':GOLD}
PHASES={'landing':'落點','action':'行動','cards':'出牌','handoff':'換人','ended':'結算'}
EVENT_NAMES={'card_played':'出牌','card_discarded':'棄牌','landed':'落點','slapped':'打巴掌',
 'snore_turn_scored':'打呼回合得分','snore_scored':'打呼得分','tool_used':'使用道具','deck_shuffled':'洗牌',
 'effects_cleared':'清除可重置效果','cards_drawn':'抽牌','turn_started':'回合開始',
 'tool_removed':'道具離場','card_skipped':'略過出牌','game_ended':'對局結束'}

class App:
    def __init__(self,root):
        pygame.init()
        self.root=Path(root)
        self.screen=pygame.display.set_mode((WIDTH,HEIGHT),pygame.RESIZABLE)
        pygame.display.set_caption('Snore Battle｜打呼卡牌對戰 · 基礎版')
        self.canvas=pygame.Surface((WIDTH,HEIGHT))
        self.assets=Assets(root)
        self.config,self.catalog=load_data(root)
        settings=self.root/'saves/settings.json'
        if settings.exists():
            try:
                saved=json.loads(settings.read_text(encoding='utf-8'))
                self.config.update(saved['config'])
                for key,count in saved['copies'].items():
                    if key in self.catalog: self.catalog[key]['copies']=max(0,int(count))
            except (ValueError,KeyError,TypeError): pass
        self.config.pop('slap_divisor',None)
        self.scene='menu'
        self.game=None
        self.running=True
        self.buttons=[]
        self.selected=None
        self.inspect_tool=False
        self.detail_scroll=0
        self._preview_key=None
        self._preview_wave=None
        self.hand_offset=0
        self.deck_offset=0
        self.message=''
        self.message_until=0
        self.log_open=False
        self.seen_events=0
        self.flash_until=0
        self.camera_x=0.0
        self.camera_from=0.0
        self.camera_target=0.0
        self.camera_started=0
        self.camera_duration=650
        self.clock=pygame.time.Clock()
        self.viewport=pygame.Rect(0,0,WIDTH,HEIGHT)

    def text(self,text,x,y,size=20,color=TEXT):
        self.canvas.blit(self.assets.font(size).render(str(text),True,color),(x,y))

    def wrap(self,text,x,y,width,size=18,color=TEXT,line_height=None,max_lines=20):
        font=self.assets.font(size)
        line=''; lines=[]
        for char in str(text):
            if char=='\n' or font.size(line+char)[0]>width:
                lines.append(line); line='' if char=='\n' else char
            else: line+=char
        if line: lines.append(line)
        for i,line in enumerate(lines[:max_lines]):
            self.text(line,x,y+i*(line_height or size+6),size,color)
        return len(lines)*(line_height or size+6)

    def panel(self,rect,color=PANEL,radius=14):
        pygame.draw.rect(self.canvas,color,rect,border_radius=radius)

    def button(self,label,rect,fn,enabled=True,accent=False):
        rect=pygame.Rect(rect)
        mouse=self.mouse()
        color=(48,100,108) if accent else (43,59,85)
        if enabled and rect.collidepoint(mouse): color=tuple(min(255,c+18) for c in color)
        if not enabled: color=(31,41,57)
        self.panel(rect,color,9)
        font=self.assets.font(18)
        rendered=font.render(label,True,TEXT if enabled else (92,108,131))
        self.canvas.blit(rendered,rendered.get_rect(center=rect.center))
        if enabled: self.buttons.append((rect,fn))

    def mouse(self):
        x,y=pygame.mouse.get_pos()
        v=self.viewport
        return ((x-v.x)*WIDTH/max(1,v.width),(y-v.y)*HEIGHT/max(1,v.height))

    def notify(self,message):
        self.message=message
        self.message_until=pygame.time.get_ticks()+6000

    def command(self,action):
        g=self.game
        if self.camera_moving():
            return
        previous_x=g.x
        try:
            g.dispatch(Command(g.active,action,self.selected,g.revision))
            self.selected=None
            self.inspect_tool=(action=='use_tool' and g.players[g.active].tool is not None)
            self.detail_scroll=0
            self.hand_offset=0
            if g.x != previous_x:
                self.camera_from=self.camera_x
                self.camera_target=g.x
                self.camera_started=pygame.time.get_ticks()
            self.events()
        except RuleError as error: self.notify(str(error))

    def camera_moving(self):
        return (abs(self.camera_target-self.camera_from)>1e-9
                and pygame.time.get_ticks()-self.camera_started<self.camera_duration)

    def update_camera(self):
        if not self.camera_moving():
            self.camera_x=self.camera_target
            return
        t=(pygame.time.get_ticks()-self.camera_started)/max(1,self.camera_duration)
        weight=t*t*(3-2*t)
        self.camera_x=self.camera_from+(self.camera_target-self.camera_from)*weight

    def events(self):
        for event in self.game.events[self.seen_events:]:
            if event['type']=='slapped':
                self.assets.sound('slap')
                self.flash_until=pygame.time.get_ticks()+650
            elif event['type']=='card_played': self.assets.sound('card')
            elif event['type']=='tool_used': self.assets.sound('tool')
        self.seen_events=len(self.game.events)
        if self.game.achievements.new:
            self.notify('成就解鎖：'+'、'.join(self.game.achievements.new))
            self.game.achievements.new.clear()

    def start_game(self):
        try:
            self.game=Game(deepcopy(self.config),deepcopy(self.catalog),self.root/'saves')
        except (ValueError,KeyError) as error:
            self.notify('設定有誤：'+str(error)); return
        self.scene='battle'
        self.camera_x=self.camera_from=self.camera_target=self.game.x
        self.selected=None
        self.inspect_tool=False
        self.detail_scroll=0
        self._preview_key=None
        self._preview_wave=None
        self.hand_offset=0
        self.seen_events=len(self.game.events)
        self.log_open=False

    def menu(self):
        self.text('SNORE / BATTLE',100,115,56,CYAN)
        self.text('一場關於睡眠、波形與巴掌的卡牌對戰',104,195,25)
        self.text('同機雙人基礎版 · 未來將擴充連線',106,240,18,MUTED)
        for i,(label,scene) in enumerate((('開始遊戲','setup'),('成就頁面','achievements'),('設定','settings'))):
            self.button(label,(108,330+i*76,280,58),lambda s=scene:self.set_scene(s),accent=i==0)
        self.text('操作：滑鼠選牌／按鈕，滾輪捲動手牌，F3 查看紀錄',106,690,18,MUTED)
        self.draw_character(950,430,True)
        self.text('先把夢做完，再看看誰贏。',816,610,23,GOLD)

    def set_scene(self,scene):
        self.scene=scene
        self.deck_offset=0

    def adjust(self,key,delta):
        minimum={'duration':3,'interval':.5,'period':1,'amplitude':1,
                 'hand_limit':1,'initial_hand':1,'preview':0,'slaps':1,
                 'snore_score':0,'snore_turn_score':0,'slap_base':1.0}[key]
        value=round(max(minimum,self.config[key]+delta),2)
        self.config[key]=int(value) if key=='snore_turn_score' else value

    def adjust_copies(self,key,delta):
        self.catalog[key]['copies']=max(0,min(99,self.catalog[key]['copies']+delta))

    def save_settings(self):
        path=self.root/'saves/settings.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(dict(config=self.config,copies={k:c['copies'] for k,c in self.catalog.items()}),
                                   ensure_ascii=False,indent=2),encoding='utf-8')
        self.notify('測試設定已儲存。')

    def settings(self):
        self.text('對局準備' if self.scene=='setup' else '設定',40,26,32,CYAN)
        self.text('全部數值與卡牌皆為測試內容；每局共用一副牌。',40,73,18,MUTED)
        fields=[('振幅／閾值','amplitude',1),('基礎週期','period',1),('落點間隔','interval',.5),
                ('遊戲總長度','duration',1),('初始手牌','initial_hand',1),('手牌上限','hand_limit',1),
                ('預覽長度','preview',1),('巴掌次數','slaps',1),('打呼固定分','snore_score',1),('巴掌底數','slap_base',.01),('打呼回合得分','snore_turn_score',1)]
        for i,(label,key,step) in enumerate(fields):
            col=i%2; row=i//2
            x=40+col*610; y=114+row*34
            self.text(label,x,y+4,18)
            self.text(f'{self.config[key]:g}',x+250,y+4,18,GOLD)
            self.button('-',(x+350,y,42,32),lambda k=key,d=-step:self.adjust(k,d))
            self.button('+',(x+400,y,42,32),lambda k=key,d=step:self.adjust(k,d))
        try:
            threshold_score=str(slap_points(self.config['amplitude'],self.config['slap_base']))
        except RuleError:
            threshold_score='超出範圍'
        if len(threshold_score)>18: threshold_score=threshold_score[:12]+'…'
        self.text(f'正閾值 +{self.config["amplitude"]:g}：巴掌 {threshold_score} 分',650,288,18,GOLD)
        self.text('共用牌堆組成',40,327,23)
        self.text('滾輪捲動清單；0 張表示不加入。',320,334,17,MUTED)
        self.text(f'總張數 {sum(c["copies"] for c in self.catalog.values())}',1030,334,19,GOLD)
        entries=list(self.catalog.items())
        for i,(key,card) in enumerate(entries[self.deck_offset:self.deck_offset+8]):
            y=370+i*43
            self.panel((40,y,1200,38),(22,33,53),6)
            self.text(card['category'],54,y+7,17,CATEGORIES[card['category']])
            self.text(card['name'],126,y+7,18)
            self.text(card['description'],320,y+9,15,MUTED)
            self.text(str(card['copies']),1090,y+7,18,GOLD)
            self.button('-',(1140,y+3,36,32),lambda k=key:self.adjust_copies(k,-1))
            self.button('+',(1184,y+3,36,32),lambda k=key:self.adjust_copies(k,1))
        self.button('返回',(40,770,140,46),lambda:self.set_scene('menu'))
        self.button('儲存設定',(200,770,160,46),self.save_settings)
        self.button('開始對局',(1040,770,200,46),self.start_game,accent=True)

    def achievements(self):
        self.text('成就紀錄',50,40,34,CYAN)
        progress=Achievements(self.root/'saves/achievements.json').unlocked
        for i,(key,(name,description)) in enumerate(DEFINITIONS.items()):
            y=125+i*130
            self.panel((50,y,1180,110))
            self.text(('已解鎖  ' if key in progress else '未解鎖  ')+name,75,y+15,24,
                      GOLD if key in progress else TEXT)
            self.wrap(description,75,y+57,1110,18,MUTED)
        self.text('這是測試成就組；解鎖紀錄跨對局保留，雙人共用本機檔案。',50,690,18,MUTED)
        self.button('返回',(50,765,150,48),lambda:self.set_scene('menu'))

    def selected_wave_preview(self):
        g=self.game
        key=(id(g),g.revision,g.x,g.y,self.selected)
        if key!=self._preview_key:
            self._preview_key=key
            self._preview_wave=g.preview_wave(self.selected)
        return self._preview_wave

    def draw_graph(self):
        g=self.game
        rect=pygame.Rect(40,119,1200,300)
        self.panel(rect)
        inner=pygame.Rect(58,149,1164,240)
        anchor=inner.centerx
        pps=52
        left_x=self.camera_x-(anchor-inner.left)/pps
        visible_end=min(g.stat('duration'),self.camera_x+g.stat('preview',g.active))
        preview=self.selected_wave_preview()
        preview_samples=[]
        samples=[]
        for px in range(inner.left,inner.right,3):
            x=left_x+(px-inner.left)/pps
            if 0<=x<=visible_end:
                samples.append((px,x,g.wave.value(x)))
                if preview is not None and x>=g.x:
                    preview_samples.append((px,x,preview.value(x)))
        max_y=max([g.config['amplitude']*1.6,abs(g.y)*1.15]
                  +[abs(y)*1.1 for _,_,y in samples]
                  +[abs(y)*1.1 for _,_,y in preview_samples])
        scale=105/max_y
        cy=inner.centery
        band=g.config['amplitude']*scale
        pygame.draw.rect(self.canvas,(29,56,64),(inner.left,cy-band,inner.width,band*2))
        for sign in (-1,1):
            yy=cy-sign*band
            pygame.draw.line(self.canvas,(92,132,118),(inner.left,yy),(inner.right,yy),1)
            self.text(f'{sign*g.config["amplitude"]:+g}',inner.left+5,yy-21,15,(141,187,153))
        pygame.draw.line(self.canvas,LINE,(inner.left,cy),(inner.right,cy))
        self.text('0',inner.left+5,cy+2,14,MUTED)
        for n in range(math.floor(left_x),math.ceil(left_x+inner.width/pps)+1):
            px=inner.left+(n-left_x)*pps
            if inner.left<=px<=inner.right and n>=0:
                pygame.draw.line(self.canvas,(34,48,72),(px,inner.top),(px,inner.bottom),1)
                self.text(str(n),px-4,inner.bottom+4,13,MUTED)
        hidden_start=max(inner.left,min(inner.right,anchor+g.stat('preview',g.active)*pps))
        if hidden_start<inner.right:
            self.panel((hidden_start,inner.top,inner.right-hidden_start,inner.height),(22,29,48),0)
            if inner.right-hidden_start>70: self.text('未知',hidden_start+14,inner.top+16,17,MUTED)
        if not g.stat('blackout',g.active):
            last=None
            for px,x,y in samples:
                py=cy-y*scale
                if last and px-last[0]<=4:
                    pygame.draw.line(self.canvas,CYAN if x>self.camera_x else (116,149,185),last[:2],(px,py),2)
                last=(px,py,x)
            last=None
            for index,(px,x,y) in enumerate(preview_samples):
                py=cy-y*scale
                if last and px-last[0]<=4 and index%5<3:
                    pygame.draw.line(self.canvas,PREVIEW,last,(px,py),3)
                last=(px,py)
            for point in g.points:
                px=inner.left+(point['x']-left_x)*pps
                py=cy-point['y']*scale
                if point['x']<=self.camera_x+1e-8 and inner.collidepoint(px,py):
                    pygame.draw.circle(self.canvas,CYAN if point['player']==0 else CORAL,(px,py),5)
            marker_y=g.wave.value(self.camera_x) if self.camera_moving() else g.y
            marker_py=cy-marker_y*scale
            pygame.draw.circle(self.canvas,GOLD,(anchor,marker_py),8)
            # 高度標籤屬於波形區，只在非關燈分支繪製。
            label=f'{marker_y:+.1f}'
            font=self.assets.font(17)
            label_width,label_height=font.size(label)
            label_x=max(inner.left+8,anchor-14-label_width)
            label_y=max(inner.top+4,min(inner.bottom-label_height-4,marker_py-label_height-8))
            self.panel((label_x-4,label_y-2,label_width+8,label_height+4),BG,5)
            self.text(label,label_x,label_y,17,GOLD)
        else:
            self.panel(inner,(7,10,18),0)
            self.text('關燈中：波形暫時不可見，落點判定仍有效',355,245,23,MUTED)
        pygame.draw.line(self.canvas,GOLD,(anchor,inner.top),(anchor,inner.bottom),1)
        end_px=inner.left+(g.stat('duration')-left_x)*pps
        if inner.left<=end_px<=inner.right:
            pygame.draw.line(self.canvas,CORAL,(end_px,inner.top),(end_px,inner.bottom),2)
            self.text('終點',min(end_px+5,inner.right-50),inner.top+4,16,CORAL)
        self.text('過去 ←',60,125,15,MUTED)
        if preview is not None and not g.stat('blackout',g.active):
            pygame.draw.line(self.canvas,CYAN,(150,134),(177,134),2)
            self.text('目前波形',185,125,15,CYAN)
            pygame.draw.line(self.canvas,PREVIEW,(282,134),(294,134),3)
            pygame.draw.line(self.canvas,PREVIEW,(301,134),(313,134),3)
            card=next(c for c in g.players[g.active].hand if c.uid==self.selected)
            self.text('選牌預覽：'+g.catalog[card.definition]['name'],322,125,15,PREVIEW)
        self.text('目前落點固定 1/2 · 未來 →',665,125,15,GOLD)

    def boundaries(self):
        boundaries=set()
        for start,effects in self.game.wave.versions:
            if math.isfinite(start): boundaries.add(start)
            boundaries.update(e.end for e in effects if e.end is not None)
        return boundaries

    def draw_character(self,x,y,sleeping):
        name='snorer' if sleeping else 'slapper'
        if name in self.assets.images:
            image=pygame.transform.smoothscale(self.assets.images[name],(140,170))
            self.canvas.blit(image,(x-70,y-85)); return
        bob=math.sin(pygame.time.get_ticks()/650)*4
        y+=bob
        color=CYAN if sleeping else CORAL
        pygame.draw.ellipse(self.canvas,(37,50,73),(x-65,y+30,130,30))
        pygame.draw.rect(self.canvas,color,(x-35,y-12,70,60),border_radius=20)
        pygame.draw.circle(self.canvas,(241,214,188),(x,y-40),35)
        for dx in (-13,13):
            pygame.draw.line(self.canvas,BG,(x+dx-5,y-44),(x+dx+5,y-44),3)
        pygame.draw.circle(self.canvas,BG,(x,y-24),5 if sleeping else 3)
        self.text('Z z z' if sleeping else '啪！' if pygame.time.get_ticks()<self.flash_until else '等你出牌',
                  x-43,y-116,24,color)

    def battle(self):
        g=self.game
        color=CYAN if g.active==0 else CORAL
        self.text(f'{ROLES[g.active]} 的回合',40,22,29,color)
        self.text(f'第 {g.turn} 回合  /  {PHASES[g.phase]}',40,68,18,MUTED)
        self.text(f'打呼 {g.players[0].score}  :  {g.players[1].score} 巴掌',420,26,26)
        self.text(f'巴掌 {g.slaps_left} 次',790,30,21,CORAL)
        self.button('紀錄 F3',(1000,25,115,42),self.toggle_log)
        self.button('主選單',(1130,25,110,42),lambda:self.set_scene('menu'))
        self.draw_graph()
        self.text(f'x = {g.x:g} / {g.stat("duration"):g}    間隔 {g.stat("interval",g.active):g}',
                  46,432,19,GOLD)
        self.text(f'牌堆 {len(g.draw_pile)}  棄牌 {len(g.discard)}  有效效果 {len(g.effects)}',820,434,17,MUTED)
        if self.camera_moving():
            self.text(f'鏡頭移動中 → {ROLES[g.active]} 行動階段',48,480,21,CYAN)
        elif g.phase=='landing':
            self.text('從上一個位置前進，再取得波形上的落點。',48,480,20)
            self.button('落點',(1010,472,225,50),lambda:self.command('land'),accent=True)
        elif g.phase=='action':
            if g.active==0:
                self.button('取得分數',(45,475,150,46),lambda:self.command('score'),g.eligible(),True)
                self.button('額外抽 1 張',(205,475,150,46),lambda:self.command('bonus_draw'),g.eligible())
            else:
                self.button('打巴掌！',(45,475,225,46),lambda:self.command('slap'),g.eligible(),True)
            self.button('查看道具',(420,475,145,46),self.select_tool,g.players[g.active].tool is not None,self.inspect_tool)
            self.button('使用道具',(420,475,160,46),lambda:self.command('use_tool'),g.tool_ready())
            self.button('棄掉道具',(590,475,160,46),lambda:self.command('discard_tool'),g.players[g.active].tool is not None)
            self.button('前往出牌階段',(1010,475,225,46),lambda:self.command('to_cards'),accent=True)
        elif g.phase=='cards':
            self.text('選一張手牌，再出牌或換牌；也可以略過。',45,482,19)
            selected=next((c for c in g.players[g.active].hand if c.uid==self.selected),None)
            can_play=selected is not None and ('tool' not in g.catalog[selected.definition] or g.players[g.active].tool is None)
            self.button('出牌並補滿',(650,475,180,46),lambda:self.command('play'),can_play,True)
            self.button('棄 1 抽 2',(840,475,180,46),lambda:self.command('discard'),selected is not None)
            self.button('略過出牌',(1030,475,200,46),lambda:self.command('skip'))
        elif g.phase=='handoff':
            self.text(f'交給 {ROLES[g.active]} 操作；不遮手牌。',45,482,20,color)
            self.button('開始此回合',(1010,475,225,46),lambda:self.command('next'),accent=True)
        elif g.phase=='ended':
            a,b=[p.score for p in g.players]
            result='平手' if a==b else ROLES[0 if a>b else 1]+' 獲勝'
            self.text('對局結束：'+result,48,480,27,GOLD)
            self.button('再玩一場',(1010,475,225,46),self.start_game,accent=True)
        self.draw_hand()
        self.draw_details()
        self.draw_character(105,660,False)
        self.draw_character(1175,660,True)
        self.text('打巴掌者',53,738,18,CORAL)
        self.text('打呼者',1133,738,18,CYAN)
        current=g.players[g.active]
        tool=current.tool
        if tool:
            name=g.catalog[tool.card.definition]['name']
            uses='永久' if tool.remaining is None else f'{tool.remaining} 次'
            self.button(f'道具：{name} / {uses}（點選查看）',(205,775,640,40),self.select_tool,accent=self.inspect_tool)
        else: self.text('道具欄：空',205,788,18,MUTED)
        self.text('完整紀錄：saves/logs/*.jsonl',40,820,13,MUTED)

    def draw_hand(self):
        g=self.game
        hand=g.players[g.active].hand
        self.text(f'{ROLES[g.active]} 手牌 {len(hand)} / 上限 {g.stat("hand_limit",g.active)}',205,540,19)
        self.text('滾輪／左右箭頭捲動',615,542,15,MUTED)
        self.hand_offset=min(self.hand_offset,max(0,len(hand)-4))
        self.button('‹',(165,625,30,56),lambda:self.scroll_hand(-1),self.hand_offset>0)
        self.button('›',(830,625,30,56),lambda:self.scroll_hand(1),self.hand_offset+4<len(hand))
        # 四張完整手牌；前後仍有牌時，在左右邊界各露出局部。
        viewport=pygame.Rect(205,576,610,185)
        previous_clip=self.canvas.get_clip()
        self.canvas.set_clip(viewport.clip(previous_clip))
        try:
            first=max(0,self.hand_offset-1)
            last=min(len(hand),self.hand_offset+5)
            for index in range(first,last):
                card=hand[index]
                i=index-self.hand_offset
                definition=g.catalog[card.definition]
                rect=pygame.Rect(249+i*134,576,120,185)
                selected=card.uid==self.selected
                self.panel(rect,(43,62,82) if selected else PANEL)
                accent=CATEGORIES[definition['category']]
                pygame.draw.rect(self.canvas,accent if selected else LINE,rect,2,border_radius=14)
                size=22
                while size>15 and self.assets.font(size).size(definition['name'])[0]>100:
                    size-=1
                title=self.assets.font(size).render(definition['name'],True,TEXT)
                self.canvas.blit(title,title.get_rect(center=rect.center))
                hit_rect=rect.clip(viewport)
                self.buttons.append((hit_rect,lambda uid=card.uid,index=index:self.select_hand(uid,index)))
        finally:
            self.canvas.set_clip(previous_clip)

    def select_hand(self,uid,index):
        if index<self.hand_offset:
            self.hand_offset=index
        elif index>=self.hand_offset+4:
            self.hand_offset=index-3
        self.select(uid)

    def select(self,uid):
        self.selected=None if self.selected==uid else uid
        self.inspect_tool=False
        self.detail_scroll=0

    def select_tool(self):
        if self.game.players[self.game.active].tool is None:
            return
        self.inspect_tool=not self.inspect_tool
        self.selected=None
        self.detail_scroll=0

    def selected_details(self):
        g=self.game
        player=g.players[g.active]
        if self.inspect_tool and player.tool:
            tool=player.tool
            remaining='永久使用' if tool.remaining is None else f'剩餘 {tool.remaining} 次'
            if player.turns<=tool.equipped_turn: status='下個自己的回合可用'
            elif g.tool_used: status='本回合已使用'
            else: status='行動階段可使用'
            return g.catalog[tool.card.definition],remaining+' · '+status
        card=next((c for c in player.hand if c.uid==self.selected),None)
        if card:
            definition=g.catalog[card.definition]
            return definition,definition['category']+'牌 · 手牌'
        return None

    def description_lines(self,text,width=193,size=17):
        lines=[]; line=''
        font=self.assets.font(size)
        for char in text:
            if char=='\n' or font.size(line+char)[0]>width:
                lines.append(line); line='' if char=='\n' else char
            else: line+=char
        if line: lines.append(line)
        return lines

    def draw_details(self):
        self.panel((880,540,225,275))
        self.text('卡牌／道具說明',896,552,18,MUTED)
        details=self.selected_details()
        if details is None:
            self.wrap('點選手牌或已裝備道具，查看完整效果。',896,604,193,19,MUTED)
            return
        definition,status=details
        self.text(definition['name'],896,584,22,CATEGORIES[definition['category']])
        self.wrap(status,896,622,193,14,MUTED,line_height=18,max_lines=2)
        lines=self.description_lines(definition['description'])
        self.detail_scroll=max(0,min(self.detail_scroll,max(0,len(lines)-6)))
        for i,line in enumerate(lines[self.detail_scroll:self.detail_scroll+6]):
            self.text(line,896,662+i*23,17)
        if len(lines)>6:
            self.text(f'滾輪閱讀 {self.detail_scroll+1}/{len(lines)-5}',896,798,12,MUTED)

    def scroll_hand(self,delta): self.hand_offset=max(0,self.hand_offset+delta)
    def toggle_log(self): self.log_open=not self.log_open

    def log_panel(self):
        # 模態紀錄視窗：開啟時不讓底下按鈕誤觸。
        self.buttons=[]
        shade=pygame.Surface((WIDTH,HEIGHT),pygame.SRCALPHA)
        shade.fill((0,0,0,190)); self.canvas.blit(shade,(0,0))
        self.panel((70,60,1140,725))
        self.text('事件紀錄 / DEBUG',100,83,28,CYAN)
        self.text(f'對局 {self.game.id[:12]}  seed {self.game.seed}  revision {self.game.revision}',100,129,17,MUTED)
        recent=[e for e in self.game.events if e['type'] in EVENT_NAMES][-19:]
        for i,event in enumerate(recent):
            player=ROLES[event['player']]
            name=EVENT_NAMES[event['type']]
            detail=''
            if 'card_id' in event: detail=self.game.catalog[event['card_id']]['name']
            if 'points' in event: detail+=f' +{event["points"]} 分'
            if event['type']=='cards_drawn': detail=f'{len(event["cards"])} 張'
            self.text(f'#{event["seq"]:03}  x={event["x"]:5.1f}  {player}  {name}  {detail}',100,175+i*27,17)
        self.text('詳細參數與抽牌結果均保存在 saves/logs，可用於追查規則。',100,710,17,MUTED)
        self.button('關閉 F3',(990,724,180,42),self.toggle_log)

    def render(self):
        self.buttons=[]
        self.update_camera()
        self.canvas.fill(BG)
        if 'background' in self.assets.images:
            self.canvas.blit(pygame.transform.smoothscale(self.assets.images['background'],(WIDTH,HEIGHT)),(0,0))
        {'menu':self.menu,'setup':self.settings,'settings':self.settings,
         'achievements':self.achievements,'battle':self.battle}[self.scene]()
        if self.scene=='battle' and self.log_open: self.log_panel()
        if self.message and pygame.time.get_ticks()<self.message_until:
            self.panel((300,7,680,46),(66,65,46),9)
            self.text(self.message[:40],318,18,18,GOLD)
        sw,sh=self.screen.get_size()
        ratio=min(sw/WIDTH,sh/HEIGHT)
        size=(max(1,int(WIDTH*ratio)),max(1,int(HEIGHT*ratio)))
        self.viewport=pygame.Rect((sw-size[0])//2,(sh-size[1])//2,*size)
        self.screen.fill((8,12,22))
        self.screen.blit(pygame.transform.smoothscale(self.canvas,size),self.viewport)
        pygame.display.flip()

    def handle(self,event):
        if event.type==pygame.QUIT: self.running=False
        elif event.type==pygame.KEYDOWN:
            if event.key==pygame.K_F3 and self.scene=='battle': self.toggle_log()
            elif event.key==pygame.K_ESCAPE:
                if self.log_open: self.log_open=False
                else: self.scene='menu'
            elif event.key in (pygame.K_LEFT,pygame.K_RIGHT) and self.scene=='battle':
                self.scroll_hand(-1 if event.key==pygame.K_LEFT else 1)
        elif event.type==pygame.MOUSEWHEEL and not self.log_open:
            if self.scene=='battle':
                if pygame.Rect(880,540,225,275).collidepoint(self.mouse()):
                    self.detail_scroll=max(0,self.detail_scroll-event.y)
                else: self.scroll_hand(-event.y)
            elif self.scene in ('setup','settings'):
                self.deck_offset=max(0,min(len(self.catalog)-8,self.deck_offset-event.y))
        elif event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
            v=self.viewport
            pos=((event.pos[0]-v.x)*WIDTH/v.width,(event.pos[1]-v.y)*HEIGHT/v.height)
            for rect,fn in reversed(self.buttons):
                if rect.collidepoint(pos):
                    fn(); break

    def run(self,smoke_frames=None,screenshot=None):
        frames=0
        self.render()
        while self.running:
            for event in pygame.event.get(): self.handle(event)
            self.render()
            self.clock.tick(60)
            frames+=1
            if smoke_frames and frames>=smoke_frames: break
        if screenshot:
            Path(screenshot).parent.mkdir(parents=True,exist_ok=True)
            pygame.image.save(self.canvas,str(screenshot))
        pygame.quit()



