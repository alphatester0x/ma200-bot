"""
Gist Storage — simpan/load tracked signals ke GitHub Gist.
Semua request pakai shared SESSION (bukan requests.get/post langsung).
"""

import json
import time
from typing import Tuple, Optional

from config import GIST_TOKEN, GIST_FILENAME
from session import SESSION
from logger import get_logger

log = get_logger("gist")

_GIST_API  = "https://api.github.com/gists"
_LOCK_FILE = "ma200_lock"          # simple advisory lock di Gist
_HEADERS   = lambda: {"Authorization": f"Bearer {GIST_TOKEN}"}


# ------------------------------------------------------------------ #
#  Internal helpers
# ------------------------------------------------------------------ #

def _find_id() -> Optional[str]:
    resp = SESSION.get(_GIST_API, headers=_HEADERS(), timeout=10)
    if resp.status_code != 200:
        log.error("Gagal list gists: HTTP %s", resp.status_code)
        return None
    for g in resp.json():
        if GIST_FILENAME in g.get("files", {}):
            return g["id"]
    return None


def _create() -> Optional[str]:
    payload = {
        "description": "MA200 Bot — Signal Tracker",
        "public": False,
        "files": {
            GIST_FILENAME:  {"content": "{}"},
            _LOCK_FILE:     {"content": "0"},
        },
    }
    resp = SESSION.post(_GIST_API, headers=_HEADERS(), json=payload, timeout=10)
    if resp.status_code == 201:
        gid = resp.json()["id"]
        log.info("Gist baru dibuat: %s", gid)
        return gid
    log.error("Gagal buat Gist: HTTP %s — %s", resp.status_code, resp.text[:120])
    return None


def _get_etag(gid: str) -> Optional[str]:
    """Ambil ETag untuk optimistic-lock check."""
    resp = SESSION.head(f"{_GIST_API}/{gid}", headers=_HEADERS(), timeout=10)
    return resp.headers.get("ETag")


# ------------------------------------------------------------------ #
#  Public API
# ------------------------------------------------------------------ #

def gist_load() -> Tuple[dict, Optional[str]]:
    """
    Load tracked data dari Gist.
    Returns (data_dict, gist_id).
    """
    gid = _find_id() or _create()
    if not gid:
        return {}, None

    resp = SESSION.get(f"{_GIST_API}/{gid}", headers=_HEADERS(), timeout=10)
    if resp.status_code != 200:
        log.error("Gagal load Gist: HTTP %s", resp.status_code)
        return {}, gid

    raw = resp.json()["files"].get(GIST_FILENAME, {}).get("content", "{}")
    try:
        data = json.loads(raw)
        log.info("Gist loaded — %d token ditracking", len(data))
        return data, gid
    except json.JSONDecodeError:
        log.warning("Gist content corrupt, reset ke {}")
        return {}, gid


def gist_save(gid: Optional[str], data: dict, retries: int = 3) -> bool:
    """
    Save tracked data ke Gist dengan simple retry.
    Returns True jika berhasil.
    """
    if not gid:
        log.error("gist_save dipanggil tanpa gist_id")
        return False

    payload = {"files": {GIST_FILENAME: {"content": json.dumps(data, indent=2)}}}

    for attempt in range(1, retries + 1):
        resp = SESSION.patch(
            f"{_GIST_API}/{gid}",
            headers=_HEADERS(),
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            log.info("Gist saved — %d token", len(data))
            return True
        log.warning(
            "Gist save gagal (attempt %d/%d): HTTP %s",
            attempt, retries, resp.status_code,
        )
        if attempt < retries:
            time.sleep(2 ** attempt)   # exponential backoff: 2s, 4s

    log.error("Gist save gagal setelah %d attempts", retries)
    return False
