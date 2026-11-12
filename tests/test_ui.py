"""可選 Pygame 無視窗測試：沒有圖像依賴時跳過。"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
if sys.platform=='win32' and sys.version_info[:2]==(3,12):
    sys.path.insert(0,str(ROOT/'.vendor'))
try:
    import pygame
    from snorebattle.app import App,GOLD,PREVIEW
    from snorebattle.core import Game
except ModuleNotFoundError:
    pygame=None

@unittest.skipIf(pygame is None,'未安裝 Pygame，略過圖像測試')
class UITests(unittest.TestCase):
    def setUp(self):
        self.app=App(ROOT)
        self.app.game=Game(self.app.config,self.app.catalog,seed=17)
        self.app.scene='battle'
        self.app.seen_events=len(self.app.game.events)

    def tearDown(self):
        pygame.quit()

    def test_initial_action_and_center_marker(self):
        self.app.render()
        self.assertEqual(self.app.game.phase,'action')
        self.assertEqual(tuple(self.app.canvas.get_at((640,160)))[:3],GOLD)

    def test_automatic_landing_eased_camera_and_input_lock(self):
        app=self.app
        with patch('pygame.time.get_ticks',return_value=1000):
            app.command('to_cards')
            app.select(app.game.players[0].hand[0].uid)
            app.command('play')
            target=app.game.x
            self.assertEqual((app.game.active,app.game.phase),(1,'action'))
            app.render()
            self.assertEqual(app.camera_x,0)
            self.assertTrue(app.camera_moving())
            revision=app.game.revision
            app.command('to_cards')
            self.assertEqual(app.game.revision,revision)
        with patch('pygame.time.get_ticks',return_value=1325):
            app.render()
            self.assertAlmostEqual(app.camera_x,target/2)
            self.assertTrue(app.camera_moving())
        with patch('pygame.time.get_ticks',return_value=1650):
            app.render()
            self.assertAlmostEqual(app.camera_x,target)
            self.assertFalse(app.camera_moving())
            app.command('to_cards')
            self.assertEqual(app.game.phase,'cards')


    def test_click_preview_in_action_and_cards_and_cancel(self):
        app=self.app; g=app.game
        card=next(c for c in g.draw_pile+g.players[0].hand if c.definition=='ripple')
        if card in g.draw_pile: g.draw_pile.remove(card)
        else: g.players[0].hand.remove(card)
        g.players[0].hand.insert(0,card)
        app.render()
        app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(250,650)))
        self.assertEqual(app.selected,card.uid)
        self.assertEqual(g.phase,'action')
        app.render()
        def preview_pixel_count():
            return sum(tuple(app.canvas.get_at((x,y)))[:3]==PREVIEW
                       for x in range(641,805) for y in range(150,389))
        self.assertGreater(preview_pixel_count(),20)
        cached=app.selected_wave_preview()
        self.assertIs(cached,app.selected_wave_preview())
        app.command('to_cards')
        app.select(card.uid); app.render()
        self.assertGreater(preview_pixel_count(),20)
        self.assertEqual(g.phase,'cards')
        app.select(card.uid); app.render()
        self.assertIsNone(app.selected_wave_preview())
        self.assertEqual(preview_pixel_count(),0)

    def test_blackout_hides_both_wave_lines(self):
        app=self.app; g=app.game
        card=next(c for c in g.draw_pile+g.players[0].hand if c.definition=='ripple')
        if card in g.draw_pile:
            g.draw_pile.remove(card); g.players[0].hand.append(card)
        app.select(card.uid)
        g.apply_effect(dict(kind='blackout',duration=5,target='self'))
        app.render()
        count=sum(tuple(app.canvas.get_at((x,y)))[:3]==PREVIEW
                  for x in range(641,805) for y in range(150,389))
        self.assertEqual(count,0)

if __name__=='__main__': unittest.main()
