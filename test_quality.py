"""
Unit tests untuk fitur quality filter:
ATR, quality gate, real highs, cross distance.
"""

import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from indicators import atr, compute_indicators
from scanner import _passes_quality_gate, _build_confirmation


class TestATR(unittest.TestCase):

    def test_basic(self):
        highs  = [11.0] * 20
        lows   = [9.0]  * 20
        closes = [10.0] * 20
        result = atr(highs, lows, closes, n=14)
        self.assertIsNotNone(result)
        self.assertGreater(result, 0)

    def test_flat_market(self):
        # Flat market: TR = high - low = 2 setiap bar
        highs  = [11.0] * 20
        lows   = [9.0]  * 20
        closes = [10.0] * 20
        result = atr(highs, lows, closes, n=14)
        self.assertAlmostEqual(result, 2.0)

    def test_insufficient(self):
        self.assertIsNone(atr([1.0], [0.5], [0.8], n=14))

    def test_atr_in_compute_indicators(self):
        import random; random.seed(1)
        n = 210
        closes = [100 + random.uniform(-5, 5) for _ in range(n)]
        highs  = [c + random.uniform(0, 2) for c in closes]
        lows   = [c - random.uniform(0, 2) for c in closes]
        vols   = [random.uniform(1, 3) for _ in range(n)]
        ind = compute_indicators(closes, "4H", highs=highs, lows=lows, volumes=vols)
        self.assertIn("atr", ind)
        self.assertIsNotNone(ind["atr"])
        self.assertGreater(ind["atr"], 0)


class TestQualityGate(unittest.TestCase):

    BASE_KWARGS = dict(
        symbol="TESTUSDT",
        score=3,
        rr=2.0,
        cross_dist_pct=1.5,
        atr_val=1.0,
        entry=100.0,
        vol_24h_usdt=1_000_000,
    )

    def test_all_pass(self):
        ok, reason = _passes_quality_gate(**self.BASE_KWARGS)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_fail_low_vol(self):
        kw = {**self.BASE_KWARGS, "vol_24h_usdt": 100_000}
        ok, reason = _passes_quality_gate(**kw)
        self.assertFalse(ok)
        self.assertIn("vol_usdt", reason)

    def test_fail_low_score(self):
        kw = {**self.BASE_KWARGS, "score": 2}
        ok, reason = _passes_quality_gate(**kw)
        self.assertFalse(ok)
        self.assertIn("score", reason)

    def test_fail_low_rr(self):
        kw = {**self.BASE_KWARGS, "rr": 1.0}
        ok, reason = _passes_quality_gate(**kw)
        self.assertFalse(ok)
        self.assertIn("R/R", reason)

    def test_fail_rr_none(self):
        kw = {**self.BASE_KWARGS, "rr": None}
        ok, reason = _passes_quality_gate(**kw)
        self.assertFalse(ok)

    def test_fail_cross_too_far(self):
        kw = {**self.BASE_KWARGS, "cross_dist_pct": 5.0}
        ok, reason = _passes_quality_gate(**kw)
        self.assertFalse(ok)
        self.assertIn("cross dist", reason)

    def test_fail_atr_too_high(self):
        # ATR 20% dari entry price → terlalu volatile
        kw = {**self.BASE_KWARGS, "atr_val": 20.0, "entry": 100.0}
        ok, reason = _passes_quality_gate(**kw)
        self.assertFalse(ok)
        self.assertIn("ATR", reason)

    def test_pass_atr_none(self):
        # ATR None tidak di-filter (data tidak tersedia)
        kw = {**self.BASE_KWARGS, "atr_val": None}
        ok, _ = _passes_quality_gate(**kw)
        self.assertTrue(ok)


class TestConfirmationScore(unittest.TestCase):

    def test_all_green(self):
        _, score = _build_confirmation(vol_ratio=2.5, is_green=True, is_gc=True)
        self.assertEqual(score, 3)

    def test_all_fail(self):
        _, score = _build_confirmation(vol_ratio=1.0, is_green=False, is_gc=False)
        self.assertEqual(score, 0)

    def test_partial(self):
        _, score = _build_confirmation(vol_ratio=2.5, is_green=True, is_gc=False)
        self.assertEqual(score, 2)


if __name__ == "__main__":
    unittest.main()
