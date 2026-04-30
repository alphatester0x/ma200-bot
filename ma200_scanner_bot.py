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
GIST_TOKEN           = os.environ.get("GITHUB_GIST_TOKEN")
GIST_FILENAME        = "ma200_tracked.json"

MAX_WORKERS          = 30
MAX_SIGNALS_PER_SCAN = 15
PROFIT_TARGET_PCT    = 10.0   # notif kalau naik >= 10%
MAX_TRACK_HOURS      = 72     # hapus token dari tracking setelah 72 jam
BINANCE_BASE         = "https://data-api.binance.vision"

SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=30, pool_maxsize=30, max_retries=1
)
SESSION.mount("https://", adapter)
SESSION.headers.update({"Accept-Encoding": "gzip", "Connection": "keep-alive"})

# ============================================================
#  GIST — simpan & load data tracking
# ============================================================

def gist_find_id():
    """Cari Gist ID yang sudah ada dengan filename kita."""
    headers = {"Authorization": f"Bearer {GIST_TOKEN}"}
    resp    = requests.get("https://api.github.com/gists", headers=headers, timeout=10)
    if resp.status_code != 200:
        return None
    for g in resp.json():
        if GIST_FILENAME in g.get("files", {}):
            return g["id"]
    return None

def gist_create():
    """Buat Gist baru untuk tracking."""
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
    print(f"  Gagal buat Gist: {resp.status_code}")
    return None

def gist_load():
    """Load data tracking dari Gist. Return dict."""
    gid = gist_find_id()
    if not gid:
        gid = gist_create()
    if not gid:
        return {}, None

    headers = {"Authorization": f"Bearer {GIST_TOKEN}"}
    resp    = requests.get(f"https://api.github.com/gists/{gid}",
                           headers=headers, timeout=10)
    if resp.status_code != 200:
        return {}, gid

    raw = resp.json()["files"].get(GIST_FILENAME, {}).get("content", "{}")
    try:
        return json.loads(raw), gid
    except Exception:
        return {}, gid

def gist_save(gid, data):
    """Simpan data tracking ke Gist."""
    if not gid:
        return
    headers = {"Authorization": f"Bearer {GIST_TOKEN}"}
    payload = {"files": {GIST_FILENAME: {"content": json.dumps(data, indent=2)}}}
    resp    = requests.patch(f"https://api.github.com/gists/{gid}",
                             headers=headers, json=payload, timeout=10)
    if resp.status_code == 200:
        print(f"  Gist tersimpan ({len(data)} token tracked)")
    else:
        print(f"  Gagal simpan Gist: {resp.status_code}")

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

def fetch(symbol, interval):
    try:
        resp = SESSION.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": 220},
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
    """Ambil harga terkini dari ticker."""
    try:
        resp = SESSION.get(
            f"{BINANCE_BASE}/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=5
        )
        if resp.status_code == 200:
            return float(resp.json()["price"])
    except Exception:
        pass
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

def rsi(c, n=14):
    if len(c) < n+2:
        return None
    d  = [c[i+1]-c[i] for i in range(len(c)-1)]
    ag = sum(x for x in d[-n:] if x > 0) / n
    al = sum(-x for x in d[-n:] if x < 0) / n
    return 100 if al == 0 else 100 - 100/(1+ag/al)

# ============================================================
#  PRICE TRACKER — cek token yang sudah dapat sinyal
# ============================================================

def check_tracked(tracked, gid):
    """
    Cek semua token yang sedang ditracking.
    Kalau naik >= 10% dari entry → notif & hapus dari tracking.
    Kalau sudah > 72 jam → hapus dari tracking.
    """
    if not tracked:
        return tracked

    now         = datetime.utcnow().timestamp()
    to_delete   = []
    updated     = dict(tracked)

    print(f"\n  Cek {len(tracked)} token yang ditracking...")

    for symbol, info in tracked.items():
        entry_price  = info["entry"]
        entry_time   = info["time"]
        signal_type  = info.get("signal", "")
        tf           = info.get("tf", "")
        hours_passed = (now - entry_time) / 3600

        # Expired — lebih dari MAX_TRACK_HOURS jam
        if hours_passed > MAX_TRACK_HOURS:
            print(f"  [EXPIRED] {symbol} — {hours_passed:.0f} jam, dihapus")
            to_delete.append(symbol)
            continue

        curr_price = get_current_price(symbol)
        if curr_price is None:
            continue

        change_pct = (curr_price - entry_price) / entry_price * 100
        print(f"  {symbol}: entry={entry_price:.4f} now={curr_price:.4f} ({change_pct:+.1f}%)")

        # Target tercapai >= 10%
        if change_pct >= PROFIT_TARGET_PCT:
            send_telegram(
                f"🎯 <b>TARGET +{PROFIT_TARGET_PCT:.0f}% TERCAPAI!</b>\n"
                f"🪙 <b>{symbol}</b>  [{tf}]\n\n"
                f"📥 Entry  : <b>{entry_price:.4f}</b>\n"
                f"📤 Sekarang: <b>{curr_price:.4f}</b>\n"
                f"📈 Profit  : <b>+{change_pct:.1f}%</b> 🚀\n\n"
                f"⏱ Sinyal awal: {signal_type}\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            time.sleep(1)
            to_delete.append(symbol)

        # Nyangkut parah >= -15% — notif warning
        elif change_pct <= -15:
            send_telegram(
                f"⚠️ <b>STOP LOSS WARNING</b>\n"
                f"🪙 <b>{symbol}</b>  [{tf}]\n\n"
                f"📥 Entry  : <b>{entry_price:.4f}</b>\n"
                f"📤 Sekarang: <b>{curr_price:.4f}</b>\n"
                f"📉 Loss    : <b>{change_pct:.1f}%</b>\n\n"
                f"⚠️ Pertimbangkan cut loss!\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            time.sleep(1)
            to_delete.append(symbol)

    for sym in to_delete:
        updated.pop(sym, None)

    return updated

# ============================================================
#  SCAN 1 TOKEN
# ============================================================

def scan_symbol(symbol):
    signals = []

    for interval, tf in [("4h","4H"), ("1d","1D")]:
        data = fetch(symbol, interval)
        if data is None:
            continue

        opens, lows, closes, vols = data

        ma200c = sma(closes, 200)
        ma200p = sma_p(closes, 200)
        ma50c  = sma(closes, 50)  if tf == "4H" else None
        ma50p  = sma_p(closes, 50) if tf == "4H" else None
        e50    = ema(closes, 50)
        e200   = ema(closes, 200)
        rsic   = rsi(closes)
        rsip   = rsi(closes[:-1])

        if not ma200c or not e50 or not e200:
            continue

        cc   = closes[-1]
        co   = opens[-1]
        cl   = lows[-1]
        pc   = closes[-2]
        body = (cc - co) / co * 100

        avg_v  = sum(vols[-21:-1]) / 20
        vol_ok = vols[-1] > avg_v
        vol_r  = vols[-1] / avg_v if avg_v > 0 else 0
        grn_ok = cc > co
        gc_ok  = e50 > e200
        score  = vol_ok + grn_ok + gc_ok

        if score < 2:
            continue

        conf = (
            f"{'✅' if vol_ok else '⚠️'} Vol: {vol_r:.1f}x avg\n"
            f"{'✅' if grn_ok else '⚠️'} Candle: {'Hijau' if grn_ok else 'Merah'}\n"
            f"{'✅' if gc_ok else '⚠️'} EMA GC: {'Ya' if gc_ok else 'Belum'}"
        )

        # Sinyal 1: MA200 Cross
        if ma200p and pc < ma200p and cc > ma200c:
            signals.append(("MA200_CROSS", tf, score, cc,
                f"Close <b>{cc:.4f}</b> crossing MA200 <b>{ma200c:.4f}</b>\n\n"
                f"<b>Konfirmasi:</b>\n{conf}"))

        # Sinyal 2: RSI Recovery
        if rsic and rsip and cc > ma200c and rsip < 35 and rsic >= 35:
            signals.append(("RSI_RECOVERY", tf, score, cc,
                f"Close <b>{cc:.4f}</b> > MA200 <b>{ma200c:.4f}</b>\n"
                f"RSI: <b>{rsip:.1f}</b> → <b>{rsic:.1f}</b>\n\n"
                f"<b>Konfirmasi:</b>\n{conf}"))

        # Sinyal 3: MA50 Cross (4H only)
        if tf == "4H" and ma50c and ma50p and pc < ma50p and cc > ma50c:
            signals.append(("MA50_CROSS", tf, score, cc,
                f"Close <b>{cc:.4f}</b> crossing MA50 <b>{ma50c:.4f}</b>\n\n"
                f"<b>Konfirmasi:</b>\n{conf}"))

        # Sinyal 4: Pullback Bounce
        if cl <= ma200c * 1.01 and cc > ma200c and body > 0.5:
            signals.append(("PULLBACK_BOUNCE", tf, score, cc,
                f"Low <b>{cl:.4f}</b> sentuh MA200 <b>{ma200c:.4f}</b>\n"
                f"Bounce <b>{cc:.4f}</b> (+{body:.1f}%)\n\n"
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

    # 1. Load tracking data dari Gist
    tracked, gid = gist_load()
    print(f"  Loaded {len(tracked)} token dari Gist")

    # 2. Cek profit target token yang sudah ditracking
    tracked = check_tracked(tracked, gid)

    # 3. Ambil pairs
    try:
        pairs = get_pairs()
    except Exception as e:
        send_telegram(f"❌ <b>Bot Error</b>\n{e}")
        return

    pairs = pre_filter(pairs)
    print(f"\n{len(pairs)} pairs | {MAX_WORKERS} workers")

    # 4. Scan paralel
    all_sig = []
    done    = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(scan_symbol, s): s for s in pairs}
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

    # 5. Sort & kirim sinyal baru
    all_sig.sort(key=lambda x: (-x[3], PRIO.get(x[2], 9)))

    new_tracked = 0
    for i, (sym, st, tf, sc, entry_price, det) in enumerate(all_sig[:send_n]):
        send_telegram(fmt(sym, st, tf, det, sc, i+1, send_n))
        print(f"  ✓ {i+1}/{send_n} {sym} {st} [{tf}] entry={entry_price:.4f}")
        time.sleep(1)

        # Tambahkan ke tracking kalau belum ada
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
            f"Total: <b>{found}</b> | Terkirim: <b>{send_n}</b>"
        )

    # 6. Simpan tracking ke Gist
    gist_save(gid, tracked)
    print(f"Tracking: +{new_tracked} baru | total {len(tracked)} token")
    print(f"Total waktu: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    scan_all()
