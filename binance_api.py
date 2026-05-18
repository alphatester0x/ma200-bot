"""
Binance API wrapper — ambil pairs dan OHLCV data.
"""

from typing import Optional, Tuple, List
from session import SESSION
from config import BINANCE_BASE, SKIP_SYMBOLS, SKIP_SUBSTRINGS
from logger import get_logger

log = get_logger("binance")

# ------------------------------------------------------------------ #
#  Types
# ------------------------------------------------------------------ #
OHLCVData = Tuple[
    List[float],  # opens
    List[float],  # lows
    List[float],  # closes
    List[float],  # volumes
]


# ------------------------------------------------------------------ #
#  Public functions
# ------------------------------------------------------------------ #

def get_pairs() -> List[str]:
    resp = SESSION.get(f"{BINANCE_BASE}/api/v3/exchangeInfo", timeout=20)
    if resp.status_code != 200:
        raise Exception(f"exchangeInfo HTTP {resp.status_code}")
    data = resp.json()
    if "symbols" not in data:
        raise Exception("Key 'symbols' tidak ada di exchangeInfo")
    pairs = [
        s["symbol"] for s in data["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
        and s["isSpotTradingAllowed"]
    ]
    return pre_filter(pairs)


def pre_filter(pairs: List[str]) -> List[str]:
    out = [
        p for p in pairs
        if p not in SKIP_SYMBOLS
        and not any(sub in p for sub in SKIP_SUBSTRINGS)
    ]
    log.info("Pre-filter: %d → %d pairs", len(pairs), len(out))
    return out


def fetch_ohlcv(symbol: str, interval: str) -> Optional[OHLCVData]:
    """
    Ambil OHLCV data. limit=202 — cukup untuk MA200 + 1 bar lookback.
    Returns None jika gagal atau data kurang.
    """
    try:
        resp = SESSION.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": 202},
            timeout=6,
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


def get_current_price(symbol: str) -> Optional[float]:
    """
    Harga terkini via klines 1m (close price candle terakhir).
    Compatible dengan data-api.binance.vision (no ticker endpoint).
    """
    try:
        resp = SESSION.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": "1m", "limit": 1},
            timeout=5,
        )
        if resp.status_code == 200:
            return float(resp.json()[0][4])
        log.warning("get_current_price %s: HTTP %s", symbol, resp.status_code)
    except Exception as e:
        log.error("get_current_price %s: %s", symbol, e)
    return None
