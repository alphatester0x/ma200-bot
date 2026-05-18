"""
Unit tests untuk fitur baru indicators.py:
S/R levels, dynamic SL, R/R ratio, entry zone, volume strength.
Jalankan: python -m unittest discover -s tests -v
"""

import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from indicators import (
    nearest_support, nearest_resistance, swing_levels,
    dynamic_sl, calc_rr, entry_zone, volume_strength,
    compute_indicators,
)


class TestSwingLevels(unittest.TestCase):

    def _make_data(self):
        highs  = [float(i % 10 + 1) for i in range(60)]
        lows   = [float(i % 5 + 0.5) for i in range(60)]
        return highs, lows

    def test_returns_tuple(self):
        h, l = self._make_data()
        result = swing_levels(h, l, n=50)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_insufficient(self):
        sh, sl = swing_levels([1.0], [0.5], n=50)
        self.assertIsNone(sh)
        self.assertIsNone(sl)


class TestNearestSupport(unittest.TestCase):

    def test_finds_support_below_price(self):
        # Lows dengan pola jelas: ada swing low di sekitar 5.0
        lows = [10, 5, 10, 5, 10, 5, 10, 5, 10, 5] * 6
        result = nearest_support(lows, current_price=8.0, lookback=50)
        self.assertIsNotNone(result)
        self.assertLess(result, 8.0)

    def test_insufficient_data(self):
        result = nearest_support([1.0, 2.0], current_price=1.5, lookback=50)
        self.assertIsNone(result)


class TestNearestResistance(unittest.TestCase):

    def test_finds_resistance_above_price(self):
        highs = [10, 5, 10, 5, 10, 5, 10, 5, 10, 5] * 6
        result = nearest_resistance(highs, current_price=7.0, lookback=50)
        self.assertIsNotNone(result)
        self.assertGreater(result, 7.0)

    def test_insufficient_data(self):
        result = nearest_resistance([1.0, 2.0], current_price=1.5, lookback=50)
        self.assertIsNone(result)


class TestDynamicSL(unittest.TestCase):

    def test_sl_below_entry(self):
        lows = [10, 5, 10, 5, 10, 5, 10, 5, 10, 5] * 6
        sl = dynamic_sl(lows, current_price=8.0, lookback=50, buffer_pct=1.0)
        self.assertIsNotNone(sl)
        self.assertLess(sl, 8.0)

    def test_sl_includes_buffer(self):
        # Buffer 1% harus membuat SL lebih rendah dari support murni
        lows = [10, 5, 10, 5, 10, 5, 10, 5, 10, 5] * 6
        sl_1 = dynamic_sl(lows, current_price=8.0, lookback=50, buffer_pct=1.0)
        sl_0 = dynamic_sl(lows, current_price=8.0, lookback=50, buffer_pct=0.0)
        if sl_1 and sl_0:
            self.assertLess(sl_1, sl_0)


class TestCalcRR(unittest.TestCase):

    def test_basic(self):
        # entry=100, target=110, stop=90 → R/R = 10/10 = 1.0
        rr = calc_rr(100.0, 110.0, 90.0)
        self.assertAlmostEqual(rr, 1.0)

    def test_good_rr(self):
        # entry=100, target=115, stop=90 → R/R = 15/10 = 1.5
        rr = calc_rr(100.0, 115.0, 90.0)
        self.assertAlmostEqual(rr, 1.5)

    def test_invalid_stop_above_entry(self):
        self.assertIsNone(calc_rr(100.0, 110.0, 105.0))

    def test_invalid_zero_entry(self):
        self.assertIsNone(calc_rr(0.0, 10.0, -5.0))


class TestEntryZone(unittest.TestCase):

    def test_lower_bound_is_max_of_support_ma200(self):
        low, high = entry_zone(current_price=100.0, support=90.0, ma200=95.0)
        # lower bound = max(90, 95) = 95
        self.assertAlmostEqual(low, 95.0)
        self.assertAlmostEqual(high, 100.0)

    def test_no_support(self):
        low, high = entry_zone(current_price=100.0, support=None, ma200=95.0)
        self.assertAlmostEqual(low, 95.0)
        self.assertAlmostEqual(high, 100.0)

    def test_no_ma200(self):
        low, high = entry_zone(current_price=100.0, support=90.0, ma200=None)
        self.assertAlmostEqual(low, 90.0)
        self.assertAlmostEqual(high, 100.0)

    def test_both_none_fallback(self):
        low, high = entry_zone(current_price=100.0, support=None, ma200=None)
        # fallback: 98% dari current price
        self.assertAlmostEqual(low, 98.0)
        self.assertAlmostEqual(high, 100.0)


class TestVolumeStrength(unittest.TestCase):

    def test_strong_volume_bullish(self):
        vols   = [1.0] * 21
        vols[-1] = 3.0          # 3x rata-rata
        closes = [1.0] * 20 + [1.1]   # candle naik
        label, ratio = volume_strength(vols, closes, n=20)
        self.assertIn("STRONG", label)
        self.assertAlmostEqual(ratio, 3.0)

    def test_moderate_volume(self):
        vols   = [1.0] * 21
        vols[-1] = 1.6
        closes = [1.0] * 20 + [0.9]   # candle turun (tidak bullish)
        label, ratio = volume_strength(vols, closes, n=20)
        self.assertIn("MODERATE", label)

    def test_weak_volume(self):
        vols   = [1.0] * 21
        vols[-1] = 1.2          # < 1.5x threshold
        closes = [1.0] * 21
        label, ratio = volume_strength(vols, closes, n=20)
        self.assertIn("WEAK", label)

    def test_insufficient(self):
        label, ratio = volume_strength([1.0, 2.0], [1.0, 2.0], n=20)
        self.assertEqual(label, "WEAK")
        self.assertEqual(ratio, 0.0)


class TestComputeIndicatorsFull(unittest.TestCase):
    """Test compute_indicators dengan highs/lows/volumes."""

    def setUp(self):
        import random; random.seed(7)
        n = 210
        self.closes  = [100 + random.uniform(-5, 5) for _ in range(n)]
        self.highs   = [c + random.uniform(0, 2) for c in self.closes]
        self.lows    = [c - random.uniform(0, 2) for c in self.closes]
        self.volumes = [random.uniform(0.5, 3.0) for _ in range(n)]

    def test_all_sr_keys_present(self):
        ind = compute_indicators(
            self.closes, "4H",
            highs=self.highs, lows=self.lows, volumes=self.volumes,
        )
        for key in ("support", "resistance", "dyn_sl", "entry_low", "entry_high",
                    "vol_label", "vol_ratio"):
            self.assertIn(key, ind)

    def test_entry_zone_ordered(self):
        ind = compute_indicators(
            self.closes, "4H",
            highs=self.highs, lows=self.lows, volumes=self.volumes,
        )
        self.assertLessEqual(ind["entry_low"], ind["entry_high"])

    def test_dyn_sl_below_price(self):
        ind = compute_indicators(
            self.closes, "4H",
            highs=self.highs, lows=self.lows, volumes=self.volumes,
        )
        if ind["dyn_sl"]:
            self.assertLess(ind["dyn_sl"], self.closes[-1])


if __name__ == "__main__":
    unittest.main()
