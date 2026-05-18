"""
Scanner — logika scan sinyal per symbol.
Menggunakan dataclass Signal supaya struktur tidak rapuh (no magic tuple indices).
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional

from config import (
    VOLUME_MULTIPLIER,
    SIGNAL_META, SIGNAL_SCORE_LABEL, SIGNAL_PRIORITY,
    PROFIT_TARGET_PCT,
)
from binance_api import fetch_ohlcv
from indicators import compute_indicators
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

    @property
    def sort_key(self):
        return (-self.score, SIGNAL_PRIORITY.get(self.signal_type, 9))


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
        ind = compute_indicators(closes, tf)

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
        if vol_r < VOLUME_MULTIPLIER:          # < 1.5x → skip
            continue

        # ── Confirmation filters ──────────────────────────────────────
        is_green = cc > co
        is_gc    = e50 > e200
        conf, score = _build_confirmation(vol_r, is_green, is_gc)

        if score < 2:          # minimal 2/3 filter lolos
            continue

        # ── Signal detection (masing-masing independent) ─────────────

        # 1. MA200 Cross
        if ma200p and pc < ma200p and cc > ma200c:
            signals.append(Signal(
                symbol=symbol, signal_type="MA200_CROSS",
                timeframe=tf, score=score, entry_price=cc,
                detail=(
                    f"Close <b>{cc:.6f}</b> crossing MA200 <b>{ma200c:.6f}</b>\n\n"
                    f"<b>Konfirmasi:</b>\n{conf}"
                ),
            ))

        # 2. RSI Recovery — hanya jika belum ada MA200_CROSS di TF ini
        #    (hindari double-signal di candle yang sama)
        elif rsic and rsip and cc > ma200c and rsip < 35 and rsic >= 35:
            signals.append(Signal(
                symbol=symbol, signal_type="RSI_RECOVERY",
                timeframe=tf, score=score, entry_price=cc,
                detail=(
                    f"Close <b>{cc:.6f}</b> > MA200 <b>{ma200c:.6f}</b>\n"
                    f"RSI: <b>{rsip:.1f}</b> → <b>{rsic:.1f}</b>\n\n"
                    f"<b>Konfirmasi:</b>\n{conf}"
                ),
            ))

        # 3. MA50 Cross (4H only)
        if tf == "4H" and ma50c and ma50p and pc < ma50p and cc > ma50c:
            signals.append(Signal(
                symbol=symbol, signal_type="MA50_CROSS",
                timeframe=tf, score=score, entry_price=cc,
                detail=(
                    f"Close <b>{cc:.6f}</b> crossing MA50 <b>{ma50c:.6f}</b>\n\n"
                    f"<b>Konfirmasi:</b>\n{conf}"
                ),
            ))

        # 4. Pullback Bounce — hanya jika belum ada MA200_CROSS
        #    (keduanya bisa trigger di candle yang sama, ambil yang lebih kuat)
        if cl <= ma200c * 1.01 and cc > ma200c and body > 0.5:
            # Cek apakah MA200_CROSS sudah ada di TF ini
            already_cross = any(
                s.signal_type == "MA200_CROSS" and s.timeframe == tf
                for s in signals
                if s.symbol == symbol
            )
            if not already_cross:
                signals.append(Signal(
                    symbol=symbol, signal_type="PULLBACK_BOUNCE",
                    timeframe=tf, score=score, entry_price=cc,
                    detail=(
                        f"Low <b>{cl:.6f}</b> sentuh MA200 <b>{ma200c:.6f}</b>\n"
                        f"Bounce <b>{cc:.6f}</b> (+{body:.1f}%)\n\n"
                        f"<b>Konfirmasi:</b>\n{conf}"
                    ),
                ))

    return symbol, signals
