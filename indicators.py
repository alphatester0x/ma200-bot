"""
Technical indicators — SMA, EMA, RSI.
Semua fungsi menerima list closes dan mengembalikan float | None.
"""

from typing import Optional, List


def sma(closes: List[float], n: int) -> Optional[float]:
    """Simple Moving Average dari n bar terakhir (current)."""
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def sma_prev(closes: List[float], n: int) -> Optional[float]:
    """SMA dari n bar sebelum bar terakhir (bar ke-2 dari ujung)."""
    if len(closes) < n + 1:
        return None
    return sum(closes[-(n + 1):-1]) / n


def ema(closes: List[float], n: int) -> Optional[float]:
    """Exponential Moving Average, seed = SMA dari n bar pertama."""
    if len(closes) < n:
        return None
    k = 2 / (n + 1)
    val = sum(closes[:n]) / n
    for price in closes[n:]:
        val = price * k + val * (1 - k)
    return val


def rsi(closes: List[float], n: int = 14) -> Optional[float]:
    """Relative Strength Index (Wilder smoothing, simplified)."""
    if len(closes) < n + 2:
        return None
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    last_n = deltas[-n:]
    avg_gain = sum(x for x in last_n if x > 0) / n
    avg_loss = sum(-x for x in last_n if x < 0) / n
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


# ------------------------------------------------------------------ #
#  Convenience: compute all indicators in one pass
# ------------------------------------------------------------------ #

def compute_indicators(closes: List[float], timeframe: str) -> dict:
    """
    Hitung semua indikator sekaligus dari satu list closes.
    Menghindari pemanggilan berulang dengan data yang sama.

    Returns dict dengan key:
        ma200c, ma200p, ma50c (4H only), ma50p (4H only),
        e50, e200, rsic, rsip
    """
    result = {
        "ma200c": sma(closes, 200),
        "ma200p": sma_prev(closes, 200),
        "e50":    ema(closes, 50),
        "e200":   ema(closes, 200),
        "rsic":   rsi(closes),
        "rsip":   rsi(closes[:-1]),
        "ma50c":  None,
        "ma50p":  None,
    }
    if timeframe == "4H":
        result["ma50c"] = sma(closes, 50)
        result["ma50p"] = sma_prev(closes, 50)
    return result
