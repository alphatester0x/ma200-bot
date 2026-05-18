"""
Unit tests untuk indicators.py (menggunakan stdlib unittest, tanpa pytest).
Jalankan: python -m unittest discover -s tests -v
"""

import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from indicators import sma, sma_prev, ema, rsi, compute_indicators


class TestSMA(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(sma([1, 2, 3, 4, 5], 3), 4.0)

    def test_exact_length(self):
        self.assertAlmostEqual(sma([10, 20, 30], 3), 20.0)

    def test_insufficient(self):
        self.assertIsNone(sma([1, 2], 5))

    def test_sma_prev_basic(self):
        # sma_prev(n=3) dari [1..6] = mean([3,4,5]) = 4.0
        self.assertAlmostEqual(sma_prev([1, 2, 3, 4, 5, 6], 3), 4.0)

    def test_sma_prev_insufficient(self):
        self.assertIsNone(sma_prev([1, 2, 3], 3))


class TestEMA(unittest.TestCase):

    def test_flat_series(self):
        self.assertAlmostEqual(ema([100.0] * 20, 10), 100.0)

    def test_insufficient(self):
        self.assertIsNone(ema([1, 2, 3], 10))

    def test_trend_up_lags(self):
        closes = list(range(1, 21))
        result = ema(closes, 10)
        self.assertIsNotNone(result)
        self.assertLess(result, closes[-1])


class TestRSI(unittest.TestCase):

    def test_all_gains(self):
        closes = [float(i) for i in range(1, 20)]
        self.assertAlmostEqual(rsi(closes), 100.0)

    def test_all_losses(self):
        closes = [float(i) for i in range(20, 0, -1)]
        self.assertAlmostEqual(rsi(closes), 0.0)

    def test_range(self):
        import random; random.seed(42)
        closes = [random.uniform(100, 200) for _ in range(50)]
        r = rsi(closes)
        self.assertIsNotNone(r)
        self.assertGreaterEqual(r, 0)
        self.assertLessEqual(r, 100)

    def test_insufficient(self):
        self.assertIsNone(rsi([1, 2, 3], 14))


class TestComputeIndicators(unittest.TestCase):

    BASE = [float(i) for i in range(1, 210)]

    def test_all_keys_present(self):
        ind = compute_indicators(self.BASE, "4H")
        for key in ("ma200c", "ma200p", "e50", "e200", "rsic", "rsip", "ma50c", "ma50p"):
            self.assertIn(key, ind)

    def test_1d_no_ma50(self):
        ind = compute_indicators(self.BASE, "1D")
        self.assertIsNone(ind["ma50c"])
        self.assertIsNone(ind["ma50p"])

    def test_4h_has_ma50(self):
        ind = compute_indicators(self.BASE, "4H")
        self.assertIsNotNone(ind["ma50c"])
        self.assertIsNotNone(ind["ma50p"])


if __name__ == "__main__":
    unittest.main()
