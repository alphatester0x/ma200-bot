import requests

# Single shared Session untuk semua HTTP calls (Binance, Telegram, GitHub Gist)
SESSION = requests.Session()
_adapter = requests.adapters.HTTPAdapter(
    pool_connections=30,
    pool_maxsize=30,
    max_retries=1,
)
SESSION.mount("https://", _adapter)
SESSION.headers.update({
    "Accept-Encoding": "gzip",
    "Connection":      "keep-alive",
})
