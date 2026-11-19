"""純計分函式：不改遊戲狀態，可供畫面預估、規則與測試共用。"""
import math
from .errors import RuleError

def calculate_points(base_points, bonus=0, *, rounding='truncate'):
    """基礎分 + 加成 → 指定取整 → 最低 0 分。"""
    methods={'truncate':math.trunc,'ceil':math.ceil}
    if rounding not in methods:
        raise RuleError('未支援的分數取整方式')
    try:
        value=base_points+bonus
        if not math.isfinite(value):
            raise ValueError('non-finite score')
        return max(0,methods[rounding](value))
    except (OverflowError,ValueError,TypeError):
        raise RuleError('分數超出可計算範圍')

def slap_base_points(height, base=1.05):
    """只計算巴掌基礎分；加成與取整交給共用流程。"""
    try:
        value=math.pow(base,height)
        if not math.isfinite(value):
            raise ValueError('non-finite score')
        return value
    except (OverflowError,ValueError,TypeError):
        raise RuleError('巴掌分數超出可計算範圍，請調低底數或波形振幅')

def slap_points(height, base=1.05, bonus=0):
    """供設定頁預估得分；與實際加分使用同一組純函式。"""
    return calculate_points(slap_base_points(height,base),bonus,rounding='ceil')
