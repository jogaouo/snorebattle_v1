"""互動教學：固定流程、操作限制與正式存檔隔離。"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'.vendor')]
os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import pygame
from snorebattle.app import App
from snorebattle.tutorial import demo_game


class TutorialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        shutil.copytree(ROOT/'data',self.root/'data')
        (self.root/'saves').mkdir()
        self.settings=self.root/'saves/settings.json'
        self.settings.write_text(json.dumps(dict(config=dict(amplitude=63,duration=37),copies=dict(ripple=0))),encoding='utf-8')
        self.achievements=self.root/'saves/achievements.json'
        self.achievements.write_text('{"first_game": {"date": "existing"}}',encoding='utf-8')
        (self.root/'saves/preferences.json').write_text('{"sfx_volume": 0.25}',encoding='utf-8')
        self.settings_before=self.settings.read_bytes();self.achievements_before=self.achievements.read_bytes()
        self.now=1000
        self.time=patch('pygame.time.get_ticks',side_effect=lambda:self.now);self.time.start()
        self.desktop=patch('pygame.display.get_desktop_sizes',return_value=[(1920,1080)]);self.desktop.start()
        self.app=App(self.root)

    def tearDown(self):
        self.desktop.stop();self.time.stop();pygame.quit();self.temp.cleanup()

    def ready(self):
        self.now+=1600;self.app.update_camera()

    def click(self,x,y):
        self.app.render();v=self.app.viewport
        pos=(round(v.x+x*v.width/1280),round(v.y+y*v.height/840))
        self.app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=pos))

    def start(self,role=0):
        self.app.request_start_game()
        self.assertEqual(self.app.scene,'tutorial')
        self.app.tutorial.start_lesson(role)
        self.ready()

    def assert_isolated(self):
        self.assertEqual(self.settings.read_bytes(),self.settings_before)
        self.assertEqual(self.achievements.read_bytes(),self.achievements_before)
        self.assertFalse((self.root/'saves/logs').exists())
        self.assertIsNone(self.app.game.save_dir)
        self.assertEqual(self.app.config['amplitude'],63)
        self.assertEqual(self.app.config['duration'],37)
        self.assertEqual(self.app.catalog['ripple']['copies'],0)

    def test_first_menu_click_opens_intro_and_guided_snorer_uses_real_controls(self):
        self.click(200,355)
        self.assertEqual(self.app.scene,'tutorial')
        self.click(200,675)
        self.ready()
        tutorial=self.app.tutorial;game=self.app.game
        self.assertEqual((game.active,game.phase),(0,'action'))
        self.assertAlmostEqual(game.y,-70)
        revision=game.revision
        self.app.command('to_cards')
        self.assertEqual(game.revision,revision)
        other=game.players[0].hand[1].uid
        self.app.select_hand(other,1)
        self.assertIsNone(self.app.selected)
        self.click(100,495)  # 取得分數
        self.assertEqual(game.players[0].score,10)
        self.assertEqual(tutorial.stage,'snore_cards')
        self.ready();self.click(1100,495)
        self.assertEqual(tutorial.stage,'snore_select')
        self.click(310,650)
        self.assertEqual(self.app.selected,tutorial.target_uid)
        preview=self.app.selected_wave_preview()
        self.assertIsNotNone(preview)
        self.assertNotEqual(preview.value(4.5),game.wave.value(4.5))
        self.click(720,495)
        self.assertEqual(tutorial.stage,'snore_done')
        self.assertEqual((game.active,game.phase),(1,'action'))
        self.assertEqual(len(game.players[0].hand),3)
        self.ready();self.app.render()
        self.assertFalse(self.app.message.startswith('成就解鎖'))
        self.assert_isolated()
        self.click(1000,495)
        self.assertEqual(self.app.tutorial.stage,'slap_cards')

    def test_slapper_prepares_wave_waits_for_opponent_then_scores_and_resets(self):
        self.start(1)
        tutorial=self.app.tutorial;game=self.app.game
        self.assertGreater(game.y,0)
        revision=game.revision
        self.app.command('slap')
        self.assertEqual(game.revision,revision)  # 先鋪路，不准提前出手。
        self.click(1100,495);self.click(310,650)
        before=game.wave.value(4.5)
        preview=self.app.selected_wave_preview()
        self.assertAlmostEqual(preview.value(4.5),before*2)
        self.click(720,495)
        self.assertEqual(tutorial.stage,'slap_opponent')
        self.assertEqual(game.active,0)
        revision=game.revision
        self.app.command('skip')
        self.assertEqual(game.revision,revision)
        for _ in range(6):
            self.now+=1000;self.app.render()
        self.assertEqual(tutorial.stage,'slap_hit')
        self.assertEqual((game.active,game.phase),(1,'action'))
        self.assertAlmostEqual(game.y,before*2)
        self.click(100,495)
        self.assertEqual(tutorial.stage,'slap_done')
        self.assertGreater(game.players[1].score,0)
        self.assertEqual(game.slaps_left,1)
        self.assertEqual((game.active,game.phase),(0,'action'))
        self.assertFalse(game.effects)
        self.ready();self.app.render()
        self.assert_isolated()
        with patch.object(self.app,'start_game') as start:
            self.click(1000,495)
            start.assert_called_once()
        saved=json.loads((self.root/'saves/preferences.json').read_text(encoding='utf-8'))
        self.assertTrue(saved['tutorial_done']);self.assertEqual(saved['sfx_volume'],.25)
        self.assertIsNone(self.app.tutorial)
        self.assertIsNone(self.app.game)
        self.assertEqual(self.settings.read_bytes(),self.settings_before)
        self.assertEqual(self.achievements.read_bytes(),self.achievements_before)

    def test_skip_completion_persists_and_rewatch_cancel_does_not_change_balance(self):
        self.app.request_start_game()
        with patch.object(self.app,'start_game') as start:
            self.app.tutorial.finish()
            start.assert_called_once()
        reloaded=App(self.root)
        self.assertTrue(reloaded.preferences['tutorial_done'])
        with patch.object(reloaded,'start_game') as start:
            reloaded.request_start_game();start.assert_called_once()
        reloaded.start_tutorial()
        self.assertEqual(reloaded.scene,'tutorial')
        reloaded.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE))
        self.assertEqual(reloaded.scene,'menu');self.assertIsNone(reloaded.tutorial)
        self.assertEqual(self.settings.read_bytes(),self.settings_before)
        self.assertEqual(self.achievements.read_bytes(),self.achievements_before)

    def test_finishing_intro_starts_formal_game_with_original_settings(self):
        self.app.request_start_game()
        self.app.tutorial.finish()
        self.assertIsNone(self.app.tutorial)
        self.assertEqual(self.app.scene,'battle')
        self.assertEqual(self.app.game.config['amplitude'],63)
        self.assertEqual(self.app.game.config['duration'],37)
        self.assertEqual(self.app.game.catalog['ripple']['copies'],0)
        self.assertEqual(self.app.game.save_dir,self.root/'saves')
        self.assertEqual(len(list((self.root/'saves/logs').glob('*.jsonl'))),1)
        self.assertTrue(self.app.preferences['tutorial_done'])
        self.assertEqual(self.settings.read_bytes(),self.settings_before)
        self.assertEqual(self.achievements.read_bytes(),self.achievements_before)

    def test_invalid_formal_settings_do_not_leave_an_unrestricted_demo(self):
        self.app.start_tutorial();self.app.tutorial.start_lesson(0)
        self.app.config['preview']=0  # 正式規則驗證不接受此設定。
        self.app.tutorial.finish()
        self.assertEqual(self.app.scene,'menu')
        self.assertIsNone(self.app.game)
        self.assertIsNone(self.app.tutorial)
        self.assertTrue(self.app.message.startswith('設定有誤'))

    def test_cancel_before_completion_will_offer_tutorial_again(self):
        self.app.request_start_game();self.app.tutorial.cancel()
        self.assertFalse(self.app.preferences['tutorial_done'])
        self.app.request_start_game();self.assertEqual(self.app.scene,'tutorial')
        self.app.tutorial.start_lesson(0)
        self.ready();self.app.game.achievements.new=['初次入夢']
        self.app.events()
        self.assertFalse(self.app.message.startswith('成就解鎖'))
        self.assert_isolated()

    def test_fixed_scenes_are_deterministic_and_cards_are_conserved(self):
        for role in (0,1):
            a,b=demo_game(role),demo_game(role)
            self.assertEqual((a.x,a.y,a.active),(b.x,b.y,b.active))
            cards=a.draw_pile+a.discard+sum([p.hand for p in a.players],[])
            self.assertEqual(len(cards),a.card_count)
            self.assertEqual(len({c.uid for c in cards}),a.card_count)
