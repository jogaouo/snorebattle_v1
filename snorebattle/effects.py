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

def change_base(c, p, x, field):
    old = c['amplitude'] * sin(tau*x/c['period'])
    c[field] *= p['factor']
    new = c['amplitude'] * sin(tau*x/c['period'])
    # 依加入順序加入基礎分量的差值；不回頭改寫較早的運算。
    c['value'] += new-old

@wave_handler('base_amplitude')
def amplitude(c, p, x, start):
    change_base(c, p, x, 'amplitude')

@wave_handler('base_period')
def period(c, p, x, start):
    change_base(c, p, x, 'period')

def toward_zero(game, player, params):
    amount = params['amount']
    game.y = max(0,game.y-amount) if game.y >= 0 else min(0,game.y+amount)

TOOL_HANDLERS['toward_zero'] = toward_zero

# 非波形效果由核心依領域處理，新增種類也需註冊而非依卡名判斷。
STAT_KINDS = {'preview', 'hand_limit', 'interval', 'duration', 'score_bonus', 'blackout'}
IMMEDIATE_KINDS = {'reshuffle'}
