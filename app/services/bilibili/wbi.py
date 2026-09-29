from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from app.services.bilibili.errors import BiliError

# Exact 64-entry permutation table from docs/RESEARCH_BILIBILI.md §3.2
# (source: bilibili-API-collect docs/misc/sign/wbi.md). Do not "fix" ordering.
MIXIN_KEY_ENC_TAB: tuple[int, ...] = (
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
)

# Characters stripped from parameter values before signing (wbi.md step 4).
_FILTER_CHARS = "!'()*"

# nav keys rotate about daily; research doc recommends a cache of <= 1 hour.
WBI_KEY_TTL_SECONDS = 3600.0


def get_mixin_keys(img_key: str, sub_key: str) -> tuple[str, str]:
    """Permute ``img_key + sub_key`` through MIXIN_KEY_ENC_TAB.

    Returns ``(mixin_key, raw_key)``: the 32-char signing secret used for
    ``w_rid`` and the raw 64-char concatenation (kept for debugging/inspection).
    """
    raw_key = img_key + sub_key
    mixin_key = "".join(raw_key[i] for i in MIXIN_KEY_ENC_TAB)[:32]
    return mixin_key, raw_key


def sign_params(params: dict[str, Any], img_key: str, sub_key: str, now: int | None = None) -> dict[str, Any]:
    """Wbi-sign query params (wbi.md algorithm).

    Adds ``wts`` (second-precision unix time), sorts by key, strips ``!'()*``
    from values, urlencodes (encodeURIComponent style: ``%20`` for spaces,
    uppercase hex) and appends ``w_rid = md5(query + mixin_key)``.

    Returns the final query dict (string values) including ``w_rid`` and
    ``wts``; the input dict is not mutated.
    """
    mixin_key, _ = get_mixin_keys(img_key, sub_key)
    wts = int(time.time() if now is None else now)
    prepared: dict[str, Any] = {str(k): v for k, v in params.items()}
    prepared["wts"] = wts
    prepared = dict(sorted(prepared.items()))
    prepared = {k: "".join(ch for ch in str(v) if ch not in _FILTER_CHARS) for k, v in prepared.items()}
    query = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in prepared.items())
    prepared["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return prepared


def extract_key(url: str) -> str:
    """Pull the key out of a nav ``wbi_img`` URL (file name without extension)."""
    name = url.rsplit("/", 1)[-1]
    return name.split(".", 1)[0]


def parse_nav_keys(nav_data: dict[str, Any]) -> tuple[str, str]:
    """Extract (img_key, sub_key) from a ``/x/web-interface/nav`` payload."""
    wbi_img = (nav_data or {}).get("wbi_img") or {}
    img_url = str(wbi_img.get("img_url") or "")
    sub_url = str(wbi_img.get("sub_url") or "")
    if not img_url or not sub_url:
        raise BiliError(-1, "nav response is missing wbi_img keys")
    return extract_key(img_url), extract_key(sub_url)


class WbiKeyCache:
    """Process-local cache for the daily-rotating nav wbi keys (<= 1h, RESEARCH §3.1)."""

    def __init__(self, ttl: float = WBI_KEY_TTL_SECONDS, clock: Callable[[], float] | None = None) -> None:
        self._ttl = ttl
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._keys: tuple[str, str] | None = None
        self._expires_at = 0.0

    def store(self, img_key: str, sub_key: str) -> None:
        with self._lock:
            self._keys = (img_key, sub_key)
            self._expires_at = self._clock() + self._ttl

    def get(self) -> tuple[str, str] | None:
        with self._lock:
            if self._keys is not None and self._clock() < self._expires_at:
                return self._keys
            return None

    def clear(self) -> None:
        with self._lock:
            self._keys = None
            self._expires_at = 0.0
