import unittest
from snorebattle.scoring import calculate_points, slap_base_points, slap_points
from snorebattle.errors import RuleError

class ScoringTests(unittest.TestCase):
    def test_common_bonus_rounding_and_lower_bound(self):
        self.assertEqual(calculate_points(1,3),4)
        self.assertEqual(calculate_points(1,6),7)
        self.assertEqual(calculate_points(2.2,3),5)
        self.assertEqual(calculate_points(2.2,3,rounding='ceil'),6)
        self.assertEqual(calculate_points(2,-10),0)

    def test_slap_formula_uses_common_calculation(self):
        self.assertEqual(slap_points(50),12)
        self.assertEqual(slap_points(50,bonus=3),15)
        self.assertEqual(slap_points(100),132)
        self.assertEqual(calculate_points(slap_base_points(50),3,rounding='ceil'),15)

    def test_invalid_calculation_raises_rule_error(self):
        for value in (float('inf'),float('nan')):
            with self.assertRaises(RuleError): calculate_points(value)
        with self.assertRaises(RuleError): calculate_points(1,rounding='unknown')
        with self.assertRaises(RuleError): slap_base_points(1000000000)
