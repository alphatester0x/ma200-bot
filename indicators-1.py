"""
Technical indicators — SMA, EMA, RSI, S/R, Swing levels, Volume Profile.
Semua fungsi menerima list closes dan mengembalikan float | None.
"""

from typing import Optional, List, Tuple


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
#  Support & Resistance
# ------------------------------------------------------------------ #

def swing_levels(
    highs: List[float],
    lows: List[float],
    n: int = 50,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Cari swing high dan swing low dari n bar terakhir (exclude bar terkini).
    Returns (swing_high, swing_low).
    """
    window_h = highs[-(n + 1):-1]
    window_l = lows[-(n + 1):-1]
    if not window_h or not window_l:
        return None, None
    return max(window_h), min(window_l)


def nearest_support(
    lows: List[float],
    current_price: float,
    lookback: int = 50,
) -> Optional[float]:
    """
    Cari level support terdekat di BAWAH harga sekarang.
    Caranya: cari swing low lokal (lows yang lebih rendah dari tetangganya)
    dalam window lookback, lalu ambil yang terdekat ke current_price.
    """
    window = lows[-(lookback + 1):-1]
    if len(window) < 3:
        return None

    # Swing low lokal: bar lebih rendah dari bar kiri dan kanan
    swing_lows = [
        window[i]
        for i in range(1, len(window) - 1)
        if window[i] < window[i - 1] and window[i] < window[i + 1]
    ]
    if not swing_lows:
        return min(window)  # fallback: lowest in window

    # Ambil swing low yang ada di bawah harga sekarang, terdekat
    candidates = [s for s in swing_lows if s < current_price]
    if not candidates:
        return min(swing_lows)
    return max(candidates)   # yang paling dekat dari bawah


def nearest_resistance(
    highs: List[float],
    current_price: float,
    lookback: int = 50,
) -> Optional[float]:
    """
    Cari level resistance terdekat di ATAS harga sekarang.
    """
    window = highs[-(lookback + 1):-1]
    if len(window) < 3:
        return None

    swing_highs = [
        window[i]
        for i in range(1, len(window) - 1)
        if window[i] > window[i - 1] and window[i] > window[i + 1]
    ]
    if not swing_highs:
        return max(window)

    candidates = [s for s in swing_highs if s > current_price]
    if not candidates:
        return max(swing_highs)
    return min(candidates)   # yang paling dekat dari atas


# ------------------------------------------------------------------ #
#  Volume Profile (simplified)
# ------------------------------------------------------------------ #

def volume_strength(
    volumes: List[float],
    closes: List[float],
    n: int = 20,
) -> Tuple[str, float]:
    """
    Nilai kekuatan volume bar terakhir vs rata-rata n bar sebelumnya.
    Returns (label, ratio) dimana label: "STRONG" | "MODERATE" | "WEAK"
    """
    if len(volumes) < n + 1:
        return "WEAK", 0.0

    avg = sum(volumes[-(n + 1):-1]) / n
    if avg == 0:
        return "WEAK", 0.0

    ratio = volumes[-1] / avg
    # Apakah volume naik sejalan dengan harga (bullish confirmation)?
    price_up = closes[-1] > closes[-2]

    if ratio >= 2.0 and price_up:
        return "STRONG 🔥", ratio
    if ratio >= 1.5:
        return "MODERATE ✅", ratio
    return "WEAK ⚠️", ratio


# ------------------------------------------------------------------ #
#  Dynamic Stop Loss & Risk/Reward
# ------------------------------------------------------------------ #

def dynamic_sl(
    lows: List[float],
    current_price: float,
    lookback: int = 50,
    buffer_pct: float = 1.0,
) -> Optional[float]:
    """
    Hitung dynamic stop loss berdasarkan swing low terdekat minus buffer.
    buffer_pct: % di bawah swing low sebagai safety margin (default 1%).
    """
    support = nearest_support(lows, current_price, lookback)
    if support is None:
        return None
    return support * (1 - buffer_pct / 100)


def calc_rr(
    entry: float,
    target: float,
    stop: float,
) -> Optional[float]:
    """
    Hitung Risk/Reward ratio.
    R/R = (target - entry) / (entry - stop)
    Returns None jika stop >= entry (invalid).
    """
    if stop >= entry or entry <= 0:
        return None
    risk   = entry - stop
    reward = target - entry
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def entry_zone(
    current_price: float,
    support: Optional[float],
    ma200: Optional[float],
) -> Tuple[float, float]:
    """
    Hitung zona entry ideal.
    Lower bound: level support atau MA200 (mana yang lebih tinggi).
    Upper bound: harga sekarang (sudah di atas MA200, jangan kejar terlalu jauh).
    """
    lower_candidates = [x for x in [support, ma200] if x is not None]
    lower = max(lower_candidates) if lower_candidates else current_price * 0.98
    upper = current_price
    return lower, upper


# ------------------------------------------------------------------ #
#  Convenience: compute all indicators in one pass
# ------------------------------------------------------------------ #

def compute_indicators(
    closes: List[float],
    timeframe: str,
    highs: Optional[List[float]] = None,
    lows: Optional[List[float]] = None,
    volumes: Optional[List[float]] = None,
) -> dict:
    """
    Hitung semua indikator sekaligus dari satu list closes.
    Menghindari pemanggilan berulang dengan data yang sama.

    Returns dict dengan key:
        ma200c, ma200p, ma50c (4H only), ma50p (4H only),
        e50, e200, rsic, rsip,
        swing_high, swing_low,
        support, resistance,
        vol_label, vol_ratio,
        dyn_sl, entry_low, entry_high
    """
    current = closes[-1]
    ma200   = sma(closes, 200)

    # S/R — butuh highs & lows
    sup = res = swing_h = swing_l = None
    if highs and lows:
        swing_h, swing_l = swing_levels(highs, lows, n=50)
        sup = nearest_support(lows, current)
        res = nearest_resistance(highs, current)

    # Volume profile
    vol_label, vol_ratio = ("N/A", 0.0)
    if volumes:
        vol_label, vol_ratio = volume_strength(volumes, closes)

    # Dynamic SL & entry zone
    dyn_sl_val = entry_low = entry_high = None
    if lows:
        dyn_sl_val = dynamic_sl(lows, current)
    entry_low, entry_high = entry_zone(current, sup, ma200)

    result = {
        "ma200c":     ma200,
        "ma200p":     sma_prev(closes, 200),
        "e50":        ema(closes, 50),
        "e200":       ema(closes, 200),
        "rsic":       rsi(closes),
        "rsip":       rsi(closes[:-1]),
        "ma50c":      None,
        "ma50p":      None,
        # S/R
        "swing_high": swing_h,
        "swing_low":  swing_l,
        "support":    sup,
        "resistance": res,
        # Volume profile
        "vol_label":  vol_label,
        "vol_ratio":  vol_ratio,
        # Entry & risk
        "dyn_sl":     dyn_sl_val,
        "entry_low":  entry_low,
        "entry_high": entry_high,
    }
    if timeframe == "4H":
        result["ma50c"] = sma(closes, 50)
        result["ma50p"] = sma_prev(closes, 50)
    return result
