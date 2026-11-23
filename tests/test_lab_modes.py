import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BOT=ROOT.parent/'snorebot'
sys.path[:0]=[str(ROOT),str(ROOT/'.vendor'),str(BOT)]
os.environ['SDL_VIDEODRIVER']='dummy';os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import pygame
from snorebattle.app import App
from snorebattle.lab_modes import start_bot,start_replay,install_game
from snorebattle.replay import state_digest,Recorder
from snorebattle.core import Game,Command
from botlab.policy import profile
from botlab.runner import play

class LabModeTests(unittest.TestCase):
    def tearDown(self):pygame.quit()
    def test_replay_controls_forward_back_and_no_manual_game_actions(self):
        app=App(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'replay.json'
            play(app.config,app.catalog,[profile(0),profile(1)],8,max_commands=10,replay_path=path)
            start_replay(app,path)
            self.assertIsNone(app.game.save_dir)
            initial=state_digest(app.game)
            app.command('to_cards');self.assertEqual(state_digest(app.game),initial)
            app.lab_mode.move();self.assertEqual(app.lab_mode.replay.cursor,1)
            app.lab_mode.move(-1);self.assertEqual(state_digest(app.game),initial)
            app.render()
    def test_bot_uses_original_gui_and_does_not_write_formal_achievements(self):
        app=App(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            import json
            path=Path(temp)/'profile.json';path.write_text(json.dumps(profile(0)),encoding='utf-8')
            start_bot(app,path,1)
            self.assertIsNone(app.game.save_dir)
            before=app.game.revision
            app.command('to_cards');self.assertEqual(app.game.revision,before)
            app.lab_mode.tick();self.assertGreater(app.game.revision,before)
            app.render()


    def test_lab_achievement_toasts_silent_but_normal_toasts_remain(self):
        app=App(ROOT);app.game=Game(app.config,app.catalog,seed=1)
        for kind in ('replay','bot',None):
            app.lab_mode=SimpleNamespace(kind=kind) if kind else None
            app.game.achievements.new=['測試成就']
            with patch.object(app,'notify') as notify:
                app.events()
                if kind:notify.assert_not_called()
                else:notify.assert_called_once_with('成就解鎖：測試成就')
            self.assertEqual(app.game.achievements.new,[])

    def test_replay_card_preselection_is_visible_pure_and_delayed(self):
        app=App(ROOT)
        config=dict(app.config);config.update(initial_hand=8,hand_limit=8)
        g=Game(config,app.catalog,seed=8);recorder=Recorder(g)
        cmd=Command(0,'to_cards');g.dispatch(cmd);recorder.append(g,cmd)
        card=g.players[0].hand[-1];name=g.catalog[card.definition]['name']
        cmd=Command(0,'play',card.uid);g.dispatch(cmd);recorder.append(g,cmd)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'preview.json';recorder.save(path,g)
            app.notify('成就解鎖：舊提示')
            start_replay(app,path);self.assertEqual(app.message,'')
            mode=app.lab_mode
            with patch('pygame.time.get_ticks',return_value=1000):
                mode.move()
                self.assertEqual(mode.replay.cursor,1)
                before=state_digest(app.game)
                self.assertEqual(app.selected,card.uid)
                self.assertEqual(mode.upcoming_uid,card.uid)
                self.assertIn(name,mode.upcoming_label)
                self.assertEqual(app.hand_offset,4)
                mode.prepare_upcoming()
                self.assertEqual(state_digest(app.game),before)
                self.assertEqual(app.selected_details()[0]['name'],name)
                app.render()
                mode.playing=True;deadline=mode.next_action
            with patch('pygame.time.get_ticks',return_value=deadline-1):
                mode.tick();self.assertEqual(mode.replay.cursor,1)
            with patch('pygame.time.get_ticks',return_value=deadline):
                mode.tick();self.assertEqual(mode.replay.cursor,2)
                self.assertIn(name,mode.last_card_label())
                self.assertEqual(state_digest(app.game),recorder.data['final']['digest'])

    def test_human_bot_mode_never_has_replay_preselection(self):
        import json
        app=App(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'profile.json'
            data=profile(0);data['weights']['explore']=0
            path.write_text(json.dumps(data),encoding='utf-8')
            start_bot(app,path,1)
            for _ in range(2):
                app.lab_mode.next_action=0
                app.lab_mode.tick()
                self.assertIsNone(app.selected)
            self.assertIsNone(getattr(app.lab_mode,'upcoming_uid',None))
            self.assertFalse(app.inspect_tool)

if __name__=='__main__':unittest.main()
