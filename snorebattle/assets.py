"""可換圖像／音效，不讓資源缺少阻止基本遊戲執行。"""
from pathlib import Path
import pygame

class Assets:
    def __init__(self, root):
        self.root=Path(root)/'assets'
        self.fonts={}
        candidates=[Path('C:/Windows/Fonts/msjh.ttc'),Path('C:/Windows/Fonts/msyh.ttc'),
                    self.root/'fonts/font.ttf']
        self.font_path=next((str(p) for p in candidates if p.exists()),None)
        self.images={}
        for name in ('snorer','slapper','background'):
            path=self.root/'images'/f'{name}.png'
            if path.exists():
                try: self.images[name]=pygame.image.load(str(path)).convert_alpha()
                except pygame.error: pass
        self.sounds={}
        if pygame.mixer.get_init():
            for name in ('card','slap','tool'):
                path=self.root/'audio'/f'{name}.wav'
                if path.exists():
                    try: self.sounds[name]=pygame.mixer.Sound(str(path))
                    except pygame.error: pass
            path=self.root/'audio/music.ogg'
            if path.exists():
                try:
                    pygame.mixer.music.load(str(path))
                    pygame.mixer.music.set_volume(.35)
                    pygame.mixer.music.play(-1)
                except pygame.error: pass

    def font(self,size):
        if size not in self.fonts: self.fonts[size]=pygame.font.Font(self.font_path,size)
        return self.fonts[size]

    def sound(self,name):
        if name in self.sounds: self.sounds[name].play()
