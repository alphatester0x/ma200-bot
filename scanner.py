"""
Scanner — logika scan sinyal per symbol.
Menggunakan dataclass Signal supaya struktur tidak rapuh (no magic tuple indices).
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional

from config import (
    VOLUME_MULTIPLIER,
    SIGNAL_META, SIGNAL_SCORE_LABEL, SIGNAL_PRIORITY,
    PROFIT_TARGET_PCT, MIN_RR_RATIO,
)
from binance_api import fetch_ohlcv
from indicators import compute_indicators, calc_rr
from logger import get_logger

log = get_logger("scanner")


# ------------------------------------------------------------------ #
#  Data structure
# ------------------------------------------------------------------ #

@dataclass
class Signal:
    symbol:      str
    signal_type: str
    timeframe:   str
    score:       int
    entry_price: float
    detail:      str
    dyn_sl:      Optional[float] = None   # dynamic SL harga, untuk disimpan ke tracker

    @property
    def sort_key(self):
        return (-self.score, SIGNAL_PRIORITY.get(self.signal_type, 9))


# ------------------------------------------------------------------ #
#  Entry info block
# ------------------------------------------------------------------ #

def _build_entry_info(
    entry: float,
    ind: dict,
    profit_target_pct: float,
) -> str:
    """
    Bangun blok teks Entry Guide untuk pesan Telegram.
    Berisi: entry zone, support, resistance, dynamic SL, R/R ratio.
    """
    target    = entry * (1 + profit_target_pct / 100)
    dyn_sl    = ind.get("dyn_sl")
    support   = ind.get("support")
    resistance= ind.get("resistance")
    entry_low = ind.get("entry_low", entry)
    entry_high= ind.get("entry_high", entry)
    vol_label = ind.get("vol_label", "N/A")

    # Gunakan dynamic SL jika ada, fallback ke flat SL
    sl_price  = dyn_sl if dyn_sl else entry * (1 + (-15.0) / 100)
    rr        = calc_rr(entry, target, sl_price)
    rr_warn   = f" ⚠️ R/R rendah!" if rr and rr < MIN_RR_RATIO else ""
    rr_str    = f"{rr:.2f}{rr_warn}" if rr else "N/A"

    lines = [
        "─────────────────────────",
        "📊 <b>Entry Guide</b>",
        f"🎯 Entry Zone : <b>{entry_low:.6f} – {entry_high:.6f}</b>",
        f"🎯 Target     : <b>{target:.6f}</b> (+{profit_target_pct:.0f}%)",
        f"🛑 Stop Loss  : <b>{sl_price:.6f}</b>"
        + (" (dynamic)" if dyn_sl else " (flat -15%)"),
        f"📐 R/R Ratio  : <b>{rr_str}</b>",
        "─────────────────────────",
        "📈 <b>Level Kunci</b>",
    ]

    if support:
        lines.append(f"🟢 Support    : <b>{support:.6f}</b>")
    if resistance:
        lines.append(f"🔴 Resistance : <b>{resistance:.6f}</b>")

    lines.append(f"📦 Volume     : <b>{vol_label}</b>")

    return "\n".join(lines)


# ------------------------------------------------------------------ #
#  Per-symbol scan
# ------------------------------------------------------------------ #

def _build_confirmation(vol_ratio: float, is_green: bool, is_gc: bool) -> Tuple[str, int]:
    """Buat teks konfirmasi dan hitung score."""
    vol_ok   = vol_ratio >= VOLUME_MULTIPLIER
    grn_ok   = is_green
    gc_ok    = is_gc
    score    = sum([vol_ok, grn_ok, gc_ok])

    conf = (
        f"{'✅' if vol_ok else '⚠️'} Vol: {vol_ratio:.1f}x avg\n"
        f"{'✅' if grn_ok else '⚠️'} Candle: {'Hijau' if grn_ok else 'Merah'}\n"
        f"{'✅' if gc_ok  else '⚠️'} EMA GC: {'Ya' if gc_ok else 'Belum'}"
    )
    return conf, score


def scan_symbol(symbol: str) -> Tuple[str, List[Signal]]:
    signals: List[Signal] = []

    for interval, tf in [("4h", "4H"), ("1d", "1D")]:
        data = fetch_ohlcv(symbol, interval)
        if data is None:
            continue

        opens, lows, closes, vols = data

        # Highs tidak ada di fetch, derive dari opens/closes
        highs = [max(o, c) for o, c in zip(opens, closes)]

        # Pass highs, lows, vols untuk S/R + volume profile
        ind = compute_indicators(closes, tf, highs=highs, lows=lows, volumes=vols)

        ma200c = ind["ma200c"]
        ma200p = ind["ma200p"]
        e50    = ind["e50"]
        e200   = ind["e200"]
        rsic   = ind["rsic"]
        rsip   = ind["rsip"]
        ma50c  = ind["ma50c"]
        ma50p  = ind["ma50p"]

        if not ma200c or not e50 or not e200:
            continue

        cc   = closes[-1]
        co   = opens[-1]
        cl   = lows[-1]
        pc   = closes[-2]
        body = (cc - co) / co * 100

        # ── Volume filter (HARD, wajib lolos dulu) ───────────────────
        avg_v   = sum(vols[-21:-1]) / 20
        vol_r   = vols[-1] / avg_v if avg_v > 0 else 0
        if vol_r < VOLUME_MULTIPLIER:
            continue

        # ── Confirmation filters ──────────────────────────────────────
        is_green = cc > co
        is_gc    = e50 > e200
        conf, score = _build_confirmation(vol_r, is_green, is_gc)

        if score < 2:
            continue

        # ── Entry guide block (shared untuk semua sinyal di TF ini) ──
        entry_info = _build_entry_info(cc, ind, PROFIT_TARGET_PCT)

        # ── Signal detection ──────────────────────────────────────────

        # 1. MA200 Cross
        if ma200p and pc < ma200p and cc > ma200c:
            signals.append(Signal(
                symbol=symbol, signal_type="MA200_CROSS",
                timeframe=tf, score=score, entry_price=cc,
                dyn_sl=ind.get("dyn_sl"),
                detail=(
                    f"Close <b>{cc:.6f}</b> crossing MA200 <b>{ma200c:.6f}</b>\n\n"
                    f"<b>Konfirmasi:</b>\n{conf}\n\n"
                    f"{entry_info}"
                ),
            ))

        # 2. RSI Recovery
        elif rsic and rsip and cc > ma200c and rsip < 35 and rsic >= 35:
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

        # 3. MA50 Cross (4H only)
        if tf == "4H" and ma50c and ma50p and pc < ma50p and cc > ma50c:
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

        # 4. Pullback Bounce
        if cl <= ma200c * 1.01 and cc > ma200c and body > 0.5:
            already_cross = any(
                s.signal_type == "MA200_CROSS" and s.timeframe == tf
                for s in signals
                if s.symbol == symbol
            )
            if not already_cross:
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
