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
    from snorebattle.core import Game,Tool
except ModuleNotFoundError:
    pygame=None

@unittest.skipIf(pygame is None,'未安裝 Pygame，略過圖像測試')
class UITests(unittest.TestCase):
    def setUp(self):
        self.app=App(ROOT)
        self.app.catalog['tool']['copies']=2
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


    def test_hud_and_on_screen_log_do_not_reveal_height(self):
        app=self.app
        texts=[]
        with patch.object(app,'text',side_effect=lambda text,*args,**kwargs:texts.append(str(text))):
            app.render()
            hud=next(text for text in texts if text.startswith('x = '))
            self.assertNotIn('高度',hud)
            self.assertNotIn('y=',hud)
            texts.clear()
            app.log_open=True
            app.render()
            self.assertFalse(any('y=' in text for text in texts))
        self.assertTrue(any('y' in event for event in app.game.events))


    def equip_tool(self):
        g=self.app.game
        for zone in [g.draw_pile,g.discard]+[p.hand for p in g.players]:
            card=next((c for c in zone if c.definition=='tool'),None)
            if card:
                zone.remove(card)
                g.players[0].tool=Tool(card,0,2)
                return
        self.fail('缺少道具測試牌')

    def test_equipped_tool_inspection_does_not_activate(self):
        app=self.app; g=app.game
        self.equip_tool()
        before=(g.revision,len(g.events),g.y,g.players[0].tool.remaining)
        app.render()
        app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(400,790)))
        self.assertTrue(app.inspect_tool)
        self.assertIsNone(app.selected)
        self.assertEqual(app.selected_details()[0]['id'],'tool')
        self.assertEqual((g.revision,len(g.events),g.y,g.players[0].tool.remaining),before)
        app.render()
        # 裝備欄可再次點擊取消或重新查看。
        app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(400,790)))
        self.assertFalse(app.inspect_tool)
        app.render()
        app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(400,790)))
        self.assertTrue(app.inspect_tool)
        app.command('use_tool')
        self.assertTrue(app.inspect_tool)
        self.assertIn('剩餘 1 次',app.selected_details()[1])
        self.assertIn('本回合已使用',app.selected_details()[1])
        app.command('discard_tool')
        self.assertIsNone(app.selected_details())

    def test_hand_details_and_tool_selection_are_exclusive(self):
        app=self.app; g=app.game
        self.equip_tool()
        card=next(c for c in g.draw_pile+g.players[0].hand if c.definition=='ripple')
        if card in g.draw_pile:
            g.draw_pile.remove(card); g.players[0].hand.append(card)
        app.select(card.uid)
        self.assertEqual(app.selected_details()[0]['id'],'ripple')
        self.assertIsNotNone(app.selected_wave_preview())
        app.select_tool()
        self.assertIsNone(app.selected)
        self.assertIsNone(app.selected_wave_preview())
        app.select(card.uid)
        self.assertFalse(app.inspect_tool)
        self.assertEqual(app.selected_details()[0]['description'],g.catalog['ripple']['description'])

    def test_long_details_scroll_without_moving_hand(self):
        app=self.app; g=app.game
        card=g.players[0].hand[0]
        g.catalog[card.definition]['description']='很長的測試敘述。'*50
        app.select(card.uid)
        app.render()
        with patch.object(app,'mouse',return_value=(950,700)):
            app.handle(pygame.event.Event(pygame.MOUSEWHEEL,y=-2,x=0))
        app.render()
        self.assertEqual(app.detail_scroll,2)
        self.assertEqual(app.hand_offset,0)
        app.select(card.uid)
        self.assertEqual(app.detail_scroll,0)


    def test_extra_hand_card_peeks_and_can_be_revealed(self):
        from snorebattle.app import PANEL,BG
        app=self.app; g=app.game
        g.draw(0,6-len(g.players[0].hand))
        fifth=g.players[0].hand[4]
        app.render()
        self.assertEqual(tuple(app.canvas.get_at((800,600)))[:3],PANEL)
        app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(800,650)))
        self.assertEqual(app.selected,fifth.uid)
        self.assertEqual(app.hand_offset,1)
        app.hand_offset=len(g.players[0].hand)-4
        app.render()
        self.assertEqual(tuple(app.canvas.get_at((800,600)))[:3],BG)
        self.assertTrue(all(rect.right<=815 for rect,fn in app.buttons if rect.top==576))


    def test_hand_peeks_both_sides_and_left_click_reveals(self):
        from snorebattle.app import PANEL,BG
        app=self.app; g=app.game
        g.draw(0,8-len(g.players[0].hand))
        app.render()
        self.assertEqual(tuple(app.canvas.get_at((215,600)))[:3],BG)
        self.assertEqual(tuple(app.canvas.get_at((800,600)))[:3],PANEL)
        app.hand_offset=2; app.render()
        self.assertEqual(tuple(app.canvas.get_at((215,600)))[:3],PANEL)
        self.assertEqual(tuple(app.canvas.get_at((800,600)))[:3],PANEL)
        previous=g.players[0].hand[1]
        app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(215,650)))
        self.assertEqual(app.selected,previous.uid)
        self.assertEqual(app.hand_offset,1)
        app.hand_offset=len(g.players[0].hand)-4; app.render()
        self.assertEqual(tuple(app.canvas.get_at((215,600)))[:3],PANEL)
        self.assertEqual(tuple(app.canvas.get_at((800,600)))[:3],BG)
        self.assertTrue(all(rect.left>=205 and rect.right<=815
                            for rect,fn in app.buttons if rect.top==576))


    def test_slap_base_setting_steps_by_point01_and_shows_threshold_score(self):
        app=self.app; app.scene='settings'
        app.config['slap_base']=1.05; app.config['amplitude']=50
        texts=[]
        with patch.object(app,'text',side_effect=lambda text,*args,**kwargs:texts.append(str(text))):
            app.render()
        self.assertIn('正閾值 +50：巴掌 12 分',texts)
        app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(1070,266)))
        self.assertEqual(app.config['slap_base'],1.06)
        app.config['slap_base']=1.1; texts.clear()
        with patch.object(app,'text',side_effect=lambda text,*args,**kwargs:texts.append(str(text))):
            app.render()
        self.assertIn('正閾值 +50：巴掌 118 分',texts)


    def test_height_label_is_near_marker_and_hidden_by_blackout(self):
        app=self.app
        labels=[]
        with patch.object(app,'text',side_effect=lambda text,*args,**kwargs:labels.append((str(text),args))):
            app.render()
        matches=[args for text,args in labels if text=='+0.0']
        self.assertEqual(len(matches),1)
        self.assertLess(matches[0][0]+app.assets.font(17).size('+0.0')[0],640)
        self.assertGreaterEqual(matches[0][1],149)
        self.assertLess(matches[0][1],389)
        app.game.apply_effect(dict(kind='blackout',duration=5,target='self'))
        labels.clear()
        with patch.object(app,'text',side_effect=lambda text,*args,**kwargs:labels.append((str(text),args))):
            app.render()
        self.assertFalse(any(text=='+0.0' for text,args in labels))

if __name__=='__main__': unittest.main()


