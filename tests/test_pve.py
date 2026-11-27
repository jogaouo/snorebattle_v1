"""獨立PvE、角色配對、玩家視角與開發者入口。"""
from copy import deepcopy
import hashlib
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
os.environ['SDL_VIDEODRIVER']='dummy';os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import pygame
from snorebattle.app import App
from snorebattle.ai.environment import observe
from snorebattle.ai.policy import Policy,profile
from snorebattle.replay import Replay,state_digest


class PvETests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        shutil.copytree(ROOT/'data',self.root/'data')
        self.now=1000
        self.time=patch('pygame.time.get_ticks',side_effect=lambda:self.now);self.time.start()
        self.app=App(self.root);self.app.preferences['tutorial_done']=True

    def tearDown(self):
        self.time.stop();pygame.quit();self.temp.cleanup()

    def test_public_menu_only_exposes_singleplayer_and_roles_match_frozen_profiles(self):
        labels=[];original=self.app.button
        def capture(label,*args,**kwargs):labels.append(label);return original(label,*args,**kwargs)
        with patch.object(self.app,'button',side_effect=capture):self.app.render()
        self.assertIn('單人模式',labels)
        self.assertNotIn('開始遊戲',labels);self.assertNotIn('測試 AI ／ 回放',labels)
        self.app.request_start_game();self.assertEqual(self.app.scene,'singleplayer')
        for role,name in [(0,'loose_1'),(1,'tight_0')]:
            with self.subTest(role=role):
                self.app.start_pve(role)
                mode=self.app.lab_mode
                self.assertEqual(self.app.scene,'battle');self.assertEqual(mode.kind,'pve')
                self.assertEqual(mode.profile['name'],name);self.assertEqual(mode.profile['role'],1-role)
                self.assertEqual(mode.human_role,role)
                self.assertEqual(self.app.game.save_dir,self.root/'saves')
                before=deepcopy(self.app.game.config)
                self.app.config['duration']+=1
                self.assertEqual(self.app.game.config,before)
        manifest=json.loads((self.root/'data/ai/manifest.json').read_text(encoding='utf-8'))
        for name,digest in manifest['sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)

    def test_developer_hotkeys_are_menu_only_and_lab_can_list_bundled_models(self):
        event=lambda key:pygame.event.Event(pygame.KEYDOWN,key=key,mod=pygame.KMOD_CTRL)
        self.app.handle(event(pygame.K_F8))
        self.assertEqual(self.app.scene,'battle');self.assertIsNone(self.app.lab_mode)
        game=self.app.game
        self.app.handle(event(pygame.K_F9))
        self.assertIs(self.app.game,game);self.assertEqual(self.app.scene,'battle')
        self.app.set_scene('menu');self.app.handle(event(pygame.K_F9))
        self.assertEqual(self.app.scene,'lab')
        self.app.lab_menu.profiles(0)
        self.assertTrue(any(path.name=='loose_1.json' for label,path in self.app.lab_menu.entries))
        self.app.lab_menu.profiles(1)
        self.assertTrue(any(path.name=='tight_0.json' for label,path in self.app.lab_menu.entries))

    def test_computer_turn_blocks_manual_actions_hides_hand_and_obeys_human_blackout(self):
        self.app.start_pve(1);mode=self.app.lab_mode;game=self.app.game
        self.assertTrue(mode.is_bot_turn())
        revision=game.revision;self.app.command('to_cards')
        self.assertEqual(game.revision,revision)
        mode.tick();self.assertGreater(game.revision,revision)
        self.assertIsNone(self.app.selected)
        mode.next_action=10**15
        with patch.object(self.app,'draw_hand') as hand:self.app.render();hand.assert_not_called()
        game.apply_effect(dict(kind='preview',amount=50,target='self'))
        game.apply_effect(dict(kind='blackout',duration=5,target='opponent'))
        self.assertEqual(self.app.view_player(),1)
        texts=[]
        with patch.object(self.app,'text',side_effect=lambda text,*args,**kwargs:texts.append(str(text))):self.app.render()
        self.assertTrue(any('關燈中' in t for t in texts))
        observation=observe(game)
        self.assertNotIn('opponent_hand',observation);self.assertNotIn('draw_pile',observation)
        self.assertFalse(observation['blind'])  # 電腦只受自己的效果影響。

    def test_achievements_only_credit_human_and_pve_toasts_are_enabled(self):
        self.app.start_pve(0);achievements=self.app.game.achievements
        for _ in range(3):achievements.consume(dict(type='card_played',player=1,card_id='ripple',timestamp='ai'))
        self.assertNotIn('triple_card',achievements.unlocked)
        for _ in range(3):achievements.consume(dict(type='card_played',player=0,card_id='ripple',timestamp='human'))
        self.assertIn('triple_card',achievements.unlocked)
        self.assertTrue((self.root/'saves/achievements.json').exists())
        with patch.object(self.app,'notify') as notify:
            self.app.events();notify.assert_called_once()
        self.assertFalse(achievements.new)

    def test_complete_both_roles_replay_every_command_and_restart_as_pve(self):
        self.app.config.update(duration=18,seed=41)
        # 此流程測試固定總長，避免牌堆循環延時讓測試場數不確定。
        for card in self.app.catalog.values():
            if any(e['kind']=='duration' for e in card['effects']):card['copies']=0
        for role in (0,1):
            with self.subTest(role=role):
                self.app.start_pve(role);mode=self.app.lab_mode;self.app.camera_duration=0
                human=Policy(profile(role,'heuristic'),123)
                for _ in range(600):
                    self.now+=1000
                    if self.app.game.phase=='ended':break
                    if mode.is_bot_turn():mode.tick()
                    else:
                        o=observe(self.app.game);action,uid=human.choose(o)
                        self.app.selected=uid;self.app.command(action)
                    self.assertFalse(mode.message,mode.message)
                self.assertEqual(self.app.game.phase,'ended')
                self.assertTrue(mode.saved)
                path=self.root/'saves/replays'/f'{self.app.game.id}.json'
                replay=Replay(path)
                self.assertEqual(replay.data['metadata']['mode'],'pve')
                while replay.step():pass
                self.assertEqual(state_digest(replay.game),state_digest(self.app.game))
                old_id=self.app.game.id;self.app.restart_match()
                self.assertEqual(self.app.lab_mode.kind,'pve')
                self.assertEqual(self.app.lab_mode.human_role,role)
                self.assertNotEqual(self.app.game.id,old_id)

    def test_leaving_saves_partial_game_and_debug_menu_can_find_it(self):
        self.app.start_pve(0);game=self.app.game
        self.app.set_scene('menu')
        path=self.root/'saves/replays'/f'{game.id}.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['metadata']['result']['reason'],'interrupted')
        self.app.lab_menu.replays()
        self.assertIn(path,[p for label,p in self.app.lab_menu.entries])

    def test_missing_model_reports_error_on_role_page(self):
        (self.root/'data/ai/loose_1.json').unlink()
        self.app.start_pve(0)
        self.assertEqual(self.app.scene,'singleplayer');self.assertIsNone(self.app.lab_mode)
        self.assertTrue(self.app.message.startswith('無法開始單人模式'))
