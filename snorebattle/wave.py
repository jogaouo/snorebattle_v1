"""保留歷史的有序波形：版本變更漸入，自然到期漸出。"""
from copy import deepcopy
from math import sin, tau
from .effects import WAVE_HANDLERS

def smoothstep(value):
    t = max(0.0, min(1.0, value))
    return t*t*(3-2*t)

class Wave:
    def __init__(self, amplitude, period, fade=1.0):
        self.amplitude, self.period = amplitude, period
        self.fade = max(0.0, float(fade))
        self.versions = [(float('-inf'), [])]

    def publish(self, x, effects):
        # 保留每次快照，即使同一 x 有多次更新也不覆寫過去的過渡來源。
        operations = deepcopy([e for e in effects if e.kind in WAVE_HANDLERS])
        self.versions.append((x, operations))

    def _pipeline(self, operations, x):
        c = dict(amplitude=self.amplitude, period=self.period, phase=0.0,
                 value=self.amplitude*sin(tau*x/self.period))
        for effect in operations:
            if not effect.active(x):
                continue
            before = c.copy()
            WAVE_HANDLERS[effect.kind](c, effect.params, x, effect.start)
            # 依 FIFO 順序把各處理器的變化量，在到期前逐步降到 0。
            weight = 1.0
            if effect.end is not None and self.fade > 0:
                weight = smoothstep((effect.end-x)/self.fade)
            for key in c:
                c[key] = before[key] + (c[key]-before[key])*weight
        return c['value']

    def _version_value(self, index, x):
        start, operations = self.versions[index]
        value = self._pipeline(operations, x)
        if index == 0 or self.fade <= 0 or x >= start+self.fade:
            return value
        # 連續快速出牌也從「當時仍在過渡的波形」接續，避免再次跳變。
        previous = self._version_value(index-1, x)
        weight = smoothstep((x-start)/self.fade)
        return previous + (value-previous)*weight

    def value(self, x):
        index = 0
        for i, (start, _) in enumerate(self.versions[1:], 1):
            if start >= x:
                break
            index = i
        value = self._version_value(index, x)
        return 0.0 if abs(value) < 1e-10 else value
