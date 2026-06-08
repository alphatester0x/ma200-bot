import os

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# ============================================================
# GIST STORAGE
# ============================================================
GIST_TOKEN    = os.environ.get("GIST_TOKEN")
GIST_FILENAME = "ma200_tracked.json"

# ============================================================
# SCANNER
# ============================================================
MAX_WORKERS           = 30
MAX_SIGNALS_PER_SCAN  = 10          # turun dari 15 → quality over quantity
PROFIT_TARGET_PCT     = 10.0
STOPLOSS_PCT          = -15.0
MAX_TRACK_HOURS       = 72
VOLUME_MULTIPLIER     = 2.0         # naik dari 1.5x → 2.0x (lebih selektif)

# ── Quality filters ──────────────────────────────────────────
MIN_RR_RATIO          = 1.5         # sinyal R/R < ini di-DROP (bukan cuma warning)
MIN_VOL_USDT          = 500_000     # minimum volume 24h dalam USDT (filter low-liq)
MAX_CROSS_DIST_PCT    = 3.0         # cross MA200 max 3% di atas MA200 (bukan kejaran)
MIN_SCORE             = 2           # wajib STRONG (3/3), buang MODERATE (2/3)
ATR_PERIOD            = 14
MAX_ATR_PCT           = 15.0        # buang coin yang ATR-nya > 15% dari harga (terlalu volatile)

# ── Entry & Risk management ──────────────────────────────────
SL_BUFFER_PCT         = 1.0
SR_LOOKBACK           = 50

# ============================================================
# BINANCE
# ============================================================
BINANCE_BASE = "https://data-api.binance.vision"

# ============================================================
# SIGNAL METADATA
# ============================================================
SIGNAL_META = {
    "MA200_CROSS":      ("🚀", "Crossing MA200"),
    "RSI_RECOVERY":     ("📈", "RSI Recovery"),
    "MA50_CROSS":       ("⚡", "Crossing MA50 (4H)"),
    "PULLBACK_BOUNCE":  ("🎯", "Pullback Bounce MA200"),
}

SIGNAL_SCORE_LABEL = {3: "🔥 STRONG", 2: "👍 MODERATE"}

SIGNAL_PRIORITY = {
    "MA200_CROSS":     0,
    "PULLBACK_BOUNCE": 1,
    "RSI_RECOVERY":    2,
    "MA50_CROSS":      3,
}

SKIP_SYMBOLS = {
    "USDCUSDT", "BUSDUSDT", "TUSDUSDT", "FDUSDUSDT",
    "PYUSDUSDT", "USDSUSDT", "DAIUSDT", "USDTUSDT", "BVNDUSDT",
}
SKIP_SUBSTRINGS = [
    "UPUSDT", "DOWNUSDT", "BEARUSDT", "BULLUSDT",
    "3LUSDT", "3SUSDT", "5LUSDT", "5SUSDT",
]
