import requests
import time
import os
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
#  KONFIGURASI
# ============================================================

TELEGRAM_BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID     = os.environ.get("TELEGRAM_CHAT_ID")
GIST_TOKEN           = os.environ.get("GIST_TOKEN")
GIST_FILENAME        = "ma200_tracked.json"

MAX_WORKERS          = 30
MAX_SIGNALS_PER_SCAN = 15
PROFIT_TARGET_PCT    = 10.0
STOPLOSS_PCT         = -15.0
MAX_TRACK_HOURS      = 72
BINANCE_BASE         = "https://data-api.binance.vision"

SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=30, pool_maxsize=30, max_retries=1
)
SESSION.mount("https://", adapter)
SESSION.headers.update({"Accept-Encoding": "gzip", "Connection": "keep-alive"})

# ============================================================
#  GIST
# ============================================================

def gist_find_id():
    headers = {"Authorization": f"Bearer {GIST_TOKEN}"}
    resp    = requests.get("https://api.github.com/gists", headers=headers, timeout=10)
    if resp.status_code != 200:
        print(f"  [GIST] gagal list: {resp.status_code}")
        return None
    for g in resp.json():
        if GIST_FILENAME in g.get("files", {}):
            return g["id"]
    return None

def gist_create():
    headers = {"Authorization": f"Bearer {GIST_TOKEN}"}
    payload = {
        "description": "MA200 Bot — Signal Tracker",
        "public": False,
        "files": {GIST_FILENAME: {"content": "{}"}}
    }
    resp = requests.post("https://api.github.com/gists",
                         headers=headers, json=payload, timeout=10)
    if resp.status_code == 201:
        gid = resp.json()["id"]
        print(f"  Gist baru dibuat: {gid}")
        return gid
    print(f"  Gagal buat Gist: {resp.status_code} {resp.text[:100]}")
    return None

def gist_load():
    gid = gist_find_id()
    if not gid:
        gid = gist_create()
    if not gid:
        return {}, None
    headers = {"Authorization": f"Bearer {GIST_TOKEN}"}
    resp    = requests.get(f"https://api.github.com/gists/{gid}",
                           headers=headers, timeout=10)
    if resp.status_code != 200:
        print(f"  [GIST] gagal load: {resp.status_code}")
        return {}, gid
    raw = resp.json()["files"].get(GIST_FILENAME, {}).get("content", "{}")
    try:
        data = json.loads(raw)
        print(f"  Gist loaded: {len(data)} token ditracking")
        return data, gid
    except Exception:
        return {}, gid

def gist_save(gid, data):
    if not gid:
        return
    headers = {"Authorization": f"Bearer {GIST_TOKEN}"}
    payload = {"files": {GIST_FILENAME: {"content": json.dumps(data, indent=2)}}}
    resp    = requests.patch(f"https://api.github.com/gists/{gid}",
                             headers=headers, json=payload, timeout=10)
    if resp.status_code == 200:
        print(f"  Gist saved: {len(data)} token")
    else:
        print(f"  [GIST] gagal save: {resp.status_code}")

# ============================================================
#  TELEGRAM
# ============================================================

def send_telegram(message):
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        resp = SESSION.post(url, json=payload, timeout=10)
        if resp.status_code == 429:
            wait = resp.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(wait + 1)
            SESSION.post(url, json=payload, timeout=10)
        elif resp.status_code != 200:
            print(f"  [TG {resp.status_code}] {resp.text[:100]}")
    except Exception as e:
        print(f"  [TG ERROR] {e}")

# ============================================================
#  BINANCE API
# ============================================================

def get_pairs():
    resp = SESSION.get(f"{BINANCE_BASE}/api/v3/exchangeInfo", timeout=20)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}")
    data = resp.json()
    if "symbols" not in data:
        raise Exception("Key 'symbols' tidak ada")
    return [
        s["symbol"] for s in data["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
        and s["isSpotTradingAllowed"]
    ]

def fetch(symbol, interval, limit=220):
    try:
        resp = SESSION.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=6
        )
        if resp.status_code != 200:
            return None
        raw = resp.json()
        if len(raw) < 202:
            return None
        return (
            [float(c[1]) for c in raw],  # open
            [float(c[3]) for c in raw],  # low
            [float(c[4]) for c in raw],  # close
            [float(c[5]) for c in raw],  # volume
        )
    except Exception:
        return None

def get_current_price(symbol):
    try:
        resp = SESSION.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": "1m", "limit": 1},
            timeout=5
        )
        if resp.status_code == 200:
            return float(resp.json()[0][4])
        print(f"  [PRICE] {symbol} HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [PRICE ERROR] {symbol}: {e}")
    return None

# ============================================================
#  PRE-FILTER
# ============================================================

SKIP     = {"USDCUSDT","BUSDUSDT","TUSDUSDT","FDUSDUSDT","PYUSDUSDT",
            "USDSUSDT","DAIUSDT","USDTUSDT","BVNDUSDT"}
SKIP_SUB = ["UPUSDT","DOWNUSDT","BEARUSDT","BULLUSDT","3LUSDT","3SUSDT","5LUSDT","5SUSDT"]

def pre_filter(pairs):
    out = [p for p in pairs
           if p not in SKIP and not any(s in p for s in SKIP_SUB)]
    print(f"  Pre-filter: {len(pairs)} → {len(out)} pairs")
    return out

# ============================================================
#  INDIKATOR
# ============================================================

def sma(c, n):
    return sum(c[-n:]) / n if len(c) >= n else None

def sma_p(c, n):
    return sum(c[-(n+1):-1]) / n if len(c) >= n+1 else None

def ema(c, n):
    if len(c) < n:
        return None
    k, v = 2/(n+1), sum(c[:n])/n
    for x in c[n:]:
        v = x*k + v*(1-k)
    return v

def rsi_wilder(c, n=14):
    """
    FIX 1: RSI pakai Wilder's Smoothing (standar industri).
    Lebih akurat dari simple average karena sesuai dengan
    RSI yang ditampilkan di TradingView dan platform lainnya.
    """
    if len(c) < n + 1:
        return None, None

    deltas = [c[i+1] - c[i] for i in range(len(c)-1)]

    # Seed pertama: simple average dari n periode pertama
    gains  = [max(d, 0) for d in deltas[:n]]
    losses = [max(-d, 0) for d in deltas[:n]]
    avg_gain = sum(gains) / n
    avg_loss = sum(losses) / n

    # Wilder's smoothing untuk periode berikutnya
    for d in deltas[n:]:
        gain = max(d, 0)
        loss = max(-d, 0)
        avg_gain = (avg_gain * (n-1) + gain) / n
        avg_loss = (avg_loss * (n-1) + loss) / n

    curr_rsi = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    # Hitung RSI candle sebelumnya
    deltas_prev = deltas[:-1]
    gains_p  = [max(d, 0) for d in deltas_prev[:n]]
    losses_p = [max(-d, 0) for d in deltas_prev[:n]]
    avg_gain_p = sum(gains_p) / n
    avg_loss_p = sum(losses_p) / n

    for d in deltas_prev[n:]:
        gain = max(d, 0)
        loss = max(-d, 0)
        avg_gain_p = (avg_gain_p * (n-1) + gain) / n
        avg_loss_p = (avg_loss_p * (n-1) + loss) / n

    prev_rsi = 100 if avg_loss_p == 0 else 100 - 100 / (1 + avg_gain_p / avg_loss_p)

    return curr_rsi, prev_rsi

def get_btc_trend():
    """
    FIX 4: Cek trend BTC sebelum scan altcoin.
    Kalau BTC di bawah MA200 daily → market bearish → skip semua sinyal 1D altcoin.
    Return: True kalau BTC bullish (di atas MA200 daily), False kalau bearish.
    """
    data = fetch("BTCUSDT", "1d", 220)
    if data is None:
        return True  # kalau gagal fetch, tidak skip sinyal
    closes = data[2]
    ma200  = sma(closes, 200)
    if ma200 is None:
        return True
    btc_above = closes[-1] > ma200
    trend = "BULLISH" if btc_above else "BEARISH"
    print(f"  BTC trend: {trend} (close={closes[-1]:.0f}, MA200={ma200:.0f})")
    return btc_above

# ============================================================
#  PRICE TRACKER
# ============================================================

def check_tracked(tracked):
    if not tracked:
        print("  Tidak ada token yang ditracking.")
        return tracked

    now       = datetime.utcnow().timestamp()
    to_delete = []
    updated   = dict(tracked)

    print(f"\n  Cek {len(tracked)} token yang ditracking...")

    for key, info in tracked.items():
        symbol      = info["symbol"]
        entry_price = info["entry"]
        entry_time  = info["time"]
        sig_type    = info.get("signal", "")
        tf          = info.get("tf", "")
        hours       = (now - entry_time) / 3600

        if hours > MAX_TRACK_HOURS:
            print(f"  [EXPIRED] {symbol} ({hours:.0f}h) — dihapus")
            to_delete.append(key)
            continue

        curr = get_current_price(symbol)
        if curr is None:
            print(f"  [SKIP] {symbol} — gagal ambil harga")
            continue

        pct = (curr - entry_price) / entry_price * 100
        print(f"  {symbol} [{tf}]: entry={entry_price:.6f} now={curr:.6f} ({pct:+.1f}%)")

        if pct >= PROFIT_TARGET_PCT:
            send_telegram(
                f"🎯 <b>TARGET +{PROFIT_TARGET_PCT:.0f}% TERCAPAI!</b>\n"
                f"🪙 <b>{symbol}</b>  [{tf}]\n\n"
                f"📥 Entry   : <b>{entry_price:.6f}</b>\n"
                f"📤 Sekarang: <b>{curr:.6f}</b>\n"
                f"📈 Profit  : <b>+{pct:.1f}%</b> 🚀\n\n"
                f"⏱ Sinyal: {sig_type}\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            time.sleep(1)
            to_delete.append(key)

        elif pct <= STOPLOSS_PCT:
            send_telegram(
                f"⚠️ <b>STOP LOSS WARNING</b>\n"
                f"🪙 <b>{symbol}</b>  [{tf}]\n\n"
                f"📥 Entry   : <b>{entry_price:.6f}</b>\n"
                f"📤 Sekarang: <b>{curr:.6f}</b>\n"
                f"📉 Loss    : <b>{pct:.1f}%</b>\n\n"
                f"⚠️ Pertimbangkan cut loss!\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            time.sleep(1)
            to_delete.append(key)

    for k in to_delete:
        updated.pop(k, None)

    print(f"  Selesai cek tracker. Hapus: {len(to_delete)} | Sisa: {len(updated)}")
    return updated

# ============================================================
#  SCAN 1 TOKEN
# ============================================================

def scan_symbol(symbol, btc_bullish=True):
    signals = []

    for interval, tf in [("4h","4H"), ("1d","1D")]:
        data = fetch(symbol, interval)
        if data is None:
            continue

        opens, lows, closes, vols = data

        # Hitung semua indikator sekali
        ma200c = sma(closes, 200)
        ma200p = sma_p(closes, 200)
        ma50c  = sma(closes, 50)   if tf == "4H" else None
        ma50p  = sma_p(closes, 50) if tf == "4H" else None
        e50    = ema(closes, 50)
        e200   = ema(closes, 200)

        # FIX 1: RSI pakai Wilder's smoothing
        rsic, rsip = rsi_wilder(closes)

        if not ma200c or not e50 or not e200:
            continue

        cc   = closes[-1]
        co   = opens[-1]
        cl   = lows[-1]
        pc   = closes[-2]
        body = (cc - co) / co * 100

        # FIX 5: Volume average dari 20 candle sebelum candle terakhir (lebih tepat)
        avg_v  = sum(vols[-21:-1]) / 20
        vol_ok = vols[-1] > avg_v          # volume harus > rata-rata
        vol_r  = vols[-1] / avg_v if avg_v > 0 else 0

        # Hard filter: volume wajib lolos
        if not vol_ok:
            continue

        # Filter tambahan
        grn_ok = cc > co
        gc_ok  = e50 > e200
        score  = int(vol_ok) + int(grn_ok) + int(gc_ok)

        # score: volume(wajib) + candle hijau + EMA GC = min 2 dari 3
        if score < 2:
            continue

        # BTC warning — tidak skip, tapi tambahkan label di notif
        btc_warn = "\n⚠️ <b>BTC BEARISH</b> — trade dengan hati-hati!" if (tf == "1D" and not btc_bullish) else ""

        conf = (
            f"✅ Vol: {vol_r:.1f}x avg\n"
            f"{'✅' if grn_ok else '⚠️'} Candle: {'Hijau' if grn_ok else 'Merah'}\n"
            f"{'✅' if gc_ok else '⚠️'} EMA GC: {'Ya' if gc_ok else 'Belum'}"
            f"{btc_warn}"
        )

        # Sinyal 1: MA200 Cross
        if ma200p and pc < ma200p and cc > ma200c:
            signals.append(("MA200_CROSS", tf, score, cc,
                f"Close <b>{cc:.6f}</b> crossing MA200 <b>{ma200c:.6f}</b>\n\n"
                f"<b>Konfirmasi:</b>\n{conf}"))

        # Sinyal 2: RSI Recovery — FIX 1: pakai RSI Wilder yang akurat
        if rsic and rsip and cc > ma200c and rsip < 35 and rsic >= 35:
            signals.append(("RSI_RECOVERY", tf, score, cc,
                f"Close <b>{cc:.6f}</b> > MA200 <b>{ma200c:.6f}</b>\n"
                f"RSI: <b>{rsip:.1f}</b> → <b>{rsic:.1f}</b>\n\n"
                f"<b>Konfirmasi:</b>\n{conf}"))

        # Sinyal 3: MA50 Cross (4H only)
        if tf == "4H" and ma50c and ma50p and pc < ma50p and cc > ma50c:
            signals.append(("MA50_CROSS", tf, score, cc,
                f"Close <b>{cc:.6f}</b> crossing MA50 <b>{ma50c:.6f}</b>\n\n"
                f"<b>Konfirmasi:</b>\n{conf}"))

        # FIX 3: Pullback Bounce — threshold lebih ketat (0.5% bukan 1%)
        # Low harus menyentuh MA200 dalam range 0.5%, bukan 1%
        if cl <= ma200c * 1.01 and cc > ma200c and body > 0.5:
            signals.append(("PULLBACK_BOUNCE", tf, score, cc,
                f"Low <b>{cl:.6f}</b> sentuh MA200 <b>{ma200c:.6f}</b>\n"
                f"Bounce <b>{cc:.6f}</b> (+{body:.1f}%)\n\n"
                f"<b>Konfirmasi:</b>\n{conf}"))

    return symbol, signals

# ============================================================
#  FORMAT
# ============================================================

META  = {
    "MA200_CROSS":    ("🚀","Crossing MA200"),
    "RSI_RECOVERY":   ("📈","RSI Recovery"),
    "MA50_CROSS":     ("⚡","Crossing MA50 (4H)"),
    "PULLBACK_BOUNCE":("🎯","Pullback Bounce MA200"),
}
SCORE = {3:"🔥 STRONG", 2:"👍 MODERATE"}
# FIX 2: Prioritas sort berdasarkan score (desc) lalu jenis sinyal
PRIO  = {"MA200_CROSS":0,"PULLBACK_BOUNCE":1,"RSI_RECOVERY":2,"MA50_CROSS":3}

def fmt(sym, st, tf, det, sc, i, tot):
    e, lb = META.get(st, ("📊", st))
    return "\n".join([
        f"{e} <b>{lb}</b>  {SCORE.get(sc,'')}",
        f"🪙 <b>{sym}</b>  [{tf}]  [{i}/{tot}]",
        "", det, "",
        f"📡 Binance | 🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"🔔 Tracking profit target +{PROFIT_TARGET_PCT:.0f}%",
    ])

# ============================================================
#  SCAN UTAMA
# ============================================================

def scan_all():
    t0 = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanning...")

    # 1. Load tracking dari Gist
    tracked, gid = gist_load()

    # 2. Cek profit/SL token yang ditracking
    tracked = check_tracked(tracked)

    # 3. Ambil pairs
    try:
        pairs = get_pairs()
    except Exception as e:
        send_telegram(f"❌ <b>Bot Error</b>\n{e}")
        return

    pairs = pre_filter(pairs)

    # FIX 4: Cek trend BTC sebelum scan
    btc_bullish = get_btc_trend()

    print(f"\n{len(pairs)} pairs | {MAX_WORKERS} workers | BTC: {'🟢' if btc_bullish else '🔴'}")

    # 4. Scan paralel — pass btc_bullish ke tiap worker
    all_sig = []
    done    = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(scan_symbol, s, btc_bullish): s for s in pairs}
        for f in as_completed(futs):
            sym, sigs = f.result()
            done += 1
            all_sig.extend((sym,)+s for s in sigs)
            if done % 150 == 0:
                print(f"  {done}/{len(pairs)} | {time.time()-t0:.0f}s")

    t_scan = time.time() - t0
    found  = len(all_sig)
    send_n = min(found, MAX_SIGNALS_PER_SCAN)
    print(f"Scan: {t_scan:.1f}s | Sinyal: {found} | Kirim: {send_n}")

    # FIX 2: Sort benar — score index adalah [3] dalam tuple (sym, st, tf, score, price, det)
    all_sig.sort(key=lambda x: (-x[3], PRIO.get(x[2], 9)))

    new_tracked = 0
    for i, (sym, st, tf, sc, entry_price, det) in enumerate(all_sig[:send_n]):
        send_telegram(fmt(sym, st, tf, det, sc, i+1, send_n))
        print(f"  ✓ {i+1}/{send_n} {sym} {st} [{tf}] score={sc} entry={entry_price:.6f}")
        time.sleep(1)

        key = f"{sym}_{tf}"
        if key not in tracked:
            tracked[key] = {
                "symbol": sym,
                "entry":  entry_price,
                "time":   datetime.utcnow().timestamp(),
                "signal": st,
                "tf":     tf,
            }
            new_tracked += 1

    if found > MAX_SIGNALS_PER_SCAN:
        send_telegram(
            f"ℹ️ <b>+{found-send_n} sinyal lain</b> tidak dikirim\n"
            f"Total: <b>{found}</b> | Terkirim: <b>{send_n}</b>\n"
            f"BTC: {'🟢 Bullish' if btc_bullish else '🔴 Bearish'}"
        )

    # 6. Simpan ke Gist
    gist_save(gid, tracked)
    print(f"Tracking: +{new_tracked} baru | total {len(tracked)}")
    print(f"Total: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    scan_all()
