import unittest
from pathlib import Path
from snorebattle.core import Game,Command,RuleError,Tool,load_data
from snorebattle.effects import Effect
from snorebattle.wave import Wave
from snorebattle.achievements import Achievements

ROOT=Path(__file__).resolve().parents[1]

class CoreTests(unittest.TestCase):
    def game(self,**overrides):
        config,catalog=load_data(ROOT)
        config.update(overrides)
        return Game(config,catalog,seed=42)

    def do(self,g,action,uid=None):
        g.dispatch(Command(g.active,action,uid,g.revision))

    def give(self,g,key):
        for zone in [g.draw_pile,g.discard]+[p.hand for p in g.players]:
            for card in zone:
                if card.definition==key:
                    zone.remove(card)
                    g.players[g.active].hand.append(card)
                    return card
        self.fail('沒有測試卡牌 '+key)

    def assert_conservation(self,g):
        cards=g.draw_pile+g.discard+[c for p in g.players for c in p.hand]
        cards += [p.tool.card for p in g.players if p.tool]
        self.assertEqual(len(cards),g.card_count)
        self.assertEqual(len(set(c.uid for c in cards)),g.card_count)

    def skip_turn(self,g):
        self.do(g,'to_cards'); self.do(g,'skip')

    def test_opening_and_automatic_turn(self):
        g=self.game()
        self.assertEqual((g.active,g.x,g.y,g.phase),(0,0,0,'action'))
        self.skip_turn(g)
        self.assertEqual((g.active,g.x,g.phase,g.turn),(1,1.5,'action',2))
        self.skip_turn(g)
        self.assertEqual((g.active,g.x,g.phase,g.turn),(0,3,'action',3))

    def test_invalid_command_does_not_mutate(self):
        g=self.game(); count=len(g.events)
        with self.assertRaises(RuleError): self.do(g,'slap')
        with self.assertRaises(RuleError): self.do(g,'land')
        with self.assertRaises(RuleError): g.dispatch(Command(1,'to_cards'))
        with self.assertRaises(RuleError): g.dispatch(Command(0,'to_cards',expected_revision=999))
        self.assertEqual(len(g.events),count)
        self.assertEqual(g.revision,0)

    def test_play_refills_and_automatically_lands(self):
        g=self.game(); card=self.give(g,'ripple'); p=g.players[0]
        g.discard.extend(c for c in p.hand if c.uid!=card.uid); p.hand=[card]
        self.do(g,'to_cards'); self.do(g,'play',card.uid)
        self.assertEqual(len(p.hand),3)
        self.assertEqual((g.active,g.phase,g.x),(1,'action',1.5))
        self.assert_conservation(g)

    def test_over_limit_draw_and_exchange(self):
        g=self.game(); g.y=50
        self.do(g,'bonus_draw'); self.assertEqual(len(g.players[0].hand),4)
        self.do(g,'to_cards'); self.do(g,'discard',g.players[0].hand[0].uid)
        self.assertEqual(len(g.players[0].hand),4)
        self.assertEqual((g.active,g.phase),(1,'action'))
        self.assert_conservation(g)

    def test_over_limit_play_does_not_refill(self):
        g=self.game(); card=self.give(g,'ripple'); g.draw(0,2)
        count=len(g.players[0].hand)
        self.do(g,'to_cards'); self.do(g,'play',card.uid)
        self.assertEqual(len(g.players[0].hand),count-1)

    def test_score_threshold_and_single_action(self):
        for y in (50,-50):
            g=self.game(); g.y=y
            self.do(g,'score')
            self.assertEqual(g.players[0].score,10)
            with self.assertRaises(RuleError): self.do(g,'bonus_draw')

    def test_fifo_after_fade_and_middle_expiration(self):
        add=Effect('sin_add',0,4,None,dict(amplitude=10,period=4))
        scale=Effect('scale',0,None,None,dict(factor=2))
        a=Wave(50,12); a.publish(0,[add,scale])
        b=Wave(50,12); b.publish(0,[scale,add])
        self.assertAlmostEqual(a.value(1)-b.value(1),10)
        self.assertAlmostEqual(a.value(5),2*Wave(50,12).value(5))

    def test_fade_in_and_out_are_continuous(self):
        wave=Wave(50,12)
        scale=Effect('scale',2,6,None,dict(factor=2))
        wave.publish(2,[scale])
        base=Wave(50,12)
        for x in (2,2+1e-6,6-1e-6,6,6+1e-6):
            self.assertAlmostEqual(wave.value(x),base.value(x),places=7)
        self.assertAlmostEqual(wave.value(2.5),base.value(2.5)*1.5)
        self.assertAlmostEqual(wave.value(5.5),base.value(5.5)*1.5)
        self.assertAlmostEqual(wave.value(3),base.value(3)*2)

    def test_reset_fades_and_preserves_history(self):
        wave=Wave(50,12); wave.publish(0,[Effect('scale',0,None,None,dict(factor=2))])
        history=wave.value(1)
        wave.publish(2,[])
        self.assertAlmostEqual(wave.value(1),history)
        base=Wave(50,12)
        self.assertAlmostEqual(wave.value(2),base.value(2)*2)
        self.assertAlmostEqual(wave.value(2.5),base.value(2.5)*1.5)
        self.assertAlmostEqual(wave.value(3),base.value(3))

    def test_overlapping_and_same_position_transitions(self):
        wave=Wave(50,12)
        first=Effect('scale',0,None,None,dict(factor=2))
        second=Effect('scale',.25,None,None,dict(factor=-1))
        wave.publish(0,[first]); before=wave.value(.25)
        wave.publish(.25,[first,second]); wave.publish(.25,[first,second])
        self.assertAlmostEqual(wave.value(.25),before)
        self.assertAlmostEqual(wave.value(.25+1e-7),before,places=4)
        self.assertAlmostEqual(wave.value(1.25),-2*Wave(50,12).value(1.25))

    def test_base_parameter_fades_keep_threshold(self):
        for kind in ('base_amplitude','base_period'):
            g=self.game(); g.apply_effect(dict(kind=kind,factor=2)); g.wave.publish(0,g.effects)
            self.assertEqual(g.config['amplitude'],50)
            self.assertAlmostEqual(g.wave.value(1e-7),Wave(50,12).value(1e-7),places=7)

    def test_tool_waits_until_own_next_turn(self):
        g=self.game(); card=self.give(g,'tool')
        self.do(g,'to_cards'); self.do(g,'play',card.uid)
        self.assertFalse(g.tool_ready())
        self.skip_turn(g)
        self.assertTrue(g.tool_ready())
        g.y=80; self.do(g,'score'); self.do(g,'use_tool')
        self.assertEqual(g.y,40)
        self.assertEqual(g.players[0].tool.remaining,1)
        with self.assertRaises(RuleError): self.do(g,'use_tool')

    def test_slap_clears_and_automatically_advances_from_current_time(self):
        g=self.game(); card=self.give(g,'tool'); g.players[0].hand.remove(card)
        g.players[0].tool=Tool(card,0,2)
        g.x=9; g.active=1; g.phase='action'; g.y=100
        for spec in [dict(kind='interval',amount=2),dict(kind='hand_limit',amount=2,target='self'),
                     dict(kind='scale',factor=2),dict(kind='duration',amount=6)]:
            g.apply_effect(spec)
        g.wave.publish(g.x,g.effects)
        self.do(g,'slap')
        self.assertEqual((g.active,g.phase,g.x,g.slaps_left),(0,'action',10.5,2))
        self.assertFalse(g.effects); self.assertIsNone(g.players[0].tool)
        self.assertIn(card,g.discard)
        self.assertEqual(g.stat('interval',0),1.5)
        self.assertEqual(g.players[1].score,20)
        self.assert_conservation(g)

    def test_empty_draw_and_recycling(self):
        g=self.game(); g.players[0].hand.extend(g.draw_pile); g.draw_pile=[]
        self.assertEqual(g.draw(1,1),0)
        card=g.players[0].hand.pop(); g.discard.append(card)
        self.assertEqual(g.draw(1,1),1)
        self.assertEqual(g.players[1].hand[-1].uid,card.uid)
        self.assert_conservation(g)

    def test_end_only_when_exceeding(self):
        g=self.game(duration=3)
        for x in (0,1.5,3):
            self.assertEqual((g.x,g.phase),(x,'action'))
            self.skip_turn(g)
        self.assertEqual(g.phase,'ended')
        end=next(e for e in g.events if e['type']=='game_ended')
        self.assertIsNone(end['winner'])

    def test_achievements_per_player_streak(self):
        a=Achievements()
        for player in (0,1,0,0):
            a.consume(dict(type='card_played',player=player,card_id='ripple',timestamp='test'))
        self.assertIn('triple_card',a.unlocked)
        b=Achievements()
        for kind in ('card_played','card_played','card_skipped','card_played'):
            b.consume(dict(type=kind,player=0,card_id='ripple',timestamp='test'))
        self.assertNotIn('triple_card',b.unlocked)

    def test_complete_games_and_card_conservation(self):
        for seed in range(12):
            config,catalog=load_data(ROOT); g=Game(config,catalog,seed=seed)
            for _ in range(1600):
                if g.phase=='ended': break
                self.assertIn(g.phase,('action','cards'))
                if g.phase=='action':
                    if g.tool_ready(): self.do(g,'use_tool')
                    if g.eligible(): self.do(g,'score' if g.active==0 else 'slap')
                    # 巴掌已自動開始下一人的回合，不混用其角色行動。
                    if g.phase=='action': self.do(g,'to_cards')
                elif g.phase=='cards':
                    p=g.players[g.active]
                    choices=[c for c in p.hand if 'tool' not in g.catalog[c.definition] or not p.tool]
                    if choices: self.do(g,'play',g.rng.choice(choices).uid)
                    else: self.do(g,'skip')
                self.assert_conservation(g)
            self.assertEqual(g.phase,'ended',f'seed={seed}')


    def test_wave_preview_matches_real_play_without_side_effects(self):
        from copy import deepcopy
        for key in ('ripple','swell','quiet','amplitude','period','invert'):
            g=self.game()
            g.apply_effect(dict(kind='sin_add',amplitude=15,period=3,duration=9))
            g.wave.publish(0,g.effects)
            card=self.give(g,key)
            before=deepcopy((g.players,g.draw_pile,g.discard,g.effects,g.wave.versions,
                             g.events,g.rng.getstate(),g.revision,g.phase,g.x,g.y))
            preview=g.preview_wave(card.uid)
            self.assertIsNotNone(preview)
            after=(g.players,g.draw_pile,g.discard,g.effects,g.wave.versions,
                   g.events,g.rng.getstate(),g.revision,g.phase,g.x,g.y)
            self.assertEqual(before,after,key)
            self.do(g,'to_cards')
            preview_cards=g.preview_wave(card.uid)
            samples=[0,.1,.5,1,2,4,8.5,9,12]
            self.do(g,'play',card.uid)
            for x in samples:
                self.assertAlmostEqual(preview.value(x),g.wave.value(x),msg=f'{key} x={x}')
                self.assertAlmostEqual(preview_cards.value(x),g.wave.value(x))

    def test_preview_rejects_nonwave_and_other_players_cards(self):
        g=self.game()
        card=self.give(g,'pocket')
        self.assertIsNone(g.preview_wave(card.uid))
        self.assertIsNone(g.preview_wave(None))
        self.assertIsNone(g.preview_wave(-1))
        opponent_card=g.players[1].hand[0]
        self.assertIsNone(g.preview_wave(opponent_card.uid))

    def test_preview_preserves_past_and_follows_new_location(self):
        g=self.game(); card=self.give(g,'invert')
        first=g.preview_wave(card.uid)
        g.x=2
        next_preview=g.preview_wave(card.uid)
        self.assertAlmostEqual(next_preview.value(1),g.wave.value(1))
        self.assertNotAlmostEqual(first.value(1),next_preview.value(1))

if __name__=='__main__': unittest.main()
