"""
Scanner — logika scan sinyal per symbol.
Quality over quantity: semua filter di-hardcode, tidak ada warning-only.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional

from config import (
    VOLUME_MULTIPLIER, MIN_RR_RATIO, MAX_CROSS_DIST_PCT,
    MIN_SCORE, MAX_ATR_PCT, ATR_PERIOD,
    SIGNAL_META, SIGNAL_SCORE_LABEL, SIGNAL_PRIORITY,
    PROFIT_TARGET_PCT, STOPLOSS_PCT,
)
from binance_api import fetch_ohlcv, fetch_24h_vol_usdt
from indicators import compute_indicators, calc_rr
from config import MIN_VOL_USDT
from logger import get_logger

log = get_logger("scanner")


@dataclass
class Signal:
    symbol:      str
    signal_type: str
    timeframe:   str
    score:       int
    entry_price: float
    detail:      str
    dyn_sl:      Optional[float] = None

    @property
    def sort_key(self):
        return (-self.score, SIGNAL_PRIORITY.get(self.signal_type, 9))


# ------------------------------------------------------------------ #
#  Entry guide block
# ------------------------------------------------------------------ #

def _build_entry_info(entry: float, ind: dict) -> Tuple[str, Optional[float]]:
    """
    Returns (teks_entry_guide, rr_value).
    rr_value dipakai untuk hard filter di caller.
    """
    target     = entry * (1 + PROFIT_TARGET_PCT / 100)
    dyn_sl     = ind.get("dyn_sl")
    support    = ind.get("support")
    resistance = ind.get("resistance")
    entry_low  = ind.get("entry_low", entry)
    entry_high = ind.get("entry_high", entry)
    vol_label  = ind.get("vol_label", "N/A")
    atr_val    = ind.get("atr")

    sl_price = dyn_sl if dyn_sl else entry * (1 + STOPLOSS_PCT / 100)
    rr       = calc_rr(entry, target, sl_price)
    rr_str   = f"{rr:.2f}" if rr else "N/A"

    # ATR sebagai % harga — info konteks
    atr_pct_str = f"{(atr_val / entry * 100):.1f}%" if atr_val else "N/A"

    lines = [
        "─────────────────────────",
        "📊 <b>Entry Guide</b>",
        f"🎯 Entry Zone : <b>{entry_low:.6f} – {entry_high:.6f}</b>",
        f"🎯 Target     : <b>{target:.6f}</b> (+{PROFIT_TARGET_PCT:.0f}%)",
        f"🛑 Stop Loss  : <b>{sl_price:.6f}</b>" + (" (dynamic)" if dyn_sl else " (flat)"),
        f"📐 R/R Ratio  : <b>{rr_str}</b>",
        f"📉 ATR        : <b>{atr_pct_str}</b> (volatilitas)",
        "─────────────────────────",
        "📈 <b>Level Kunci</b>",
    ]
    if support:
        lines.append(f"🟢 Support    : <b>{support:.6f}</b>")
    if resistance:
        lines.append(f"🔴 Resistance : <b>{resistance:.6f}</b>")
    lines.append(f"📦 Volume     : <b>{vol_label}</b>")

    return "\n".join(lines), rr


# ------------------------------------------------------------------ #
#  Confirmation score
# ------------------------------------------------------------------ #

def _build_confirmation(vol_ratio: float, is_green: bool, is_gc: bool) -> Tuple[str, int]:
    vol_ok = vol_ratio >= VOLUME_MULTIPLIER
    score  = sum([vol_ok, is_green, is_gc])
    conf   = (
        f"{'✅' if vol_ok   else '❌'} Vol: {vol_ratio:.1f}x avg\n"
        f"{'✅' if is_green else '❌'} Candle: {'Hijau' if is_green else 'Merah'}\n"
        f"{'✅' if is_gc    else '❌'} EMA GC: {'Ya' if is_gc else 'Belum'}"
    )
    return conf, score


# ------------------------------------------------------------------ #
#  Quality gate — semua hard filter dalam satu tempat
# ------------------------------------------------------------------ #

def _passes_quality_gate(
    symbol: str,
    score: int,
    rr: Optional[float],
    cross_dist_pct: float,
    atr_val: Optional[float],
    entry: float,
    vol_24h_usdt: float,
) -> Tuple[bool, str]:
    """
    Returns (lolos, alasan_gagal).
    Semua filter bersifat hard — tidak ada yang cuma warning.
    """
    if vol_24h_usdt < MIN_VOL_USDT:
        return False, f"vol_usdt {vol_24h_usdt/1000:.0f}K < {MIN_VOL_USDT/1000:.0f}K"

    if score < MIN_SCORE:
        return False, f"score {score} < {MIN_SCORE}"

    if rr is None or rr < MIN_RR_RATIO:
        return False, f"R/R {rr} < {MIN_RR_RATIO}"

    if cross_dist_pct > MAX_CROSS_DIST_PCT:
        return False, f"cross dist {cross_dist_pct:.1f}% > {MAX_CROSS_DIST_PCT}%"

    if atr_val is not None and entry > 0:
        atr_pct = atr_val / entry * 100
        if atr_pct > MAX_ATR_PCT:
            return False, f"ATR {atr_pct:.1f}% > {MAX_ATR_PCT}% (terlalu volatile)"

    return True, ""


# ------------------------------------------------------------------ #
#  Per-symbol scan
# ------------------------------------------------------------------ #

def scan_symbol(symbol: str) -> Tuple[str, List[Signal]]:
    signals: List[Signal] = []

    # Cek likuiditas 24h sekali saja (shared untuk 4H dan 1D)
    vol_24h = fetch_24h_vol_usdt(symbol)
    if vol_24h < MIN_VOL_USDT:
        return symbol, []   # early exit, hemat API call fetch_ohlcv

    for interval, tf in [("4h", "4H"), ("1d", "1D")]:
        data = fetch_ohlcv(symbol, interval)
        if data is None:
            continue

        opens, highs, lows, closes, vols = data   # highs sekarang REAL

        ind = compute_indicators(closes, tf, highs=highs, lows=lows, volumes=vols)

        ma200c = ind["ma200c"]
        ma200p = ind["ma200p"]
        e50    = ind["e50"]
        e200   = ind["e200"]
        rsic   = ind["rsic"]
        rsip   = ind["rsip"]
        ma50c  = ind["ma50c"]
        ma50p  = ind["ma50p"]
        atr_v  = ind["atr"]

        if not ma200c or not e50 or not e200:
            continue

        cc   = closes[-1]
        co   = opens[-1]
        cl   = lows[-1]
        pc   = closes[-2]
        body = (cc - co) / co * 100

        # Volume bar terakhir
        avg_v = sum(vols[-21:-1]) / 20
        vol_r = vols[-1] / avg_v if avg_v > 0 else 0

        is_green = cc > co
        is_gc    = e50 > e200
        conf, score = _build_confirmation(vol_r, is_green, is_gc)

        # Entry guide & R/R (hitung sekali, dipakai semua sinyal di TF ini)
        entry_info, rr = _build_entry_info(cc, ind)

        # Jarak close ke MA200 (%) — makin kecil makin valid
        cross_dist = abs(cc - ma200c) / ma200c * 100 if ma200c else 999

        def _gate(label: str) -> bool:
            ok, reason = _passes_quality_gate(symbol, score, rr, cross_dist, atr_v, cc, vol_24h)
            if not ok:
                log.debug("[FILTER] %s %s [%s]: %s", symbol, label, tf, reason)
            return ok

        # ── 1. MA200 Cross ────────────────────────────────────────────
        if ma200p and pc < ma200p and cc > ma200c:
            if _gate("MA200_CROSS"):
                signals.append(Signal(
                    symbol=symbol, signal_type="MA200_CROSS",
                    timeframe=tf, score=score, entry_price=cc,
                    dyn_sl=ind.get("dyn_sl"),
                    detail=(
                        f"Close <b>{cc:.6f}</b> crossing MA200 <b>{ma200c:.6f}</b>\n"
                        f"Jarak ke MA200: <b>{cross_dist:.2f}%</b>\n\n"
                        f"<b>Konfirmasi:</b>\n{conf}\n\n"
                        f"{entry_info}"
                    ),
                ))

        # ── 2. RSI Recovery ───────────────────────────────────────────
        elif rsic and rsip and cc > ma200c and rsip < 35 and rsic >= 35:
            if _gate("RSI_RECOVERY"):
                signals.append(Signal(
                    symbol=symbol, signal_type="RSI_RECOVERY",
                    timeframe=tf, score=score, entry_price=cc,
                    dyn_sl=ind.get("dyn_sl"),
                    detail=(
                        f"Close <b>{cc:.6f}</b> > MA200 <b>{ma200c:.6f}</b>\n"
                        f"RSI: <b>{rsip:.1f}</b> → <b>{rsic:.1f}</b>\n\n"
                        f"<b>Konfirmasi:</b>\n{conf}\n\n"
                        f"{entry_info}"
                    ),
                ))

        # ── 3. MA50 Cross (4H only) ───────────────────────────────────
        if tf == "4H" and ma50c and ma50p and pc < ma50p and cc > ma50c:
            if _gate("MA50_CROSS"):
                signals.append(Signal(
                    symbol=symbol, signal_type="MA50_CROSS",
                    timeframe=tf, score=score, entry_price=cc,
                    dyn_sl=ind.get("dyn_sl"),
                    detail=(
                        f"Close <b>{cc:.6f}</b> crossing MA50 <b>{ma50c:.6f}</b>\n\n"
                        f"<b>Konfirmasi:</b>\n{conf}\n\n"
                        f"{entry_info}"
                    ),
                ))

        # ── 4. Pullback Bounce ────────────────────────────────────────
        if cl <= ma200c * 1.01 and cc > ma200c and body > 0.5:
            already_cross = any(
                s.signal_type == "MA200_CROSS" and s.timeframe == tf
                for s in signals if s.symbol == symbol
            )
            if not already_cross and _gate("PULLBACK_BOUNCE"):
                signals.append(Signal(
                    symbol=symbol, signal_type="PULLBACK_BOUNCE",
                    timeframe=tf, score=score, entry_price=cc,
                    dyn_sl=ind.get("dyn_sl"),
                    detail=(
                        f"Low <b>{cl:.6f}</b> sentuh MA200 <b>{ma200c:.6f}</b>\n"
                        f"Bounce <b>{cc:.6f}</b> (+{body:.1f}%)\n\n"
                        f"<b>Konfirmasi:</b>\n{conf}\n\n"
                        f"{entry_info}"
                    ),
                ))

    return symbol, signals
