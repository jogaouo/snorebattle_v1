"""固定劇本清單教學：六關流程、測驗、圖卡、進度與正式存檔隔離。"""
from copy import deepcopy
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
os.environ['SDL_VIDEODRIVER']='dummy';os.environ['SDL_AUDIODRIVER']='dummy';os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import pygame
from snorebattle.app import App
from snorebattle.replay import state_digest
from snorebattle.tutorial import build_game


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
        self.app=App(self.root);self.app.start_tutorial()

    def tearDown(self):
        self.desktop.stop();self.time.stop();pygame.quit();self.temp.cleanup()

    def click(self,x,y):
        self.app.render();v=self.app.viewport
        pos=(round(v.x+x*v.width/1280),round(v.y+y*v.height/840))
        self.app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=pos))

    def drive(self,until=None):
        tutorial=self.app.tutorial
        for _ in range(300):
            self.now+=1400;self.app.render()
            self.assertFalse(tutorial.error,tutorial.error)
            step=tutorial.current
            if ((until and until(step)) or step['kind']=='finish') and tutorial.ready():return
            if step['kind'] in ('info','observe'):tutorial.acknowledge()
            elif step['kind']=='select':
                uid=tutorial.card_uid(step['card'])
                index=next(i for i,c in enumerate(self.app.game.players[tutorial.role].hand) if c.uid==uid)
                self.app.select_hand(uid,index)
                if tutorial.current.get('confirm_on_play'):self.app.command('play')
            elif step['kind']=='command':self.app.command(step['action'])
        self.fail('教學劇本未能完成')

    def assert_isolated(self):
        self.assertEqual(self.settings.read_bytes(),self.settings_before)
        self.assertEqual(self.achievements.read_bytes(),self.achievements_before)
        self.assertFalse((self.root/'saves/logs').exists())
        if self.app.game:self.assertIsNone(self.app.game.save_dir)
        self.assertEqual(self.app.config['amplitude'],50)
        self.assertEqual(self.app.config['duration'],37)
        self.assertEqual(self.app.catalog['ripple']['copies'],0)

    def test_all_six_lessons_follow_formal_rules_and_complete_to_their_list(self):
        tutorial=self.app.tutorial
        self.assertEqual(len(tutorial.lessons),6)
        for id in tutorial.lessons:
            with self.subTest(lesson=id):
                tutorial.start_lesson(id);self.drive()
                g=self.app.game
                if id=='snorer':
                    self.assertEqual(g.players[0].score,20);self.assertLess(g.y,-50)
                elif id=='slapper':
                    slaps=[e for e in g.events if e['type']=='slapped']
                    self.assertEqual(len(slaps),2);self.assertGreater(slaps[0]['points'],slaps[1]['points'])
                elif id=='cards_advantage':
                    self.assertEqual(g.stat('hand_limit',0),4);self.assertEqual(g.stat('preview',0),3)
                elif id=='cards_time':
                    self.assertEqual(g.stat('interval',0),1);self.assertEqual(g.stat('duration'),15)
                elif id=='cards_special':self.assertEqual(g.stat('blackout',1),0)
                self.assertNotIn(id,tutorial.completed)
                tutorial.complete()
                self.assertIsNone(self.app.game);self.assertIsNone(self.app.lab_mode)
                self.assertEqual(self.app.scene,'tutorial')
                self.assertEqual(tutorial.page,'cards' if id.startswith('cards_') else 'home')
                self.assertIn(id,tutorial.completed)
                self.assert_isolated()
        saved=json.loads((self.root/'saves/preferences.json').read_text(encoding='utf-8'))
        self.assertEqual(len(saved['tutorial_completed']),6);self.assertEqual(saved['sfx_volume'],.25)
        reloaded=App(self.root);reloaded.start_tutorial()
        self.assertEqual(reloaded.tutorial.completed,set(tutorial.lessons))

    def test_quiz_wrong_selection_changes_only_preview_and_never_runs_wrong_card(self):
        for id in ('snorer','slapper'):
            with self.subTest(lesson=id):
                t=self.app.tutorial;t.start_lesson(id)
                self.drive(lambda step:step['kind']=='select' and step.get('quiz'))
                index=t.step_index;g=self.app.game;before=state_digest(g)
                future_x=g.x+2*g.stat('interval',t.role)
                valid=[]
                for card in g.players[t.role].hand:
                    height=(g.preview_wave(card.uid) or g.wave).value(future_x)
                    if (abs(height)>=g.config['amplitude'] if t.role==0 else height>0):valid.append(card.definition)
                self.assertEqual(valid,[t.current['card']])
                wrong=next(c for c in g.players[t.role].hand if c.definition!=t.current['card'])
                self.app.select_hand(wrong.uid,g.players[t.role].hand.index(wrong))
                self.assertEqual(t.step_index,index)
                if not t.current.get('confirm_on_play'):self.assertTrue(t.feedback)
                self.app.command('play')
                self.assertEqual(state_digest(g),before)
                self.assertEqual(t.current['kind'],'select')
                uid=t.card_uid(t.current['card'])
                self.app.select_hand(uid,next(i for i,c in enumerate(g.players[t.role].hand) if c.uid==uid))
                if t.current.get('confirm_on_play'):
                    self.assertEqual(t.current['kind'],'select')
                    self.app.command('play')
                    self.assertEqual(t.current['kind'],'auto')
                else:
                    self.assertEqual(t.current['kind'],'command');self.assertEqual(t.current['action'],'play')
                self.drive();self.assertEqual(t.current['kind'],'finish')

    def test_snorer_small_wave_keeps_threshold_and_quiz_waits_for_confirmation(self):
        t=self.app.tutorial;t.start_lesson('snorer');g=self.app.game
        self.assertEqual(g.config['amplitude'],50)
        self.assertAlmostEqual(g.wave.value(3),30)
        self.drive(lambda step:step.get('focus')=='next_landing')
        self.assertLess(abs(t.next_landing()[1]),50)
        self.drive(lambda step:step.get('confirm_on_play'))
        index=t.step_index;before=state_digest(g)
        for card in list(g.players[0].hand):
            self.app.select_hand(card.uid,g.players[0].hand.index(card))
            self.assertEqual(t.step_index,index)
            self.assertTrue(t.button_enabled('出牌並補滿'))
            if card.definition!=t.current['card']:
                self.app.command('play')
                self.assertIn('不對喔',t.feedback)
                self.assertEqual(state_digest(g),before)
        self.drive()
        self.assertEqual(t.current['kind'],'finish')

    def test_slapper_story_opening_explains_positive_height_and_two_chances(self):
        t=self.app.tutorial;t.start_lesson('slapper');g=self.app.game
        self.assertEqual(g.slaps_left,2)
        self.assertEqual(t.current['presentation'],'role_intro')
        t.acknowledge()
        self.assertTrue(t.hidden_opponent())
        with patch.object(self.app,'draw_hand') as hand:
            self.app.render();hand.assert_not_called()
        self.drive(lambda step:step.get('focus')=='slap_button')
        self.assertEqual(t.phase_banner['title'],'行動階段')
        self.assertTrue(g.eligible())
        before=state_digest(g)
        for focus in ('slap_button','landing','positive_landing','slap_chances'):
            if focus=='slap_chances':
                self.assertEqual(t.current['presentation'],'locate_chances')
                self.drive(lambda step:step.get('focus')=='slap_chances')
            self.assertEqual(t.current['focus'],focus)
            self.now+=800;self.app.render()
            self.app.command('slap')
            self.assertEqual(state_digest(g),before)
            t.acknowledge()
        self.assertIn('高度次方',t.format_text(t.current['hint']))
        self.drive(lambda step:step['kind']=='info')
        self.assertEqual(state_digest(g),before)
        self.assertIn('兩次',t.current['emphasis'])
        self.drive()
        self.assertEqual(g.slaps_left,0)

    def test_slapper_lit_button_and_chance_location_hold(self):
        t=self.app.tutorial;t.start_lesson('slapper')
        self.assertEqual(self.app.game.config['slap_base'],1.04)
        self.drive(lambda step:step.get('focus')=='slap_button')
        colors=[]
        original=self.app.panel
        def panel(rect,color=None,*args,**kwargs):
            if pygame.Rect(rect)==pygame.Rect(45,475,225,46):colors.append(color)
            return original(rect,*args,**kwargs) if color is None else original(rect,color,*args,**kwargs)
        with patch.object(self.app,'panel',side_effect=panel),patch.object(self.app,'mouse',return_value=(-100,-100)):
            self.app.render()
        self.assertIn((48,100,108),colors)
        self.assertFalse(any(rect==pygame.Rect(45,475,225,46) for rect,fn in self.app.buttons))
        self.drive(lambda step:step.get('presentation')=='locate_chances')
        started=t.focus_started;self.now=started+4999;self.app.render()
        self.assertEqual(t.current['presentation'],'locate_chances')
        self.now=started+5000;self.app.render()
        self.assertEqual(t.current['focus'],'slap_chances')

    def test_slap_waits_before_story_and_current_lessons_use_text(self):
        t=self.app.tutorial
        for lesson in t.lessons.values():
            for step in lesson['steps']:
                if step['kind']=='info':
                    if step.get('title')=='打巴掌前，先記住這幾件事':
                        self.assertEqual(step['presentation'],'image_card')
                        self.assertEqual(step['image'],'slap_scoring')
                    else:
                        self.assertEqual(step['presentation'],'story')
                        self.assertNotIn('image',step)
        t.start_lesson('slapper');self.drive(lambda step:step.get('action')=='slap')
        before=t.step_index;now=self.now;self.app.command('slap')
        self.assertEqual(t.step_index,before)
        self.assertEqual(self.app.game.active,0)
        self.assertFalse(t.ready())
        with patch.object(t,'draw_info_card') as story:
            self.app.render();story.assert_not_called()
            self.now=now+3499;self.app.render();story.assert_not_called()
        self.assertEqual(t.step_index,before)
        self.now=now+3500;self.app.render()
        self.assertEqual(t.current['title'],'打完巴掌之後')
        self.assertEqual(t.current['presentation'],'story')
        self.drive()
        self.assertEqual(t.current['kind'],'finish')

    def test_script_hands_draws_and_opponent_actions_are_deterministic(self):
        for id,lesson in self.app.tutorial.lessons.items():
            with self.subTest(lesson=id):
                a,b=build_game(self.app,lesson),build_game(self.app,lesson)
                self.assertEqual(state_digest(a),state_digest(b))
                for p in (0,1):
                    self.assertEqual([c.definition for c in a.players[p].hand],lesson['scenario']['hands'][str(p)])
                n=len(lesson['scenario']['draw_order'])
                self.assertEqual([c.definition for c in reversed(a.draw_pile[-n:])],lesson['scenario']['draw_order'])
                cards=a.draw_pile+a.discard+sum([p.hand for p in a.players],[])
                self.assertEqual(len(cards),a.card_count);self.assertEqual(len({c.uid for c in cards}),a.card_count)

    def test_list_click_modal_and_escape_return_without_marking_completed(self):
        self.click(1060,255)
        t=self.app.tutorial
        self.assertEqual(t.lesson['id'],'snorer');self.assertEqual(t.current['kind'],'observe')
        before=state_digest(self.app.game);self.app.command('to_cards')
        self.assertEqual(state_digest(self.app.game),before)
        self.drive(lambda step:step.get('focus')=='score_button')
        for _ in range(3):
            self.now+=800;self.click(1080,777)
        self.assertEqual(t.current['kind'],'info')
        self.click(640,665)
        self.assertEqual(t.current['kind'],'command')
        self.app.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE))
        self.assertEqual(self.app.scene,'tutorial');self.assertEqual(t.page,'home');self.assertFalse(t.completed)
        t.show_cards();t.start_lesson('cards_wave')
        self.app.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE))
        self.assertEqual(t.page,'cards');self.assertFalse(t.completed)
        self.app.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE));self.assertEqual(t.page,'home')
        self.app.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE));self.assertEqual(self.app.scene,'menu')
        self.assertIsNone(self.app.tutorial);self.assert_isolated()

    def test_snorer_opening_zooms_without_advancing_game_and_threshold_regions_pulse(self):
        t=self.app.tutorial;t.start_lesson('snorer')
        self.drive(lambda step:step.get('focus')=='score_button')
        before=state_digest(self.app.game)
        self.assertEqual(t.current['focus'],'score_button')
        self.now+=800
        with patch('pygame.transform.smoothscale',wraps=pygame.transform.smoothscale) as scale:
            self.app.render()
            self.assertTrue(any(call.args[1]==(560,217) for call in scale.call_args_list))
        t.acknowledge();self.assertEqual(t.current['focus'],'landing')
        self.now+=800
        with patch('pygame.transform.smoothscale',wraps=pygame.transform.smoothscale) as scale:
            self.app.render()
            self.assertTrue(any(call.args[1]==(1000,400) for call in scale.call_args_list))
        t.acknowledge();self.assertEqual(t.current['focus'],'thresholds')
        self.now+=800;self.app.render();first=self.app.canvas.get_at((1000,180))
        self.now+=350;self.app.render();second=self.app.canvas.get_at((1000,180))
        self.assertNotEqual(first,second)
        self.assertEqual(state_digest(self.app.game),before)
        self.assertFalse(self.app.game.eligible())
        t.acknowledge();self.assertEqual(t.current['kind'],'info')

    def test_role_intro_banner_and_original_button_location_precede_closeup(self):
        t=self.app.tutorial;t.start_lesson('snorer')
        initial=state_digest(self.app.game)
        self.assertEqual(t.current['presentation'],'role_intro')
        t.acknowledge();self.assertEqual(t.current['presentation'],'action_banner')
        self.now+=1000;self.app.render()
        self.assertEqual(t.current['presentation'],'action_banner')
        self.now+=1101;self.app.render()
        self.assertEqual(t.current['presentation'],'locate_score')
        self.now+=5000;self.app.render()
        self.assertEqual(t.current['presentation'],'locate_score')
        self.now+=501;self.app.render()
        self.assertEqual(t.current['focus'],'score_button')
        self.assertIn('行動階段',t.current['hint'])
        self.assertEqual(state_digest(self.app.game),initial)

    def test_snorer_repeated_phase_banners_and_hidden_opponent(self):
        t=self.app.tutorial;t.start_lesson('snorer')
        self.drive(lambda step:step.get('action')=='to_cards')
        self.app.command('to_cards')
        self.assertTrue(t.banner_active())
        self.assertEqual(t.phase_banner['title'],'出牌階段')
        self.assertFalse(t.ready())
        self.drive(lambda step:step['kind']=='auto')
        self.assertTrue(t.hidden_opponent())
        with patch.object(self.app,'draw_hand') as hand, patch.object(self.app,'draw_details') as details:
            self.app.render();hand.assert_not_called();details.assert_not_called()
        self.drive(lambda step:step['kind']=='info')
        self.assertFalse(t.hidden_opponent())
        self.assertEqual(t.phase_banner['title'],'行動階段')
        self.assertNotEqual((t.animation or {}).get('kind'),'card')

    def test_info_card_only_has_one_continue_button(self):
        t=self.app.tutorial;t.start_lesson('snorer')
        self.drive(lambda step:step['kind']=='info')
        self.app.render()
        self.assertEqual(len(self.app.buttons),1)
        self.assertEqual(self.app.buttons[0][0],pygame.Rect(510,642,260,46))
        before=t.step_index;self.click(640,665)
        self.assertEqual(t.step_index,before+1)

    def test_completed_badges_and_replay_keep_progress(self):
        t=self.app.tutorial;t.start_lesson('cards_wave');self.drive();t.complete()
        texts=[]
        with patch.object(self.app,'text',side_effect=lambda text,*args,**kwargs:texts.append(str(text))):self.app.render()
        self.assertIn('已完成',texts)
        t.page='home';texts.clear()
        with patch.object(self.app,'text',side_effect=lambda text,*args,**kwargs:texts.append(str(text))):self.app.render()
        self.assertIn('1/4 已完成',texts)
        t.start_lesson('cards_wave');self.drive();t.complete()
        self.assertEqual(self.app.preferences['tutorial_completed'],['cards_wave'])
        self.assert_isolated()

    def test_info_cards_can_be_inserted_in_json_and_use_optional_artwork(self):
        path=self.root/'data/tutorial/lessons.json';data=json.loads(path.read_text(encoding='utf-8'))
        data['lessons'][0]['steps'].insert(1,dict(kind='info',title='新增圖卡',body='可在劇本中插入說明。',emphasis='說明',image='custom'))
        path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        folder=self.root/'assets/tutorial';folder.mkdir(parents=True)
        art=pygame.Surface((300,100));art.fill((22,200,160));pygame.image.save(art,str(folder/'custom.png'))
        a=App(self.root);a.start_tutorial();t=a.tutorial;t.start_lesson('snorer')
        t.acknowledge();a.render()
        self.assertEqual(t.current['title'],'新增圖卡')
        self.assertEqual(tuple(a.canvas.get_at((640,320)))[:3],(22,200,160))
        self.assertEqual(a.game.revision,0)
        t.acknowledge();self.assertEqual(t.current['presentation'],'action_banner')

    def test_blackout_demo_shows_affected_view_then_expires_normally(self):
        t=self.app.tutorial;t.start_lesson('cards_special')
        self.drive(lambda step:step['kind']=='observe')
        self.assertEqual(self.app.game.active,1);self.assertTrue(self.app.game.stat('blackout',1))
        texts=[]
        with patch.object(self.app,'text',side_effect=lambda text,*args,**kwargs:texts.append(str(text))):self.app.render()
        self.assertTrue(any('關燈中' in text for text in texts))
        t.acknowledge();self.drive()
        self.assertEqual(self.app.game.stat('blackout',1),0)
        self.assert_isolated()

    def test_lesson_completion_and_exit_never_start_pve(self):
        t=self.app.tutorial;t.start_lesson('snorer');self.drive();t.complete()
        self.assertEqual(self.app.scene,'tutorial');self.assertEqual(t.page,'home')
        self.assertIsNone(self.app.game);self.assertIsNone(self.app.lab_mode)
        t.back()
        self.assertEqual(self.app.scene,'menu');self.assertIsNone(self.app.tutorial)
        self.assert_isolated()

    def test_tutorial_lists_have_no_singleplayer_shortcut(self):
        labels=[];original=self.app.button
        def capture(label,*args,**kwargs):labels.append(label);return original(label,*args,**kwargs)
        for page in ('home','cards'):
            self.app.tutorial.page=page
            with patch.object(self.app,'button',side_effect=capture):self.app.render()
        self.assertFalse(any('單人' in label for label in labels),labels)
        self.app.tutorial.back();self.app.tutorial.back()
        self.assertEqual(self.app.scene,'menu')
        self.app.preferences['tutorial_done']=False
        self.app.request_start_game();self.app.request_pve(1)
        self.assertEqual(self.app.scene,'battle')
        self.assertEqual(self.app.lab_mode.kind,'pve')
        self.assertIsNone(self.app.tutorial)

    def test_tutorial_achievement_toasts_stay_silent(self):
        self.app.tutorial.start_lesson('snorer')
        self.app.game.achievements.new=['測試成就']
        with patch.object(self.app,'notify') as notify:self.app.events();notify.assert_not_called()
        self.assertFalse(self.app.game.achievements.new);self.assert_isolated()
