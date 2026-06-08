"""
Technical indicators — SMA, EMA, RSI, ATR, S/R, Volume Profile.
"""

from typing import Optional, List, Tuple


def sma(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def sma_prev(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    return sum(closes[-(n + 1):-1]) / n


def ema(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    k = 2 / (n + 1)
    val = sum(closes[:n]) / n
    for price in closes[n:]:
        val = price * k + val * (1 - k)
    return val


def rsi(closes: List[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 2:
        return None
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    last_n = deltas[-n:]
    avg_gain = sum(x for x in last_n if x > 0) / n
    avg_loss = sum(-x for x in last_n if x < 0) / n
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def atr(highs: List[float], lows: List[float], closes: List[float], n: int = 14) -> Optional[float]:
    """
    Average True Range — ukuran volatilitas rata-rata.
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    if len(closes) < n + 1 or len(highs) < n + 1 or len(lows) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return None
    return sum(trs[-n:]) / n


# ------------------------------------------------------------------ #
#  Support & Resistance
# ------------------------------------------------------------------ #

def swing_levels(highs: List[float], lows: List[float], n: int = 50) -> Tuple[Optional[float], Optional[float]]:
    window_h = highs[-(n + 1):-1]
    window_l = lows[-(n + 1):-1]
    if not window_h or not window_l:
        return None, None
    return max(window_h), min(window_l)


def nearest_support(lows: List[float], current_price: float, lookback: int = 50) -> Optional[float]:
    window = lows[-(lookback + 1):-1]
    if len(window) < 3:
        return None
    swing_lows = [
        window[i] for i in range(1, len(window) - 1)
        if window[i] < window[i - 1] and window[i] < window[i + 1]
    ]
    if not swing_lows:
        return min(window)
    candidates = [s for s in swing_lows if s < current_price]
    if not candidates:
        return min(swing_lows)
    return max(candidates)


def nearest_resistance(highs: List[float], current_price: float, lookback: int = 50) -> Optional[float]:
    window = highs[-(lookback + 1):-1]
    if len(window) < 3:
        return None
    swing_highs = [
        window[i] for i in range(1, len(window) - 1)
        if window[i] > window[i - 1] and window[i] > window[i + 1]
    ]
    if not swing_highs:
        return max(window)
    candidates = [s for s in swing_highs if s > current_price]
    if not candidates:
        return max(swing_highs)
    return min(candidates)


# ------------------------------------------------------------------ #
#  Volume Profile
# ------------------------------------------------------------------ #

def volume_strength(volumes: List[float], closes: List[float], n: int = 20) -> Tuple[str, float]:
    if len(volumes) < n + 1:
        return "WEAK", 0.0
    avg = sum(volumes[-(n + 1):-1]) / n
    if avg == 0:
        return "WEAK", 0.0
    ratio = volumes[-1] / avg
    price_up = closes[-1] > closes[-2]
    if ratio >= 2.0 and price_up:
        return "STRONG 🔥", ratio
    if ratio >= 1.5:
        return "MODERATE ✅", ratio
    return "WEAK ⚠️", ratio


# ------------------------------------------------------------------ #
#  Dynamic SL & R/R
# ------------------------------------------------------------------ #

def dynamic_sl(lows: List[float], current_price: float, lookback: int = 50, buffer_pct: float = 1.0) -> Optional[float]:
    support = nearest_support(lows, current_price, lookback)
    if support is None:
        return None
    return support * (1 - buffer_pct / 100)


def calc_rr(entry: float, target: float, stop: float) -> Optional[float]:
    if stop >= entry or entry <= 0:
        return None
    risk   = entry - stop
    reward = target - entry
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def entry_zone(current_price: float, support: Optional[float], ma200: Optional[float]) -> Tuple[float, float]:
    lower_candidates = [x for x in [support, ma200] if x is not None]
    lower = max(lower_candidates) if lower_candidates else current_price * 0.98
    return lower, current_price


# ------------------------------------------------------------------ #
#  Compute all indicators in one pass
# ------------------------------------------------------------------ #

def compute_indicators(
    closes: List[float],
    timeframe: str,
    highs: Optional[List[float]] = None,
    lows: Optional[List[float]] = None,
    volumes: Optional[List[float]] = None,
) -> dict:
    current = closes[-1]
    ma200   = sma(closes, 200)

    sup = res = swing_h = swing_l = None
    if highs and lows:
        swing_h, swing_l = swing_levels(highs, lows, n=50)
        sup = nearest_support(lows, current)
        res = nearest_resistance(highs, current)

    vol_label, vol_ratio = ("N/A", 0.0)
    if volumes:
        vol_label, vol_ratio = volume_strength(volumes, closes)

    dyn_sl_val = None
    if lows:
        dyn_sl_val = dynamic_sl(lows, current)
    entry_low, entry_high = entry_zone(current, sup, ma200)

    # ATR — untuk filter volatilitas
    atr_val = None
    if highs and lows:
        atr_val = atr(highs, lows, closes)

    result = {
        "ma200c":     ma200,
        "ma200p":     sma_prev(closes, 200),
        "e50":        ema(closes, 50),
        "e200":       ema(closes, 200),
        "rsic":       rsi(closes),
        "rsip":       rsi(closes[:-1]),
        "ma50c":      None,
        "ma50p":      None,
        "swing_high": swing_h,
        "swing_low":  swing_l,
        "support":    sup,
        "resistance": res,
        "vol_label":  vol_label,
        "vol_ratio":  vol_ratio,
        "dyn_sl":     dyn_sl_val,
        "entry_low":  entry_low,
        "entry_high": entry_high,
        "atr":        atr_val,     # ← BARU
    }
    if timeframe == "4H":
        result["ma50c"] = sma(closes, 50)
        result["ma50p"] = sma_prev(closes, 50)
    return result
