import requests
import time
import os
from datetime import datetime

# ============================================================
#  KONFIGURASI
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# ============================================================
#  FUNGSI HELPER
# ============================================================

BINANCE_BASE = "https://data-api.binance.vision"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

def get_all_usdt_pairs():
    """Ambil semua USDT pairs dengan retry otomatis."""
    url = f"{BINANCE_BASE}/api/v3/exchangeInfo"
    for attempt in range(3):  # coba 3x kalau gagal
        try:
            resp = requests.get(url, timeout=30)
            print(f"  exchangeInfo status: {resp.status_code}")
            if resp.status_code != 200:
                print(f"  Response: {resp.text[:200]}")
                time.sleep(5)
                continue
            data = resp.json()
            if "symbols" not in data:
                print(f"  Response keys: {list(data.keys())}")
                print(f"  Response: {str(data)[:300]}")
                time.sleep(5)
                continue
            pairs = [
                s["symbol"]
                for s in data["symbols"]
                if s["quoteAsset"] == "USDT"
                and s["status"] == "TRADING"
                and s["isSpotTradingAllowed"]
            ]
            return pairs
        except Exception as e:
            print(f"  Attempt {attempt+1} gagal: {e}")
            time.sleep(5)
    raise Exception("Gagal ambil pairs setelah 3x percobaan")

def get_closes(symbol, interval, limit=215):
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        return None
    return [float(c[4]) for c in resp.json()]

def get_candles_full(symbol, interval, limit=215):
    """Ambil candle lengkap: open, high, low, close."""
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        return None
    raw = resp.json()
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
    }

def calc_ma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def calc_rsi(closes, period=14):
    """Hitung RSI sederhana."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ============================================================
#  4 JENIS SINYAL
# ============================================================

def check_signal_1_ma200_cross(closes_4h, closes_1d):
    """Sinyal 1: Candle baru crossing ke atas MA200 di 4H atau 1D."""
    results = []
    for closes, tf in [(closes_4h, "4H"), (closes_1d, "1D")]:
        if closes is None or len(closes) < 202:
            continue
        ma_prev = calc_ma(closes[:-1], 200)
        ma_curr = calc_ma(closes, 200)
        if ma_prev and ma_curr:
            if closes[-2] < ma_prev and closes[-1] > ma_curr:
                results.append({
                    "tf": tf,
                    "close": closes[-1],
                    "ma200": ma_curr,
                    "detail": f"Close <b>{closes[-1]:.4f}</b> baru crossing MA200 <b>{ma_curr:.4f}</b>"
                })
    return results

def check_signal_2_rsi_recovery(closes_4h, closes_1d):
    """Sinyal 2: Close di atas MA200 + RSI baru naik dari oversold (<35)."""
    results = []
    for closes, tf in [(closes_4h, "4H"), (closes_1d, "1D")]:
        if closes is None or len(closes) < 215:
            continue
        ma200 = calc_ma(closes, 200)
        if ma200 is None or closes[-1] <= ma200:
            continue
        rsi_curr = calc_rsi(closes, 14)
        rsi_prev = calc_rsi(closes[:-1], 14)
        if rsi_curr and rsi_prev:
            if rsi_prev < 35 and rsi_curr >= 35:
                results.append({
                    "tf": tf,
                    "close": closes[-1],
                    "ma200": ma200,
                    "rsi": rsi_curr,
                    "detail": (
                        f"Close <b>{closes[-1]:.4f}</b> > MA200 <b>{ma200:.4f}</b>\n"
                        f"📊 RSI recovery: <b>{rsi_prev:.1f}</b> → <b>{rsi_curr:.1f}</b>"
                    )
                })
    return results

def check_signal_3_ma50_cross_4h(closes_4h):
    """Sinyal 3: Close baru crossing ke atas MA50 di 4H."""
    if closes_4h is None or len(closes_4h) < 52:
        return []
    ma50_prev = calc_ma(closes_4h[:-1], 50)
    ma50_curr = calc_ma(closes_4h, 50)
    if ma50_prev and ma50_curr:
        if closes_4h[-2] < ma50_prev and closes_4h[-1] > ma50_curr:
            return [{
                "tf": "4H",
                "close": closes_4h[-1],
                "ma50": ma50_curr,
                "detail": f"Close <b>{closes_4h[-1]:.4f}</b> baru crossing MA50 <b>{ma50_curr:.4f}</b>"
            }]
    return []

def check_signal_4_pullback_bounce(candles_4h, candles_1d):
    """
    Sinyal 4: Pullback ke MA200 lalu bounce.
    Low menyentuh MA200 (dalam 1%), tapi close di atas MA200
    dengan body candle bullish > 0.5%.
    """
    results = []
    for candles, tf in [(candles_4h, "4H"), (candles_1d, "1D")]:
        if candles is None or len(candles["close"]) < 202:
            continue
        closes = candles["close"]
        lows   = candles["low"]
        opens  = candles["open"]
        ma200  = calc_ma(closes, 200)
        if ma200 is None:
            continue
        curr_close = closes[-1]
        curr_low   = lows[-1]
        curr_open  = opens[-1]

        touched_ma    = curr_low <= ma200 * 1.01
        close_above   = curr_close > ma200
        candle_body   = (curr_close - curr_open) / curr_open * 100
        strong_bounce = candle_body > 0.5

        if touched_ma and close_above and strong_bounce:
            results.append({
                "tf": tf,
                "close": curr_close,
                "low": curr_low,
                "ma200": ma200,
                "body_pct": candle_body,
                "detail": (
                    f"Low <b>{curr_low:.4f}</b> menyentuh MA200 <b>{ma200:.4f}</b>\n"
                    f"💪 Bounce close <b>{curr_close:.4f}</b> (+{candle_body:.1f}%)"
                )
            })
    return results

# ============================================================
#  FORMAT PESAN TELEGRAM
# ============================================================

SIGNAL_META = {
    "MA200_CROSS":    ("🚀", "Crossing MA200"),
    "RSI_RECOVERY":   ("📈", "RSI Recovery + di atas MA200"),
    "MA50_CROSS":     ("⚡", "Crossing MA50 (4H)"),
    "PULLBACK_BOUNCE":("🎯", "Pullback Bounce ke MA200"),
}

def format_message(symbol, signal_type, data):
    emoji, label = SIGNAL_META.get(signal_type, ("📊", signal_type))
    lines = [
        f"{emoji} <b>{label}</b>",
        f"🪙 <b>{symbol}</b>  [{data.get('tf','')}]",
        f"",
        data.get("detail", ""),
        f"",
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    return "\n".join(lines)

# ============================================================
#  SCAN UTAMA
# ============================================================

def scan_all():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Mulai scanning...")

    try:
        pairs = get_all_usdt_pairs()
    except Exception as e:
        print(f"[ERROR] Gagal ambil pairs: {e}")
        return

    print(f"Total pairs: {len(pairs)}")
    total_signals = 0

    for i, symbol in enumerate(pairs):
        try:
            closes_4h  = get_closes(symbol, "4h")
            closes_1d  = get_closes(symbol, "1d")
            candles_4h = get_candles_full(symbol, "4h")
            candles_1d = get_candles_full(symbol, "1d")

            sinyal = [
                ("MA200_CROSS",    check_signal_1_ma200_cross(closes_4h, closes_1d)),
                ("RSI_RECOVERY",   check_signal_2_rsi_recovery(closes_4h, closes_1d)),
                ("MA50_CROSS",     check_signal_3_ma50_cross_4h(closes_4h)),
                ("PULLBACK_BOUNCE",check_signal_4_pullback_bounce(candles_4h, candles_1d)),
            ]

            for signal_type, results in sinyal:
                for data in results:
                    msg = format_message(symbol, signal_type, data)
                    send_telegram(msg)
                    total_signals += 1
                    print(f"  [SIGNAL] {symbol} — {signal_type} [{data.get('tf','')}]")
                    time.sleep(0.3)  # jeda antar notif

            # Rate limit protection
            if (i + 1) % 50 == 0:
                print(f"  Progress: {i+1}/{len(pairs)}")
                time.sleep(1)
            else:
                time.sleep(0.15)

        except Exception as e:
            print(f"  [SKIP] {symbol}: {e}")
            continue

    if total_signals == 0:
        print("  Tidak ada sinyal ditemukan.")
    else:
        print(f"  Total sinyal terkirim: {total_signals}")
    print("Scan selesai.")

# ============================================================
#  ENTRY POINT
# ============================================================

if __name__ == "__main__":
    scan_all()
