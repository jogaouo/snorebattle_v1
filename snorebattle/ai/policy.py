"""兩個角色各一份參數，無神經網路；不匯入 Game 或讀取完整狀態。"""
import json
import math
import random
from copy import deepcopy
from pathlib import Path
from snorebattle.scoring import slap_points

DEFAULTS=dict(wave=2.0,forecast=1.2,hand_limit=1.5,bonus=2.5,time=.35,
              interval=.8,exchange=.9,tool=.4,blackout=.8,draw_bias=.4,
              slap_threshold=.9,urgency=1.0,explore=.04,
              growth=0.0,burst=0.0,precision=0.0,peak_fraction=.85,threat=0.0,buffer=1.2,harvest_score=250.0,win_safety=2.0,rebuild_time=12.0,late_score_multiplier=2.0,recent_weight=.35,landing=0.0,interval_explore=.25,shorten_bias=.8,control_explore=0.0,control_avoid=0.0,control_safety=0.0,loose_plan=0.0,burst_height=80.0)
BOUNDS=dict(wave=(0,6),forecast=(0,4),hand_limit=(0,4),bonus=(0,6),time=(0,2),
            interval=(0,3),exchange=(0,3),tool=(0,3),blackout=(0,3),draw_bias=(0,1),
            slap_threshold=(.1,12),urgency=(.3,3),explore=(0,.3),
            growth=(0,12),burst=(0,6),precision=(0,4),peak_fraction=(.4,1),threat=(0,4),buffer=(.5,3),harvest_score=(200,300),win_safety=(1,5),rebuild_time=(6,24),late_score_multiplier=(1.5,4),recent_weight=(0,1),landing=(0,5),interval_explore=(0,1),shorten_bias=(.5,1),control_explore=(0,1),control_avoid=(0,1),control_safety=(0,1),loose_plan=(0,1),burst_height=(40,160))

def profile(role,kind='heuristic'):
    weights=dict(DEFAULTS)
    if kind=='peak':
        if role==1:
            weights.update(growth=6,burst=2,precision=1.2,forecast=2.2,hand_limit=1.2,
                           bonus=.3,time=.2,interval=.3,slap_threshold=4,
                           exchange=.8,explore=.02,peak_fraction=.85,buffer=1.2,landing=1.5)
        else:
            weights.update(wave=4,forecast=2,hand_limit=2,threat=1.5,explore=.02,landing=1.5)
    return dict(schema=1,name=f'{kind}_{role}',role=role,kind=kind,weights=weights)

def load_profile(path):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if data.get('schema')!=1 or data.get('role') not in (0,1): raise ValueError('策略檔格式或角色錯誤')
    if data.get('kind') not in ('random','heuristic','peak'): raise ValueError('未知策略種類')
    weights=dict(DEFAULTS)
    if data['kind']=='peak': weights['landing']=1.5
    weights.update(data.get('weights',{}))
    weights.pop('harvest_height',None)
    for key,(lo,hi) in BOUNDS.items():
        if not isinstance(weights[key],(int,float)) or not math.isfinite(weights[key]) or not lo<=weights[key]<=hi:
            raise ValueError(f'策略參數 {key} 超出範圍')
    data['weights']=weights
    return data

def mutate(parent,rng,name):
    child=deepcopy(parent); child['name']=name
    for key in rng.sample(list(BOUNDS),4):
        lo,hi=BOUNDS[key]
        value=child['weights'][key]+rng.gauss(0,(hi-lo)*.12)
        child['weights'][key]=round(max(lo,min(hi,value)),5)
    if child['kind']=='peak' and child['role']==1:
        # 每個候選固定一個分數收割門檻，用同批種子比較，不是每回合亂換目標。
        child['weights']['harvest_score']=round(rng.uniform(200,300),2)
    return child

class Policy:
    def __init__(self,data,seed=0):
        self.data=deepcopy(data); self.rng=random.Random(seed)
        merged=dict(DEFAULTS)
        if self.data['kind']=='peak': merged['landing']=1.5
        merged.update(self.data['weights']);merged.pop('harvest_height',None);self.data['weights']=merged
        self.max_seen_peak=0.0
        self.last_slaps=None
        self.last_opponent_score=None
        self.last_score_x=None
        self.recent_opponent_rate=None
        self.opponent_gain=0.0
        self.last_reason=''

    def remember(self,o):
        if self.last_slaps is not None and o['slaps_left']<self.last_slaps:
            self.max_seen_peak=0.0
        self.last_slaps=o['slaps_left']
        visible=[y for x,y in o['future']]
        if o['y'] is not None: visible.append(o['y'])
        if visible:
            observed=max(max(0,y) for y in visible) if o['role']==1 else max(abs(y) for y in visible)
            self.max_seen_peak=max(self.max_seen_peak,observed)
        score=o['scores'][1-o['role']]
        if self.last_opponent_score is not None and o['x']>self.last_score_x:
            rate=max(0,(score-self.last_opponent_score)/(o['x']-self.last_score_x))
            self.recent_opponent_rate=rate if self.recent_opponent_rate is None else .35*rate+.65*self.recent_opponent_rate
        if self.last_score_x is None or o['x']>self.last_score_x:
            self.last_opponent_score=score;self.last_score_x=o['x']

    def projected_threat(self,o):
        # 只從當下公開比分估速，不拿單次最高增分一路外推，也不讀終局結果。
        score=o['scores'][0]
        baseline=o['turn_score']/max(1,2*o['interval'])
        average=score/max(o['x'],o['interval'],.5)
        recent=average if self.recent_opponent_rate is None else self.recent_opponent_rate
        weight=self.data['weights']['recent_weight']
        rate=max(baseline,(1-weight)*average+weight*recent)
        return score+max(0,o['duration']-o['x'])*rate*self.data['weights']['buffer']

    def harvest_context(self,o,w):
        remaining=max(0,o['duration']-o['x'])
        progress=o['x']/max(.5,o['duration'])
        # 巴掌清除波形；只有前段、還有下一次機會且時間足夠才估計能重建。
        can_rebuild=(progress<2/3 and remaining>=w['rebuild_time'] and o['slaps_left']>=2)
        projected=max(o['scores'][0],self.projected_threat(o))
        # 後段剩餘時間較少，不能再對整個預估終局分數硬乘固定兩倍。
        safety=1+(w['win_safety']-1)*max(0,1-progress)
        win_need=max(1,projected*safety-o['scores'][1]+1)
        useful=max(1,(projected-o['scores'][1]+1)/max(1,o['slaps_left']))
        visits=remaining/max(.5,o['interval'])/2
        # 最後兩次自己的落點附近，不能再守著整場相同的最低分。
        floor=w['harvest_score']*min(1,max(0,(visits-.5)/1.5))
        return dict(can_rebuild=can_rebuild,win_need=win_need,useful=useful,
                    visits=visits,floor=floor)

    def cashout_action(self,o,w):
        """先估實際得分，再依能否重建分成前段收割與後段最後一擊。"""
        if ('slap',None) not in o['legal'] or o['y'] is None: return None
        try:
            points=slap_points(o['y'],o['slap_base'],o['bonus'])
        except ValueError:
            return None
        context=self.harvest_context(o,w)
        if points>=max(context['floor'],context['win_need']):
            ratio=o['scores'][0]/max(1,o['scores'][1]+points)
            progress=o['x']/max(.5,o['duration'])
            self.last_reason=f'收尾：可得 {points:,} 分，比分比值 {ratio:.2f}／進度 {progress:.0%}，所需 {math.ceil(context["win_need"]):,} 分' 
            return ('slap',None)
        if context['can_rebuild']:
            target=max(w['harvest_score'],context['useful'])
            if points>=target:
                self.last_reason=f'前段收割：現在 {points:,} 分達標 {math.ceil(target):,}，尚有時間重建'
                return ('slap',None)
        else:
            # 後1/3或僅剩一次，不再把剩餘巴掌當作可重新養好的多次機會。
            target=max(w['harvest_score']*w['late_score_multiplier'],context['win_need'])
            if points>=target:
                self.last_reason=f'後段高分收割：現在 {points:,} 分，目標 {math.ceil(target):,} 分'
                return ('slap',None)
        return None

    def peak_action(self,o,w):
        if ('slap',None) not in o['legal']: return None
        cashout=self.cashout_action(o,w)
        if cashout:return cashout
        context=self.harvest_context(o,w)
        points=slap_points(o['y'],o['slap_base'],o['bonus']) if o['y'] is not None else None
        now=f'{points:,} 分' if points is not None else '關燈，無法估算'
        next_y=o.get('landings',{}).get('self')
        last_visible_good=(context['visits']<2 and next_y is not None and next_y<=0)
        if context['visits']<w['urgency'] or last_visible_good:
            reason='下一個可見落點不可打' if last_visible_good else '最後一次落點機會'
            self.last_reason=f'終盤收割：現在 {now}；{reason}，不再預留重建';return ('slap',None)
        if context['can_rebuild']:
            target=max(w['harvest_score'],context['useful'])
            self.last_reason=f'前段蓄力：現在 {now}，考慮 {math.ceil(target):,} 分以上先收割'
        else:
            target=max(w['harvest_score']*w['late_score_multiplier'],context['win_need'])
            self.last_reason=f'後段等高分：現在 {now}，目標約 {math.ceil(target):,} 分；預估難再重建'
        return ('to_cards',None)

    def choose(self,o):
        legal=o['legal']
        if not legal: raise ValueError('沒有合法操作')
        if self.data['role']!=o['role']: raise ValueError('策略角色不符')
        self.last_reason=''
        if self.data['kind']=='peak': self.remember(o)
        if self.data['kind']=='random':
            self.last_reason='隨機合法操作';return self.rng.choice(legal)
        w=self.data['weights']
        if self.data['kind']=='peak' and o['role']==1 and o['phase']=='action':
            cashout=self.cashout_action(o,w)
            if cashout:return cashout
            # 行動階段不隨機浪費有限巴掌；探索保留在出牌選擇與參數搜尋。
            return self.action(o,w)
        if o['role']==1 and o['phase']=='cards' and o['slaps_left'] and w['loose_plan']>=.5:
            preferred=[];reserved=set()
            before=o.get('landings',{}).get('self')
            for action,uid in legal:
                if action!='play':continue
                card=next(c for c in o['hand'] if c['uid']==uid)
                effects=card['definition']['effects']
                permanent=any(e['kind']=='base_amplitude' and e.get('factor',1)>1 for e in effects)
                ripple=any(e['kind']=='sin_add' and e.get('duration',0)>=18 for e in effects)
                burst=any(e['kind']=='scale' and e.get('factor',1)>=2 for e in effects)
                after=o.get('landing_previews',{}).get(card['id'],{}).get('self')
                if permanent:
                    preferred.append((3,self.card_value(o,card,w),uid,card['definition']['name'],'永久增幅優先'))
                elif ripple:
                    # 同級長波優先選較有利自己的下一落點；看不到時用既有估值。
                    value=after if after is not None else self.card_value(o,card,w)
                    preferred.append((2,value,uid,card['definition']['name'],'疊加18秒長波'))
                elif burst:
                    reserved.add(uid)
                    if before is not None and before>=w['burst_height'] and after is not None and after>before:
                        preferred.append((1,after,uid,card['definition']['name'],f'自己的下次落點 {before:.1f}→{after:.1f}，達到加倍時機'))
            if preferred:
                rank,value,uid,name,reason=max(preferred,key=lambda item:(item[0],item[1]))
                self.last_reason=f'蓄波計畫：{name}；{reason}'
                return ('play',uid)
            # 未達時機的加倍牌不出也不棄；一般探索與棄一抽二也遵守。
            legal=[(a,u) for a,u in legal if u not in reserved or a not in ('play','discard')]
        if o['role']==0 and o['phase']=='cards' and w['control_avoid']>=.5:
            # 只限制出牌；仍可棄掉反向控時牌補牌。一般探索也使用此篩選。
            def contrary(uid):
                card=next(c for c in o['hand'] if c['uid']==uid)
                for e in card['definition']['effects']:
                    condition=e.get('when','always');y=o['y']
                    if condition!='always' and y is not None and ((condition=='landing_negative')!=(y<0)):continue
                    if e.get('target','all') not in ('self','all'):continue
                    if (e['kind']=='interval' and e.get('amount',0)<0) or (e['kind']=='duration' and e.get('amount',0)>0):return True
                return False
            filtered=[(a,u) for a,u in legal if a!='play' or not contrary(u)]
            if filtered:legal=filtered
        if o['role']==0 and o['phase']=='cards' and w['control_safety']>=.5 and o['slaps_left']:
            def risk(y):
                if y is None:return None
                if y<=0:return 0
                try:return slap_points(y,o['slap_base'],o.get('opponent_bonus',0))
                except ValueError:return float('inf')
            current=risk(o.get('landings',{}).get('opponent'))
            defenses=[]
            for action,uid in legal:
                if action!='play':continue
                card=next(c for c in o['hand'] if c['uid']==uid)
                after=risk(o.get('landing_previews',{}).get(card['id'],{}).get('opponent'))
                if current is not None and current>=200 and after is not None and after<current:
                    defenses.append((after,-self.card_value(o,card,w),uid,card['definition']['name']))
            if defenses:
                after,_,uid,name=min(defenses)
                self.last_reason=f'優先控波：{name}，對手下一落點可得分 {current:,}→{after:,}'
                return ('play',uid)
            # 確認當前及改間隔後的新落點都低於200分，才允許控時。
            def safe_tempo(uid):
                card=next(c for c in o['hand'] if c['uid']==uid)
                tempo=any(e['kind'] in ('interval','duration') for e in card['definition']['effects'])
                if not tempo:return True
                after=risk(o.get('tempo_previews',{}).get(card['id']))
                return after==0 or (current is not None and current<200 and after is not None and after<200)
            filtered=[(a,u) for a,u in legal if a!='play' or safe_tempo(u)]
            if filtered:legal=filtered
        if o['role']==0 and o['phase']=='cards' and w['control_explore']>0:
            groups={'interval':[],'duration':[]};seen=set()
            for action,uid in legal:
                if action!='play':continue
                card=next(c for c in o['hand'] if c['uid']==uid)
                if card['id'] in seen:continue
                seen.add(card['id'])
                for e in card['definition']['effects']:
                    if e.get('when','always')!='always':continue
                    kind=e['kind'];amount=e.get('amount',0)
                    if (kind=='interval' and amount>0) or (kind=='duration' and amount<0 and o['duration']>0):
                        if e.get('target','all') in ('self','all'):
                            groups[kind].append((uid,card['definition']['name']))
            available=[items for items in groups.values() if items]
            if available and self.rng.random()<w['control_explore']:
                uid,name=self.rng.choice(self.rng.choice(available))
                self.last_reason=f'打緊探索：{name}（延長間隔／縮短總時長）'
                return ('play',uid)
        if self.rng.random()<w['explore']:
            self.last_reason='小機率探索';return self.rng.choice(legal)
        if o['phase']=='action':
            choice=self.action(o,w)
            if not self.last_reason:self.last_reason='依目前得分機會與道具用途選擇行動'
            return choice
        if self.data['kind']=='peak' and o['role']==1 and o['phase']=='cards' and o['slaps_left']:
            options=[];seen_interval=set()
            for action,uid in legal:
                if action!='play':continue
                card=next(c for c in o['hand'] if c['uid']==uid)
                if card['id'] in seen_interval:continue
                seen_interval.add(card['id'])
                delta=sum(e['amount'] for e in card['definition']['effects']
                          if e['kind']=='interval' and e.get('target','all') in ('self','all'))
                after=max(.5,o['interval']+delta)
                if abs(after-o['interval'])>1e-9:options.append((uid,card['definition']['name'],after))
            if options and self.rng.random()<w['interval_explore']:
                shorter=[c for c in options if c[2]<o['interval']]
                longer=[c for c in options if c[2]>o['interval']]
                pool=shorter if shorter and (not longer or self.rng.random()<w['shorten_bias']) else longer or shorter
                uid,name,after=self.rng.choice(pool)
                self.last_reason=f'間隔牌探索：{name}，間隔 {o["interval"]:g}→{after:g}'
                return ('play',uid)
        candidates=[]
        # 同種類牌的決策效果相同，只評估第一張，避免囤牌導致重複計算。
        seen=set()
        for action,uid in legal:
            if action=='skip': candidates.append((-.2,(action,uid))); continue
            card=next(c for c in o['hand'] if c['uid']==uid)
            if (action,card['id']) in seen: continue
            seen.add((action,card['id']))
            value=self.card_value(o,card,w)
            if action=='discard':
                # 棄一抽二可增一張；若卡有明顯用途，棄掉它的機會成本較高。
                value=w['exchange']-max(0,value)*.45
            candidates.append((value,(action,uid)))
        self.rng.shuffle(candidates)
        value,choice=max(candidates,key=lambda pair:pair[0])
        card=next((c for c in o['hand'] if c['uid']==choice[1]),None)
        self.last_reason=f'{choice[0]} {card["definition"]["name"] if card else ""}，策略評價 {value:.2f}'
        return choice

    def immediate_utility(self,o,y):
        if o['role_used'] or y is None: return 0
        if o['role']==0: return 1.0 if abs(y)+1e-8>=o['threshold'] else 0.0
        return max(0,y)/max(1,o['threshold']) if o['slaps_left'] else 0

    def action(self,o,w):
        legal=o['legal']; y=o['y']
        if ('use_tool',None) in legal and y is not None:
            amount=o['tool']['definition']['tool']['amount']
            moved=y-amount if y>0 else y+amount if y<0 else y
            gain=self.immediate_utility(o,moved)-self.immediate_utility(o,y)
            # 也考慮夢境重整的條件分支，但只有持牌時才有價值。
            if any(c['id']=='shuffle' for c in o['hand']) and y>=0 and moved<0: gain+=.4
            if gain>.05: return ('use_tool',None)
        if ('score',None) in legal:
            room=max(1,o['hand_limit'])
            if len(o['hand'])<room*w['draw_bias'] and o['duration']-o['x']>8*o['interval']:
                return ('bonus_draw',None)
            return ('score',None)
        if self.data['kind']=='peak' and o['role']==1:
            choice=self.peak_action(o,w)
            if choice:return choice
        if ('slap',None) in legal:
            turns_left=(o['duration']-o['x'])/max(.5,o['interval'])
            urgent=turns_left<=o['slaps_left']*2*w['urgency']
            if urgent or (y is not None and y>=o['threshold']*w['slap_threshold']): return ('slap',None)
        return ('to_cards',None)

    def wave_value(self,ys,o):
        if not ys: return 0
        t=max(1,o['threshold'])
        values=[]
        for x,y in ys:
            bound=50 if self.data['kind']=='peak' else 5
            h=max(-bound,min(bound,y/t))
            if o['role']==0:
                values.append(min(2,abs(h))-(.5+self.data['weights']['threat'])*max(0,h)**2
                              if self.data['kind']!='peak' or o['slaps_left'] else min(2,abs(h)))
            else: values.append(max(0,h)**1.5-.2*max(0,-h))
        return sum(values)/len(values)

    def card_value(self,o,card,w):
        value=0.0
        for e in card['definition']['effects']:
            condition=e.get('when','always'); y=o['y']
            if condition!='always':
                if y is not None and ((condition=='landing_negative')!=(y<0)): continue
                uncertainty=.5 if y is None else 1
            else: uncertainty=1
            k=e['kind']; a=e.get('amount',0)
            own=e.get('target','all')!='opponent'
            sign=1 if own else -1
            if k=='preview':
                marginal=1
                if self.data['kind']=='peak':
                    useful=min(max(0,o['duration']-o['x']),4*o['interval'])
                    marginal=max(0,min(1,(useful-o.get('preview_length',0))/max(1,abs(a))))
                value+=uncertainty*sign*a*w['forecast']*marginal
            elif k=='hand_limit':
                marginal=1 if self.data['kind']!='peak' else min(1,6/max(1,o['hand_limit']))
                value+=uncertainty*sign*a*w['hand_limit']*marginal
            elif k=='score_bonus': value+=uncertainty*sign*a*w['bonus']
            elif k=='duration':
                # 時間對打呼被動得分有利；領先的打巴掌者偏好縮短。
                value+=a*w['time']*(1 if o['role']==0 else -.8)
            elif k=='interval':
                delta=max(.5,o['interval']+a)-o['interval'] if self.data['kind']=='peak' and o['role']==1 else a
                value+=(-delta if o['role']==0 else delta)*w['interval']
            elif k=='blackout': value+=w['blackout'] if not own else -w['blackout']
            elif k=='reshuffle': value+=uncertainty*w['exchange']*.6
        if self.data['kind']=='peak' and o['role']==1:
            left=max(0,o['duration']-o['x'])
            for e in card['definition']['effects']:
                k=e['kind']
                if k=='base_amplitude' and o['slaps_left'] and left>2*o['interval']:
                    value+=w['growth']*math.log2(e['factor'])*min(1,left/12)
                elif k=='scale' and e['factor']>1 and o['slaps_left']:
                    next_x=o['x']+2*o['interval']
                    visible=[y for x,y in o['previews'].get(card['id'],[]) if abs(x-next_x)<=o['interval']*.3]
                    timing=1 if visible and max(visible)>0 else .25
                    value+=w['burst']*math.log2(e['factor'])*timing
                elif k=='interval' and o['slaps_left']:
                    value-=(max(.5,o['interval']+e['amount'])-o['interval'])*w['precision']
                elif k=='duration':
                    # 覆蓋舊版無條件偏好縮短：蓄力落後時爭取時間，安全領先時收尾。
                    value-=e['amount']*w['time']*(-.8)
                    investing=o['slaps_left']>0 and o['scores'][1]<self.projected_threat(o)
                    value+=e['amount']*w['time']*(1 if investing else -1)
                elif k in ('score_bonus','preview') and not o['slaps_left']:
                    value-=e['amount']*(w['bonus'] if k=='score_bonus' else w['forecast'])
        if 'tool' in card['definition']: value+=w['tool']
        if self.data['kind']=='peak' and card['id'] in o.get('landing_previews',{}):
            before=o['landings'];after=o['landing_previews'][card['id']]
            def payoff(height,bonus=0):
                try:return math.log1p(slap_points(height,o['slap_base'],bonus))
                except ValueError:return 700.0
            def expected(values):
                own=values['self'];opponent=values['opponent']
                if o['role']==1:
                    if own is None or own<=0 or not o['slaps_left']:return 0.0
                    return payoff(own,o['bonus'])
                reward=1.0 if own is not None and abs(own)>=o['threshold'] else 0.0
                risk=payoff(opponent) if opponent is not None and opponent>0 and o['slaps_left'] else 0.0
                return reward-risk
            value+=w['landing']*(expected(after)-expected(before))
        if card['id'] in o['previews']:
            value+=w['wave']*(self.wave_value(o['previews'][card['id']],o)-self.wave_value(o['future'],o))
        return value
