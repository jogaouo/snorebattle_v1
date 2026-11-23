"""可驗證、無副作用的命令回放；不讀取或寫入正式成就存檔。"""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
from .core import Game,Command

RULE_FILES=('core.py','effects.py','wave.py','scoring.py','errors.py')
def rules_fingerprint():
    root=Path(__file__).parent
    h=hashlib.sha256()
    for name in RULE_FILES:
        h.update(name.encode()); h.update((root/name).read_bytes())
    return h.hexdigest()

def state_digest(g):
    data=dict(revision=g.revision,phase=g.phase,active=g.active,x=g.x,y=g.y,
              players=[asdict(p) for p in g.players],draw=[asdict(c) for c in g.draw_pile],
              discard=[asdict(c) for c in g.discard],effects=[asdict(e) for e in g.effects],
              slaps=g.slaps_left,turn=g.turn,role_used=g.role_used,tool_used=g.tool_used,
              rng=g.rng.getstate(),wave=[(x,[asdict(e) for e in es]) for x,es in g.wave.versions])
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class Recorder:
    def __init__(self,g,metadata=None):
        self.data=dict(schema=1,rules=rules_fingerprint(),config=dict(g.config),
                       catalog=g.catalog,seed=g.seed,metadata=metadata or {},
                       initial=state_digest(g),commands=[])
    def append(self,g,command):
        self.data['commands'].append(dict(player=command.player,action=command.action,
                                         card_uid=command.card_uid,after=state_digest(g)))
    def save(self,path,g):
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        self.data['final']=dict(phase=g.phase,scores=[p.score for p in g.players],digest=state_digest(g))
        # catalog 的插入順序影響卡牌 UID，不可用 sort_keys 重排它。
        path.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf-8')

class Replay:
    def __init__(self,path):
        self.path=Path(path)
        self.data=json.loads(self.path.read_text(encoding='utf-8-sig'))
        if self.data.get('schema')!=1: raise ValueError('不支援的回放格式')
        if self.data['rules']!=rules_fingerprint():
            raise ValueError('遊戲規則版本與回放不符；請切回產生回放時的 Git 版本。')
        self.reset()
    def reset(self):
        d=self.data
        self.game=Game(d['config'],d['catalog'],seed=d['seed'])
        self.cursor=0
        if state_digest(self.game)!=d['initial']: raise ValueError('回放起始狀態不符')
    def step(self):
        if self.cursor>=len(self.data['commands']): return False
        item=self.data['commands'][self.cursor]
        self.game.dispatch(Command(item['player'],item['action'],item['card_uid'],self.game.revision))
        if state_digest(self.game)!=item['after']:
            raise ValueError(f'回放第 {self.cursor+1} 步狀態不符，已停止')
        self.cursor+=1
        return True
    def seek(self,cursor):
        self.reset()
        for _ in range(max(0,min(cursor,len(self.data['commands'])))): self.step()
