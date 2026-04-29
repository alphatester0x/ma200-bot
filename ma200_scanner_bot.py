import requests
import time
from datetime import datetime

# ============================================================
#  KONFIGURASI - ISI BAGIAN INI DULU SEBELUM JALANKAN BOT
# ============================================================

TELEGRAM_BOT_TOKEN = "8753880668:AAG8fXPJD-Zp3f-BFjoQHgEjSZPc6aAdY2U"   # Contoh: 7123456789:AAFxxxxxx
TELEGRAM_CHAT_ID   = "243258418"               # Contoh: 123456789

# Berapa menit sekali bot scan ulang semua token
SCAN_INTERVAL_MINUTES = 15

# ============================================================
#  FUNGSI UTAMA
# ============================================================

BINANCE_BASE = "https://api.binance.com"

def send_telegram(message):
    """Kirim pesan ke Telegram."""
    url = f"https://api.telegram.org/bot8753880668:AAG8fXPJD-Zp3f-BFjoQHgEjSZPc6aAdY2U/sendMessage"
    payload = {
        "chat_id": 243258418,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

def get_all_usdt_pairs():
    """Ambil semua USDT pairs yang aktif dari Binance."""
    url = f"{BINANCE_BASE}/api/v3/exchangeInfo"
    resp = requests.get(url, timeout=15)
    data = resp.json()
    pairs = [
        s["symbol"]
        for s in data["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
        and s["isSpotTradingAllowed"]
    ]
    return pairs

def get_closes(symbol, interval, limit=210):
    """
    Ambil data candle dari Binance.
    interval: '4h' atau '1d'
    limit   : jumlah candle (butuh minimal 200 untuk MA200)
    """
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        return None
    candles = resp.json()
    closes = [float(c[4]) for c in candles]  # indeks 4 = close price
    return closes

def calculate_ma(closes, period=200):
    """Hitung Moving Average sederhana."""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def check_cross_above_ma200(closes):
    """
    Cek apakah candle terakhir BARU SAJA closing di atas MA200.
    Kondisi:
      - Candle sebelumnya (closes[-2]) berada DI BAWAH MA200
      - Candle terakhir   (closes[-1]) berada DI ATAS  MA200
    """
    if len(closes) < 202:
        return False, None, None

    # MA200 dihitung dari candle sebelum candle terakhir
    ma200_prev = calculate_ma(closes[:-1])
    ma200_curr = calculate_ma(closes)

    if ma200_prev is None or ma200_curr is None:
        return False, None, None

    prev_close = closes[-2]
    curr_close = closes[-1]

    crossed = (prev_close < ma200_prev) and (curr_close > ma200_curr)
    return crossed, curr_close, ma200_curr

def scan_all():
    """Scan semua USDT pairs untuk sinyal MA200 cross."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Mulai scanning...")

    try:
        pairs = get_all_usdt_pairs()
    except Exception as e:
        print(f"[ERROR] Gagal ambil pairs: {e}")
        return

    print(f"Total pairs ditemukan: {len(pairs)}")
    signals = []

    for i, symbol in enumerate(pairs):
        try:
            # --- Cek 4H ---
            closes_4h = get_closes(symbol, "4h", limit=210)
            signal_4h, close_4h, ma_4h = False, None, None
            if closes_4h:
                signal_4h, close_4h, ma_4h = check_cross_above_ma200(closes_4h)

            # --- Cek 1D ---
            closes_1d = get_closes(symbol, "1d", limit=210)
            signal_1d, close_1d, ma_1d = False, None, None
            if closes_1d:
                signal_1d, close_1d, ma_1d = check_cross_above_ma200(closes_1d)

            if signal_4h or signal_1d:
                signals.append({
                    "symbol": symbol,
                    "signal_4h": signal_4h,
                    "close_4h": close_4h,
                    "ma_4h": ma_4h,
                    "signal_1d": signal_1d,
                    "close_1d": close_1d,
                    "ma_1d": ma_1d,
                })

            # Jeda kecil biar tidak kena rate limit Binance
            if (i + 1) % 50 == 0:
                print(f"  Progress: {i+1}/{len(pairs)}")
                time.sleep(1)
            else:
                time.sleep(0.1)

        except Exception as e:
            print(f"  [SKIP] {symbol}: {e}")
            continue

    # --- Kirim notif ke Telegram ---
    if signals:
        for s in signals:
            lines = [f"🚨 <b>SINYAL MA200</b> — {s['symbol']}"]

            if s["signal_4h"]:
                lines.append(
                    f"📊 <b>4H Cross ✅</b>\n"
                    f"   Close : {s['close_4h']:.6f}\n"
                    f"   MA200 : {s['ma_4h']:.6f}"
                )
            if s["signal_1d"]:
                lines.append(
                    f"📅 <b>1D Cross ✅</b>\n"
                    f"   Close : {s['close_1d']:.6f}\n"
                    f"   MA200 : {s['ma_1d']:.6f}"
                )

            lines.append(f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            msg = "\n".join(lines)

            send_telegram(msg)
            print(f"  [SIGNAL] {s['symbol']} — notif terkirim!")
    else:
        print("  Tidak ada sinyal baru ditemukan.")

    print(f"Scan selesai. Berikutnya dalam {SCAN_INTERVAL_MINUTES} menit.")

# ============================================================
#  JALANKAN BOT
# ============================================================

if __name__ == "__main__":
    send_telegram(
        "🤖 <b>MA200 Scanner Bot aktif!</b>\n"
        f"Scan setiap {SCAN_INTERVAL_MINUTES} menit.\n"
        "Memantau semua USDT pairs di Binance.\n"
        "Timeframe: 4H dan 1D"
    )

    while True:
        scan_all()
        time.sleep(SCAN_INTERVAL_MINUTES * 60)
