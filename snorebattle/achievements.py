"""以成功結算事件更新，與卡牌、畫面互相獨立。"""
import json
from pathlib import Path

DEFINITIONS = {
    'first_game': ('初次入夢', '完成一場對局。'),
    'triple_card': ('同一個夢', '同一位玩家連續三次出牌都是同一種卡；棄牌或略過會中斷。'),
    'both_sides': ('翻來覆去', '打呼者在一場內於正、負兩側都得過分。'),
    'three_slaps': ('叫醒服務', '一場內用完三次巴掌。'),
}

class Achievements:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.unlocked = {}
        if self.path and self.path.exists():
            try:
                self.unlocked = json.loads(self.path.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                pass
        self.streak = {0:(None,0), 1:(None,0)}
        self.sides = set()
        self.slaps = 0
        self.new = []

    def unlock(self, key, event):
        if key in self.unlocked:
            return
        self.unlocked[key] = event['timestamp']
        self.new.append(DEFINITIONS[key][0])
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.unlocked,ensure_ascii=False,indent=2), encoding='utf-8')
            temp.replace(self.path)

    def consume(self, event):
        kind, player = event['type'], event.get('player')
        if kind == 'card_played':
            previous, count = self.streak[player]
            card = event['card_id']
            count = count+1 if previous == card else 1
            self.streak[player] = (card,count)
            if count >= 3:
                self.unlock('triple_card', event)
        elif kind in ('card_discarded','card_skipped'):
            self.streak[player] = (None,0)
        elif kind == 'snore_scored':
            self.sides.add(1 if event['y'] >= 0 else -1)
            if len(self.sides)==2:
                self.unlock('both_sides',event)
        elif kind == 'slapped':
            self.slaps += 1
            if self.slaps >= 3:
                self.unlock('three_slaps',event)
        elif kind == 'game_ended':
            self.unlock('first_game',event)
