"""可序列化效果資料；處理器不依賴 pygame。"""
from dataclasses import dataclass, field
from math import sin, tau

@dataclass
class Effect:
    kind: str
    start: float
    end: float | None
    target: int | None
    params: dict = field(default_factory=dict)
    clear_on_slap: bool = True

    def active(self, x):
        return x >= self.start and (self.end is None or x < self.end)

WAVE_HANDLERS = {}
TOOL_HANDLERS = {}

def wave_handler(name):
    def register(fn):
        WAVE_HANDLERS[name] = fn
        return fn
    return register

@wave_handler('sin_add')
def add_sin(c, p, x, start):
    c['value'] += p['amplitude'] * sin(tau * (x-start) / p['period'])

@wave_handler('scale')
def scale(c, p, x, start):
    c['value'] *= p['factor']

def change_base(c, p, x, field, start):
    phase=c.get('phase',0.0)
    old = c['amplitude'] * sin(tau*x/c['period']+phase)
    if field=='period':
        old_period=c['period']
        c['period']*=p['factor']
        # 以出牌位置為錨點保留相位，不因後段出牌而從原點重新壓縮。
        c['phase']=phase+tau*start*(1/old_period-1/c['period'])
    else:
        c[field] *= p['factor']
    new = c['amplitude'] * sin(tau*x/c['period']+c.get('phase',0.0))
    # 依 FIFO 加入基礎分量差值，不回頭改寫較早的運算。
    c['value'] += new-old

@wave_handler('base_amplitude')
def amplitude(c, p, x, start):
    change_base(c, p, x, 'amplitude', start)

@wave_handler('base_period')
def period(c, p, x, start):
    change_base(c, p, x, 'period', start)

def toward_zero(game, player, params):
    amount = params['amount']
    # 固定距離朝 0 的方向移動，允許跨越；正好為 0 時沒有方向，不移動。
    if game.y > 0: game.y -= amount
    elif game.y < 0: game.y += amount

TOOL_HANDLERS['toward_zero'] = toward_zero

# 非波形效果由核心依領域處理，新增種類也需註冊而非依卡名判斷。
STAT_KINDS = {'preview', 'hand_limit', 'interval', 'duration', 'score_bonus', 'blackout'}
IMMEDIATE_KINDS = {'reshuffle'}
