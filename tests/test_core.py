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
        self.assertEqual(len(g.players[0].hand),5)
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
            self.assertEqual(g.players[0].score,11)
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
        self.assertEqual(g.y,30)
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
        self.assertEqual(g.players[1].score,132)
        self.assert_conservation(g)

    def test_empty_draw_and_recycling(self):
        g=self.game(); g.players[0].hand.extend(g.draw_pile); g.draw_pile=[]
        self.assertEqual(g.draw(1,1),0)
        card=g.players[0].hand.pop(); g.discard.append(card)
        self.assertEqual(g.draw(1,1),1)
        self.assertEqual(g.players[1].hand[-1].uid,card.uid)
        self.assert_conservation(g)

    def test_end_only_when_exceeding(self):
        g=self.game(duration=3,snore_turn_score=0)
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
        for key in ('ripple','ripple_reverse','swell','quiet','amplitude','period','invert'):
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


    def test_duration_cards_survive_slap_and_still_stack(self):
        for key,delta in (('long',6),('short',-6)):
            g=self.game(); card=self.give(g,key)
            self.do(g,'to_cards'); self.do(g,'play',card.uid)
            self.assertEqual(g.stat('duration'),45+delta)
            self.assertFalse(next(e for e in g.effects if e.kind=='duration').clear_on_slap)
            self.do(g,'slap')
            self.assertEqual(g.stat('duration'),45+delta)
            self.assertEqual((g.active,g.phase,g.x),(0,'action',3))
            self.assertEqual(len(g.effects),1)
            self.assertEqual([e for e in g.events if e['type']=='landed'][-1]['player'],0)
            event=next(e for e in g.events if e['type']=='effects_cleared')
            self.assertEqual(len(event['retained']),1)
        g=self.game()
        for key in ('long','long','short'):
            g.apply_effect(g.catalog[key]['effects'][0])
        self.assertEqual(g.stat('duration'),51)
        g.active=1; g.y=50; self.do(g,'slap')
        self.assertEqual(g.stat('duration'),51)

    def test_permanent_invert_twice_then_slap_resets(self):
        g=self.game()
        spec=g.catalog['invert']['effects'][0]
        self.assertNotIn('duration',spec)
        g.apply_effect(spec); g.wave.publish(g.x,g.effects)
        self.assertIsNone(g.effects[-1].end)
        base=Wave(g.config['amplitude'],g.config['period'])
        self.assertAlmostEqual(g.wave.value(15),-base.value(15))
        g.x=2
        g.apply_effect(spec); g.wave.publish(g.x,g.effects)
        self.assertAlmostEqual(g.wave.value(15),base.value(15))
        g.active=1; g.y=50
        self.do(g,'slap')
        self.assertFalse(g.effects)
        self.assertAlmostEqual(g.wave.value(15),base.value(15))


    def test_interval_floor_half_and_persists_through_slap(self):
        g=self.game()
        for _ in range(12):
            g.apply_effect(g.catalog['fast']['effects'][0])
        self.assertEqual(g.stat('interval',0),.5)
        self.assertEqual(g.stat('interval',1),.5)
        self.skip_turn(g)
        self.assertEqual(g.x,.5)
        self.assertGreater(g.y,0)
        self.do(g,'slap')
        self.assertEqual(g.stat('interval',0),.5)
        self.assertEqual(g.x,1)


    def test_preview_and_hand_limit_buffs_survive_slap_for_both_players(self):
        g=self.game()
        for player in (0,1):
            g.active=player
            for _ in range(2):
                for key in ('forecast','pocket'):
                    g.apply_effect(g.catalog[key]['effects'][0])
        g.apply_effect(g.catalog['fast']['effects'][0])
        g.apply_effect(g.catalog['invert']['effects'][0])
        g.wave.publish(g.x,g.effects)
        before=[(g.stat('preview',p),g.stat('hand_limit',p)) for p in (0,1)]
        self.assertEqual(before,[(5,5),(5,5)])
        g.active=1; g.y=50
        self.do(g,'slap')
        for player in (0,1):
            self.assertEqual((g.stat('preview',player),g.stat('hand_limit',player)),before[player])
        self.assertEqual(g.stat('interval',0),g.config['interval']-.5)
        self.assertEqual({e.kind for e in g.effects},{'preview','hand_limit','interval'})
        self.assertEqual(len(g.effects),9)
        self.assertTrue(all(not e.clear_on_slap for e in g.effects))
        # 保留上限不只是顯示數字，出牌後也確實補到保留的上限。
        card=self.give(g,'ripple')
        self.do(g,'to_cards'); self.do(g,'play',card.uid)
        self.assertEqual(len(g.players[0].hand),5)
        self.assert_conservation(g)


    def test_dream_reshuffle_targets_own_remaining_hand_then_refills(self):
        g=self.game(); card=self.give(g,'shuffle')
        original_remaining={c.uid for c in g.players[0].hand if c.uid!=card.uid}
        opponent_before=list(g.players[1].hand)
        self.do(g,'to_cards'); self.do(g,'play',card.uid)
        self.assertEqual(g.players[1].hand,opponent_before)
        event=next(e for e in g.events if e['type']=='hand_reshuffled')
        self.assertEqual(event['target'],0)
        self.assertEqual(event['count'],len(original_remaining))
        self.assertTrue(original_remaining.issubset({c.uid for c in g.discard}))
        self.assertEqual(len(g.players[0].hand),max(g.config['hand_limit'],len(original_remaining)))
        self.assert_conservation(g)


    def test_conditional_dream_reshuffle_sign_and_zero(self):
        for y in (20,0,-20):
            g=self.game(); card=self.give(g,'shuffle'); g.y=y
            self.do(g,'to_cards'); self.do(g,'play',card.uid)
            reshuffles=[e for e in g.events if e['type']=='hand_reshuffled']
            self.assertEqual(bool(reshuffles),y>=0)
            self.assertEqual(g.stat('hand_limit',0),3 if y>=0 else 4)
            self.assertEqual(len(g.players[0].hand),3 if y>=0 else 4)
            if y<0:
                effect=next(e for e in g.effects if e.kind=='hand_limit')
                self.assertFalse(effect.clear_on_slap)
                self.assertNotIn('when',effect.params)
            event=next(e for e in g.events if e['type']=='card_played')
            self.assertEqual(event['landing_y'],y)
            self.assertEqual(len(event['selected_effects']),1)
            self.assert_conservation(g)

    def test_tool_crosses_zero_and_changes_card_branch(self):
        for start,end in ((20,-30),(-20,30),(80,30),(-80,-30),(50,0),(-50,0),(0,0)):
            g=self.game(); tool=self.give(g,'tool'); g.players[0].hand.remove(tool)
            g.players[0].tool=Tool(tool,0,2)
            card=self.give(g,'shuffle'); g.y=start
            self.do(g,'use_tool')
            self.assertEqual(g.y,end)
            self.do(g,'to_cards'); self.do(g,'play',card.uid)
            self.assertEqual(g.stat('hand_limit',0),4 if end<0 else 3)
            self.assertEqual(any(e['type']=='hand_reshuffled' for e in g.events),end>=0)
            self.assert_conservation(g)

    def test_conditional_wave_preview_uses_current_sign(self):
        g=self.game(); card=self.give(g,'ripple')
        # 通用條件入口也適用未來的條件波形牌，預覽只取當下有效分支。
        g.catalog['ripple']['effects'][0]['when']='landing_negative'
        g.y=20; self.assertIsNone(g.preview_wave(card.uid))
        g.y=-20; self.assertIsNotNone(g.preview_wave(card.uid))
        self.do(g,'to_cards'); preview=g.preview_wave(card.uid)
        self.do(g,'play',card.uid)
        for x in (.5,1,2,4): self.assertAlmostEqual(preview.value(x),g.wave.value(x))


    def test_snorer_passive_score_each_successful_turn(self):
        g=self.game(duration=3)
        self.assertEqual(g.players[0].score,1)
        self.assertFalse(g.role_used)
        self.skip_turn(g)
        self.assertEqual(g.players[0].score,1)
        self.skip_turn(g)
        self.assertEqual(g.players[0].score,2)
        self.assertEqual(g.x,3)
        self.skip_turn(g)
        self.assertEqual(g.phase,'ended')
        self.assertEqual(g.players[0].score,2)
        events=[e for e in g.events if e['type']=='snore_turn_scored']
        self.assertEqual([(e['x'],e['points']) for e in events],[(0,1),(3,1)])

    def test_snorer_passive_score_after_slap_and_configurable(self):
        g=self.game(snore_turn_score=3)
        self.assertEqual(g.players[0].score,3)
        self.skip_turn(g)
        self.do(g,'slap')
        self.assertEqual(g.players[0].score,6)
        self.assertFalse(g.role_used)
        g.y=50
        self.do(g,'score')
        self.assertEqual(g.players[0].score,16)
        g=self.game(snore_turn_score=0)
        self.assertEqual(g.players[0].score,0)
        self.assertFalse(any(e['type']=='snore_turn_scored' for e in g.events))


    def test_period_change_anchors_at_play_position(self):
        from math import sin,tau
        start=9
        wave=Wave(50,12,fade=0)
        wave.publish(start,[Effect('base_period',start,None,None,dict(factor=.7))])
        for x in (9+1e-6,10,13):
            expected=50*sin(tau*start/12+tau*(x-start)/(12*.7))
            self.assertAlmostEqual(wave.value(x),expected)
        self.assertAlmostEqual(wave.value(8),Wave(50,12).value(8))

    def test_repeated_period_changes_preserve_phase_and_amplitude(self):
        from math import sin,tau
        first=Effect('base_period',9,None,None,dict(factor=.7))
        second=Effect('base_period',15,None,None,dict(factor=.7))
        amplitude=Effect('base_amplitude',16,None,None,dict(factor=1.5))
        wave=Wave(50,12,fade=0)
        wave.publish(9,[first]); previous=wave.value(15)
        wave.publish(15,[first,second])
        self.assertAlmostEqual(wave.value(15+1e-7),previous,places=4)
        wave.publish(16,[first,second,amplitude])
        x=18
        phase=tau*9/12+tau*(15-9)/(12*.7)+tau*(x-15)/(12*.7*.7)
        self.assertAlmostEqual(wave.value(x),75*sin(phase))


    def test_exponential_slap_rounds_up_and_uses_config(self):
        from snorebattle.core import slap_points
        self.assertEqual(slap_points(1),2)
        self.assertEqual(slap_points(50),12)
        self.assertEqual(slap_points(100),132)
        self.assertEqual(slap_points(50,1.1),118)
        self.assertEqual(slap_points(50,1.0),1)
        for height,base,bonus,expected in ((50,1.05,0,12),(100,1.05,0,132),(50,1.1,3,121)):
            g=self.game(slap_base=base)
            g.active=1; g.y=height
            if bonus: g.apply_effect(dict(kind='score_bonus',amount=bonus,target='self'))
            self.do(g,'slap')
            self.assertEqual(g.players[1].score,expected)


    def test_exchange_draws_two_and_handles_exhausted_shared_deck(self):
        g=self.game()
        before=len(g.players[0].hand)
        self.do(g,'to_cards'); self.do(g,'discard',g.players[0].hand[0].uid)
        self.assertEqual(len(g.players[0].hand),before+1)
        self.assert_conservation(g)
        g=self.game()
        g.players[1].hand.extend(g.draw_pile); g.draw_pile=[]
        # 只有自己剛棄掉的一張可回收，第二張抽不到時也能正常結束。
        before=len(g.players[0].hand)
        self.do(g,'to_cards'); self.do(g,'discard',g.players[0].hand[0].uid)
        self.assertEqual(len(g.players[0].hand),before)
        self.assertEqual((g.active,g.phase),(1,'action'))
        self.assert_conservation(g)


    def test_all_slaps_achievement_uses_remaining_not_fixed_three(self):
        for total in (1,2,3,5):
            g=self.game(slaps=total)
            for used in range(total):
                g.active=1; g.phase='action'; g.role_used=False; g.y=50
                self.do(g,'slap')
                self.assertEqual('three_slaps' in g.achievements.unlocked,used==total-1)
            self.assertEqual(g.slaps_left,0)
        a=Achievements()
        for remaining in (4,3,2):
            a.consume(dict(type='slapped',player=1,remaining=remaining,timestamp='test'))
        self.assertNotIn('three_slaps',a.unlocked)


    def test_good_dream_bonus_applies_to_all_scores_and_survives_slap(self):
        g=self.game(); card=self.give(g,'bonus')
        self.assertEqual(g.players[0].score,1)
        self.do(g,'to_cards'); self.do(g,'play',card.uid)
        self.skip_turn(g)
        self.assertEqual(g.players[0].score,5)  # 開局1 + 本回合(1+3)
        self.assertEqual([e for e in g.events if e['type']=='snore_turn_scored'][-1]['points'],4)
        g.y=50; self.do(g,'score')
        self.assertEqual(g.players[0].score,18)  # 行動仍得10+3
        self.skip_turn(g); self.do(g,'slap')
        self.assertEqual(g.stat('score_bonus',0),3)
        self.assertEqual(g.players[0].score,22)  # 功能牌加成保留，巴掌後新回合仍得4分

    def test_passive_bonus_stacks_and_disabled_passive_stays_disabled(self):
        for base,expected in ((1,7),(2,8),(0,0)):
            g=self.game(snore_turn_score=base)
            for _ in range(2): g.apply_effect(g.catalog['bonus']['effects'][0])
            before=g.players[0].score
            self.skip_turn(g); self.skip_turn(g)
            self.assertEqual(g.players[0].score-before,expected)


    def test_new_score_source_uses_common_bonus_and_event(self):
        g=self.game()
        g.apply_effect(g.catalog['bonus']['effects'][0])
        before=g.players[0].score
        self.assertEqual(g.award_score(0,2,source='test_new_method'),5)
        self.assertEqual(g.players[0].score,before+5)
        event=g.events[-1]
        self.assertEqual(event['type'],'score_awarded')
        self.assertEqual((event['source'],event['base_points'],event['bonus'],event['points']),
                         ('test_new_method',2,3,5))
        self.assertEqual(event['total'],g.players[0].score)
        self.assertNotIn('both_sides',g.achievements.unlocked)
        self.assertEqual(g.award_score(1,2,source='test_other_player'),2)


    def test_function_category_survival_is_automatic_for_new_cards(self):
        g=self.game()
        # 模擬未來的新功能牌：即使資料遺留可清除標記，分類規則仍統一保留。
        g.catalog['ripple']['category']='功能'
        g.catalog['ripple']['effects'][0]['clear_on_slap']=True
        card=self.give(g,'ripple')
        preview=g.preview_wave(card.uid)
        self.do(g,'to_cards'); self.do(g,'play',card.uid)
        self.assertFalse(g.effects[-1].clear_on_slap)
        self.assertTrue(g.catalog['ripple']['effects'][0]['clear_on_slap'])
        for x in (2,4): self.assertAlmostEqual(preview.value(x),g.wave.value(x))
        g.y=50; self.do(g,'slap')
        self.assertEqual([e.kind for e in g.effects],['sin_add'])

if __name__=='__main__': unittest.main()
