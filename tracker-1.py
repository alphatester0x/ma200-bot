"""
Tracker — cek profit/SL semua token yang ditracking secara paralel.
"""

import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict

from config import PROFIT_TARGET_PCT, STOPLOSS_PCT, MAX_TRACK_HOURS, MAX_WORKERS
from binance_api import get_current_price
import telegram
from logger import get_logger

log = get_logger("tracker")


def _check_one(key: str, info: dict) -> tuple:
    """
    Cek satu token. Dijalankan di thread pool.
    Returns (key, action, pct, curr)
    action in {"profit","stoploss","expired","ok","skip"}
    """
    symbol     = info["symbol"]
    entry      = info["entry"]
    entry_time = info["time"]

    # Gunakan dynamic SL jika tersimpan, fallback ke flat STOPLOSS_PCT
    dyn_sl     = info.get("dyn_sl")
    sl_pct     = ((dyn_sl - entry) / entry * 100) if dyn_sl else STOPLOSS_PCT

    now   = datetime.utcnow().timestamp()
    hours = (now - entry_time) / 3600

    if hours > MAX_TRACK_HOURS:
        return key, "expired", 0.0, None

    curr = get_current_price(symbol)
    if curr is None:
        return key, "skip", 0.0, None

    pct = (curr - entry) / entry * 100
    if pct >= PROFIT_TARGET_PCT:
        return key, "profit", pct, curr
    if pct <= sl_pct:
        return key, "stoploss", pct, curr
    return key, "ok", pct, curr


def check_tracked(tracked: Dict[str, dict]) -> Dict[str, dict]:
    """
    Cek semua tracked token secara paralel.
    Returns dict yang sudah di-update (token expired/hit target/SL dihapus).
    """
    if not tracked:
        log.info("Tidak ada token yang ditracking.")
        return tracked

    log.info("Cek %d token yang ditracking...", len(tracked))
    updated   = dict(tracked)
    to_delete = []
    messages  = []   # kumpulkan dulu, kirim setelah semua selesai

    workers = min(MAX_WORKERS, len(tracked))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_check_one, k, v): k for k, v in tracked.items()}
        for f in as_completed(futs):
            key, action, pct, curr = f.result()
            info   = tracked[key]
            symbol = info["symbol"]
            entry  = info["entry"]
            tf     = info.get("tf", "")
            st     = info.get("signal", "")

            if action == "expired":
                hours = (datetime.utcnow().timestamp() - info["time"]) / 3600
                log.info("[EXPIRED] %s (%.0fh) — dihapus", symbol, hours)
                to_delete.append(key)

            elif action == "skip":
                log.warning("[SKIP] %s — gagal ambil harga", symbol)

            elif action == "profit":
                log.info("[PROFIT] %s %.1f%%", symbol, pct)
                messages.append((
                    "profit",
                    f"🎯 <b>TARGET +{PROFIT_TARGET_PCT:.0f}% TERCAPAI!</b>\n"
                    f"🪙 <b>{symbol}</b> [{tf}]\n\n"
                    f"📥 Entry    : <b>{entry:.6f}</b>\n"
                    f"📤 Sekarang : <b>{curr:.6f}</b>\n"
                    f"📈 Profit   : <b>+{pct:.1f}%</b> 🚀\n\n"
                    f"⏱ Sinyal: {st}\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ))
                to_delete.append(key)

            elif action == "stoploss":
                log.info("[STOPLOSS] %s %.1f%%", symbol, pct)
                dyn_sl  = info.get("dyn_sl")
                sl_info = f"Dynamic SL: <b>{dyn_sl:.6f}</b>" if dyn_sl else "Flat SL -15%"
                messages.append((
                    "stoploss",
                    f"⚠️ <b>STOP LOSS WARNING</b>\n"
                    f"🪙 <b>{symbol}</b> [{tf}]\n\n"
                    f"📥 Entry    : <b>{entry:.6f}</b>\n"
                    f"📤 Sekarang : <b>{curr:.6f}</b>\n"
                    f"📉 Loss     : <b>{pct:.1f}%</b>\n"
                    f"🛑 {sl_info}\n\n"
                    f"⚠️ Pertimbangkan cut loss!\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ))
                to_delete.append(key)

            else:
                log.info("  %s [%s]: entry=%.6f now=%.6f (%+.1f%%)",
                         symbol, tf, entry, curr, pct)

    # Kirim semua notif setelah threading selesai
    for _, msg in messages:
        telegram.send(msg, delay_after=0.3)

    for k in to_delete:
        updated.pop(k, None)

    log.info("Selesai cek tracker. Hapus: %d | Sisa: %d",
             len(to_delete), len(updated))
    return updated
