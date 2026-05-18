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
MAX_SIGNALS_PER_SCAN  = 15
PROFIT_TARGET_PCT     = 10.0
STOPLOSS_PCT          = -15.0
MAX_TRACK_HOURS       = 72
VOLUME_MULTIPLIER     = 1.5   # volume minimum vs 20-bar average

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
