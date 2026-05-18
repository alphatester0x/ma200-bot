"""
MA200 Scanner Bot — entry point utama.

Struktur:
  config.py        — konstanta & env vars
  session.py       — shared requests.Session
  logger.py        — logging setup
  gist_storage.py  — load/save tracking ke GitHub Gist
  telegram.py      — kirim pesan Telegram
  binance_api.py   — ambil pairs & OHLCV dari Binance
  indicators.py    — SMA, EMA, RSI
  scanner.py       — logika sinyal per symbol (pakai dataclass Signal)
  tracker.py       — cek profit/SL secara paralel
  ma200_scanner_bot.py — orchestrator (file ini)
"""

import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import MAX_WORKERS, MAX_SIGNALS_PER_SCAN, SIGNAL_META, SIGNAL_SCORE_LABEL, PROFIT_TARGET_PCT
from gist_storage import gist_load, gist_save
from binance_api import get_pairs
from scanner import scan_symbol
from tracker import check_tracked
import telegram
from logger import get_logger

log = get_logger("main")


# ------------------------------------------------------------------ #
#  Format pesan sinyal
# ------------------------------------------------------------------ #

def fmt_signal(sig, index: int, total: int) -> str:
    emoji, label = SIGNAL_META.get(sig.signal_type, ("📊", sig.signal_type))
    score_str    = SIGNAL_SCORE_LABEL.get(sig.score, "")
    return "\n".join([
        f"{emoji} <b>{label}</b> {score_str}",
        f"🪙 <b>{sig.symbol}</b> [{sig.timeframe}] [{index}/{total}]",
        "",
        sig.detail,
        "",
        f"📡 Binance | 🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"🔔 Tracking profit target +{PROFIT_TARGET_PCT:.0f}%",
    ])


# ------------------------------------------------------------------ #
#  Main scan
# ------------------------------------------------------------------ #

def scan_all():
    t0 = time.time()
    log.info("=" * 50)
    log.info("Scanning dimulai...")

    # 1. Load tracking dari Gist
    tracked, gid = gist_load()

    # 2. Cek profit/SL token yang ditracking (paralel)
    tracked = check_tracked(tracked)

    # 3. Ambil & filter pairs dari Binance
    try:
        pairs = get_pairs()
    except Exception as e:
        log.error("Gagal ambil pairs: %s", e)
        telegram.send(f"❌ <b>Bot Error</b>\nGagal ambil pairs dari Binance.")
        return

    log.info("%d pairs | %d workers", len(pairs), MAX_WORKERS)

    # 4. Scan paralel
    all_signals = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(scan_symbol, s): s for s in pairs}
        for f in as_completed(futs):
            sym, sigs = f.result()
            done += 1
            all_signals.extend(sigs)
            if done % 150 == 0:
                log.info("  %d/%d pairs | %.0fs", done, len(pairs), time.time() - t0)

    t_scan = time.time() - t0
    found  = len(all_signals)
    send_n = min(found, MAX_SIGNALS_PER_SCAN)
    log.info("Scan: %.1fs | Sinyal: %d | Kirim: %d", t_scan, found, send_n)

    # 5. Sort (score desc, lalu priority signal type)
    all_signals.sort(key=lambda s: s.sort_key)

    # 6. Kirim & track sinyal teratas
    new_tracked = 0
    for i, sig in enumerate(all_signals[:send_n], start=1):
        msg = fmt_signal(sig, i, send_n)
        telegram.send(msg, delay_after=0.3)
        log.info("✓ %d/%d %s %s [%s] entry=%.6f",
                 i, send_n, sig.symbol, sig.signal_type, sig.timeframe, sig.entry_price)

        key = f"{sig.symbol}_{sig.timeframe}"
        if key not in tracked:
            tracked[key] = {
                "symbol": sig.symbol,
                "entry":  sig.entry_price,
                "time":   datetime.utcnow().timestamp(),
                "signal": sig.signal_type,
                "tf":     sig.timeframe,
            }
            new_tracked += 1

    # 7. Info jika ada sinyal yang tidak dikirim
    if found > MAX_SIGNALS_PER_SCAN:
        telegram.send(
            f"ℹ️ <b>+{found - send_n} sinyal lain</b> tidak dikirim\n"
            f"Total: <b>{found}</b> | Terkirim: <b>{send_n}</b>",
            delay_after=0,
        )

    # 8. Simpan ke Gist
    gist_save(gid, tracked)

    log.info("Tracking: +%d baru | total %d", new_tracked, len(tracked))
    log.info("Selesai: %.1fs", time.time() - t0)


if __name__ == "__main__":
    scan_all()
