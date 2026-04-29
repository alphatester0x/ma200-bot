import requests
import time
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
#  KONFIGURASI
# ============================================================

TELEGRAM_BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID     = os.environ.get("TELEGRAM_CHAT_ID")
DATA_SOURCE          = None
MAX_WORKERS          = 10
MAX_SIGNALS_PER_SCAN = 15  # batas maksimal notif per scan, hindari flood

# ============================================================
#  TELEGRAM — dengan rate limit handling & retry
# ============================================================

def send_telegram(message, retry=3):
    """
    Kirim pesan dengan:
    - Jeda 1.5 detik antar pesan (aman dari Telegram rate limit)
    - Auto retry + baca retry_after kalau kena 429
    - Print error di log GitHub Actions supaya ketahuan
    """
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}

    for attempt in range(retry):
        try:
            resp = requests.post(url, json=payload, timeout=10)

            if resp.status_code == 200:
                time.sleep(1.5)  # jeda wajib antar pesan
                return True

            elif resp.status_code == 429:
                wait = resp.json().get("parameters", {}).get("retry_after", 10)
                print(f"  [TELEGRAM 429] Rate limit! Tunggu {wait}s...")
                time.sleep(wait + 1)

            else:
                print(f"  [TELEGRAM ERROR] {resp.status_code}: {resp.text[:300]}")
                return False

        except Exception as e:
            print(f"  [TELEGRAM EXCEPTION] attempt {attempt+1}: {e}")
            time.sleep(3)

    print("  [TELEGRAM FAILED] Pesan gagal terkirim setelah 3x percobaan")
    return False

# ============================================================
#  BINANCE API  (data-api.binance.vision)
# ============================================================

BINANCE_BASE = "https://data-api.binance.vision"

def binance_get_pairs():
    resp = requests.get(f"{BINANCE_BASE}/api/v3/exchangeInfo", timeout=20)
    if resp.status_code == 451:
        raise Exception("451 - Binance diblokir dari lokasi ini")
    if resp.status_code != 200:
        raise Exception(f"Binance HTTP {resp.status_code}")
    data = resp.json()
    if "symbols" not in data:
        raise Exception("Binance: key 'symbols' tidak ada")
    return [
        s["symbol"] for s in data["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
        and s["isSpotTradingAllowed"]
    ]

def binance_get_candles(symbol, interval, limit=215):
    resp = requests.get(
        f"{BINANCE_BASE}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10
    )
    if resp.status_code != 200:
        return None
    raw = resp.json()
    if not raw:
        return None
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
    }

# ============================================================
#  BYBIT API  (fallback)
# ============================================================

BYBIT_BASE = "https://api.bybit.com"

def bybit_get_pairs():
    resp = requests.get(
        f"{BYBIT_BASE}/v5/market/instruments-info",
        params={"category": "spot"}, timeout=20
    )
    if resp.status_code != 200:
        raise Exception(f"Bybit HTTP {resp.status_code}")
    items = resp.json().get("result", {}).get("list", [])
    return [
        s["symbol"] for s in items
        if s["symbol"].endswith("USDT") and s.get("status") == "Trading"
    ]

def bybit_get_candles(symbol, interval, limit=215):
    interval_map = {"4h": "240", "1d": "D"}
    resp = requests.get(
        f"{BYBIT_BASE}/v5/market/kline",
        params={"category": "spot", "symbol": symbol,
                "interval": interval_map[interval], "limit": limit},
        timeout=10
    )
    if resp.status_code != 200:
        return None
    raw = resp.json().get("result", {}).get("list", [])
    if not raw:
        return None
    raw = list(reversed(raw))
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
    }

# ============================================================
#  AUTO-SELECT SOURCE
# ============================================================

def get_all_pairs():
    global DATA_SOURCE
    print("  Mencoba Binance (data-api.binance.vision)...")
    try:
        pairs = binance_get_pairs()
        DATA_SOURCE = "binance"
        print(f"  Binance OK — {len(pairs)} pairs")
        return pairs
    except Exception as e:
        print(f"  Binance gagal: {e}")

    print("  Mencoba Bybit...")
    try:
        pairs = bybit_get_pairs()
        DATA_SOURCE = "bybit"
        print(f"  Bybit OK — {len(pairs)} pairs")
        return pairs
    except Exception as e:
        print(f"  Bybit gagal: {e}")

    raise Exception("Semua sumber data gagal!")

def get_candles(symbol, interval, limit=215):
    if DATA_SOURCE == "binance":
        return binance_get_candles(symbol, interval, limit)
    return bybit_get_candles(symbol, interval, limit)

# ============================================================
#  PRE-FILTER
# ============================================================

def pre_filter(pairs):
    skip = [
        "UPUSDT","DOWNUSDT","BEARUSDT","BULLUSDT",
        "USDCUSDT","BUSDUSDT","TUSDUSDT","FDUSDUSDT",
        "PYUSDUSDT","USDSUSDT","DAIUSDT","USDTUSDT",
        "3LUSDT","3SUSDT","5LUSDT","5SUSDT",
    ]
    filtered = [p for p in pairs if not any(k in p for k in skip)]
    print(f"  Pre-filter: {len(pairs)} → {len(filtered)} pairs")
    return filtered

# ============================================================
#  INDIKATOR
# ============================================================

def calc_ma(closes, period):
    if closes is None or len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def calc_rsi(closes, period=14):
    if closes is None or len(closes) < period + 1:
        return None
    deltas   = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    gains    = [d if d > 0 else 0 for d in deltas]
    losses   = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    return 100 - (100 / (1 + avg_gain / avg_loss))

# ============================================================
#  SCAN 1 TOKEN
# ============================================================

def scan_symbol(symbol):
    signals = []
    try:
        c4h = get_candles(symbol, "4h", 215)
        c1d = get_candles(symbol, "1d", 215)
        closes_4h = c4h["close"] if c4h else None
        closes_1d = c1d["close"] if c1d else None

        # Sinyal 1 — MA200 Cross
        for closes, tf in [(closes_4h, "4H"), (closes_1d, "1D")]:
            if closes is None or len(closes) < 202:
                continue
            ma_prev = calc_ma(closes[:-1], 200)
            ma_curr = calc_ma(closes, 200)
            if ma_prev and ma_curr and closes[-2] < ma_prev and closes[-1] > ma_curr:
                signals.append(("MA200_CROSS", tf,
                    f"Close <b>{closes[-1]:.4f}</b> crossing MA200 <b>{ma_curr:.4f}</b>"))

        # Sinyal 2 — RSI Recovery
        for closes, tf in [(closes_4h, "4H"), (closes_1d, "1D")]:
            if closes is None or len(closes) < 215:
                continue
            ma200 = calc_ma(closes, 200)
            if ma200 is None or closes[-1] <= ma200:
                continue
            rsi_curr = calc_rsi(closes)
            rsi_prev = calc_rsi(closes[:-1])
            if rsi_curr and rsi_prev and rsi_prev < 35 and rsi_curr >= 35:
                signals.append(("RSI_RECOVERY", tf,
                    f"Close <b>{closes[-1]:.4f}</b> > MA200 <b>{ma200:.4f}</b>\n"
                    f"RSI: <b>{rsi_prev:.1f}</b> → <b>{rsi_curr:.1f}</b>"))

        # Sinyal 3 — MA50 Cross 4H
        if closes_4h and len(closes_4h) >= 52:
            ma50_prev = calc_ma(closes_4h[:-1], 50)
            ma50_curr = calc_ma(closes_4h, 50)
            if ma50_prev and ma50_curr and closes_4h[-2] < ma50_prev and closes_4h[-1] > ma50_curr:
                signals.append(("MA50_CROSS", "4H",
                    f"Close <b>{closes_4h[-1]:.4f}</b> crossing MA50 <b>{ma50_curr:.4f}</b>"))

        # Sinyal 4 — Pullback Bounce
        for candles, tf in [(c4h, "4H"), (c1d, "1D")]:
            if candles is None or len(candles["close"]) < 202:
                continue
            closes = candles["close"]
            ma200  = calc_ma(closes, 200)
            if ma200 is None:
                continue
            curr_close = closes[-1]
            curr_low   = candles["low"][-1]
            curr_open  = candles["open"][-1]
            body       = (curr_close - curr_open) / curr_open * 100
            if curr_low <= ma200 * 1.01 and curr_close > ma200 and body > 0.5:
                signals.append(("PULLBACK_BOUNCE", tf,
                    f"Low <b>{curr_low:.4f}</b> sentuh MA200 <b>{ma200:.4f}</b>\n"
                    f"Bounce close <b>{curr_close:.4f}</b> (+{body:.1f}%)"))

    except Exception as e:
        print(f"  [SKIP] {symbol}: {e}")

    return symbol, signals

# ============================================================
#  FORMAT PESAN
# ============================================================

SIGNAL_META = {
    "MA200_CROSS":    ("🚀", "Crossing MA200"),
    "RSI_RECOVERY":   ("📈", "RSI Recovery + di atas MA200"),
    "MA50_CROSS":     ("⚡", "Crossing MA50 (4H)"),
    "PULLBACK_BOUNCE":("🎯", "Pullback Bounce ke MA200"),
}

def format_message(symbol, signal_type, tf, detail, rank, total):
    emoji, label = SIGNAL_META.get(signal_type, ("📊", signal_type))
    source = "Binance" if DATA_SOURCE == "binance" else "Bybit"
    return "\n".join([
        f"{emoji} <b>{label}</b>  [{rank}/{total}]",
        f"🪙 <b>{symbol}</b>  [{tf}]",
        "",
        detail,
        "",
        f"📡 {source} | 🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ])

# ============================================================
#  SCAN UTAMA
# ============================================================

def scan_all():
    start = time.time()
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Mulai scanning...")

    try:
        pairs = get_all_pairs()
    except Exception as e:
        print(f"[FATAL] {e}")
        send_telegram(f"❌ <b>Bot Error</b>\n{e}")
        return

    pairs = pre_filter(pairs)
    print(f"Source: {DATA_SOURCE.upper()} | {len(pairs)} pairs | {MAX_WORKERS} threads")

    # Kumpulkan semua sinyal dulu, baru kirim
    all_signals = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scan_symbol, sym): sym for sym in pairs}
        done = 0
        for future in as_completed(futures):
            symbol, signals = future.result()
            done += 1
            for s in signals:
                all_signals.append((symbol,) + s)
            if done % 100 == 0:
                print(f"  Progress scan: {done}/{len(pairs)}")

    elapsed_scan = time.time() - start
    total_found  = len(all_signals)
    total_sent   = min(total_found, MAX_SIGNALS_PER_SCAN)

    print(f"\nScan selesai dalam {elapsed_scan:.1f}s")
    print(f"Sinyal ditemukan: {total_found} | Akan dikirim: {total_sent} (max {MAX_SIGNALS_PER_SCAN})")

    if total_found == 0:
        print("Tidak ada sinyal.")
        return

    # Prioritaskan sinyal: MA200_CROSS & PULLBACK_BOUNCE duluan
    priority = {"MA200_CROSS": 0, "PULLBACK_BOUNCE": 1, "RSI_RECOVERY": 2, "MA50_CROSS": 3}
    all_signals.sort(key=lambda x: priority.get(x[1], 9))

    # Kirim satu per satu dengan rate limit protection
    for i, (symbol, signal_type, tf, detail) in enumerate(all_signals[:MAX_SIGNALS_PER_SCAN]):
        msg = format_message(symbol, signal_type, tf, detail, i+1, total_sent)
        ok  = send_telegram(msg)
        status = "✓" if ok else "✗"
        print(f"  [{status}] {i+1}/{total_sent} {symbol} — {signal_type} [{tf}]")

    # Kalau ada sinyal yang tidak terkirim karena limit, kasih summary
    if total_found > MAX_SIGNALS_PER_SCAN:
        sisa = total_found - MAX_SIGNALS_PER_SCAN
        send_telegram(
            f"ℹ️ <b>+{sisa} sinyal lainnya</b> tidak dikirim untuk menghindari flood.\n"
            f"Total sinyal ditemukan: <b>{total_found}</b>\n"
            f"Scan berikutnya dalam 15 menit."
        )

    total_elapsed = time.time() - start
    print(f"Total waktu: {total_elapsed:.1f}s | Sinyal terkirim: {total_sent}")

# ============================================================
#  ENTRY POINT
# ============================================================

if __name__ == "__main__":
    scan_all()
