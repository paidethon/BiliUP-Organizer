from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.services.bilibili.errors import (
    AuthExpiredError,
    BiliError,
    CsrfError,
    RiskControlError,
    UpstreamHttpError,
    UpstreamParamError,
)
from app.services.bilibili.wbi import WbiKeyCache, parse_nav_keys, sign_params

API_BASE = "https://api.bilibili.com"
PASSPORT_BASE = "https://passport.bilibili.com"
HOME_URL = "https://www.bilibili.com/"

# Browser-grade UA; must not contain "python"/"curl" or followings returns an
# empty list and buvid issuance breaks (RESEARCH §1.3 / §4 / §9.1).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_MIN_INTERVAL = 0.6  # seconds between upstream calls (RESEARCH §9.5)
RISK_RETRY_MAX = 2  # at most 2 retries after a -412/-352 (frozen contract)
RISK_BACKOFF_BASE = 2.0  # exponential backoff: 2s, 4s
QR_EXPIRES_SECONDS = 180  # qrcode_key TTL (RESEARCH §2.1)
DEFAULT_PAGE_SIZE = 50  # followings ps (RESEARCH §4)
ARCHIVE_PAGE_SIZE = 30  # arc search ps (RESEARCH §5)
HISTORY_PAGE_SIZE = 20  # history/search ps (RESEARCH §6.1)
MAX_FOLLOWING_PAGES = 100  # hard cap so a lying `total` cannot loop forever


class BiliClient:
    """Synchronous httpx client for the Bilibili web API.

    Frozen interface (implemented by the bilibili agent):

    - ``__init__(cookies: dict[str, str] | None = None)``
    - ``_request(method, url, params=None, data=None, wbi=False) -> dict``:
      returns ``data`` when ``code == 0``; maps -101 -> AuthExpiredError,
      -412/-352 -> RiskControlError, other codes -> BiliError. Applies rate
      limiting and retries with backoff.
    - ``ensure_buvid() -> None``: warm up visitor cookies (buvid3).
    - ``get_nav() -> dict``
    - ``generate_qrcode() -> dict`` (qr_url, qrcode_key, expires seconds)
    - ``poll_qrcode(qrcode_key) -> dict`` (status + cookies on confirm)
    - ``get_followings(mid, page, page_size=50) -> dict`` (total, list)
    - ``get_all_followings(mid) -> list[dict]``
    - ``get_user_archives(mid, page=1, page_size=30) -> dict`` (total, vlist)
    - ``get_latest_archive(mid) -> dict | None``
    - ``get_history(page=1, page_size=20) -> dict`` (total, list)
    - ``close() -> None``
    """

    _LOGIN_COOKIE_NAMES = ("SESSDATA", "bili_jct", "DedeUserID")

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = 15.0,
    ) -> None:
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._wbi_cache = WbiKeyCache()
        self._last_request_at: float | None = None
        self._last_set_cookies: list[str] = []
        self._http = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
            },
            cookies=dict(cookies or {}),
            timeout=timeout,
        )

    # ------------------------------------------------------------------ core

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        wbi: bool = False,
    ) -> Any:
        query = dict(params or {})
        if wbi:
            img_key, sub_key = self._wbi_keys()
            query = sign_params(query, img_key, sub_key)
        risk_attempts = 0
        while True:
            body = self._fetch(method, url, query or None, data)
            code = _as_int(body.get("code"), -1)
            if code == 0:
                return body.get("data")
            message = str(body.get("message") or body.get("msg") or "unknown error")
            if code in (-412, -352):
                risk_attempts += 1
                if risk_attempts > RISK_RETRY_MAX:
                    raise RiskControlError(code=code, message=message)
                self._sleep(RISK_BACKOFF_BASE * (2 ** (risk_attempts - 1)))
                continue
            if code == -101:
                raise AuthExpiredError(message)
            if code == -111:
                raise CsrfError(message)
            if 22100 <= code < 22200:
                raise UpstreamParamError(code, message)
            raise BiliError(code, message)

    def _fetch(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """One throttled HTTP round trip returning the parsed JSON envelope."""
        self._throttle()
        response = self._http.request(method, url, params=params, data=data)
        self._last_set_cookies = response.headers.get_list("set-cookie")
        return _parse_body(response)

    def _throttle(self) -> None:
        """min_interval + random jitter between calls (RESEARCH §9.5)."""
        if self._last_request_at is not None and self.min_interval > 0:
            wait = self._last_request_at + self._interval() - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def _interval(self) -> float:
        # jitter only needs unpredictability for rate-limit politeness, but we
        # use a CSPRNG anyway to keep security scanners quiet; not used for
        # anything secret.
        fraction = secrets.randbelow(2500) / 10000.0
        return self.min_interval * (1.0 + fraction)

    def _wbi_keys(self) -> tuple[str, str]:
        cached = self._wbi_cache.get()
        if cached is not None:
            return cached
        # nav answers code=-101 for anonymous sessions yet still carries
        # data.wbi_img (RESEARCH §3.1), so read the raw envelope here instead
        # of going through the -101-mapped _request path.
        body = self._fetch("GET", f"{API_BASE}/x/web-interface/nav", None, None)
        img_key, sub_key = parse_nav_keys(body.get("data") or {})
        self._wbi_cache.store(img_key, sub_key)
        return img_key, sub_key

    # --------------------------------------------------------------- session

    def ensure_buvid(self) -> None:
        """Warm up visitor cookies (buvid3/b_nut) from the main site (RESEARCH §9.2)."""
        if self._http.cookies.get("buvid3"):
            return
        self._throttle()
        response = self._http.get(HOME_URL)
        self._last_set_cookies = response.headers.get_list("set-cookie")
        # Set-Cookie is captured into the shared cookie jar automatically.

    def get_nav(self) -> dict:
        data = self._request("GET", f"{API_BASE}/x/web-interface/nav")
        return dict(data or {})

    # --------------------------------------------------------------- qr login

    def generate_qrcode(self) -> dict:
        data = self._request("GET", f"{PASSPORT_BASE}/x/passport-login/web/qrcode/generate")
        data = dict(data or {})
        return {
            "qr_url": str(data.get("url") or ""),
            "qrcode_key": str(data.get("qrcode_key") or ""),
            "expires_in": QR_EXPIRES_SECONDS,
        }

    def poll_qrcode(self, qrcode_key: str) -> dict:
        data = self._request(
            "GET",
            f"{PASSPORT_BASE}/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": qrcode_key},
        )
        data = dict(data or {})
        return {
            "code": _as_int(data.get("code"), -1),
            "url": str(data.get("url") or ""),
            "cookies": self._login_cookies(),
        }

    def _login_cookies(self) -> dict[str, str]:
        """Read SESSDATA/bili_jct/DedeUserID off the latest poll Set-Cookie headers.

        Only cookies carried by THIS response count; SESSDATA values may contain
        commas, so raw headers are parsed verbatim (the cookie jar can mangle
        them) (RESEARCH §2.2).
        """
        found: dict[str, str] = {}
        for raw in self._last_set_cookies:
            name, sep, value = raw.partition("=")
            if sep and name.strip() in self._LOGIN_COOKIE_NAMES:
                # value runs up to the first attribute separator ';'
                found[name.strip()] = value.split(";", 1)[0].strip()
        return found

    # ------------------------------------------------------------- followings

    def get_followings(self, mid: int, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
        """One wbi-signed followings page (RESEARCH §4): {"total": int, "list": [...]}."""
        data = self._request(
            "GET",
            f"{API_BASE}/x/relation/followings",
            params={"vmid": mid, "pn": page, "ps": page_size},
            wbi=True,
        )
        data = dict(data or {})
        return {"total": _as_int(data.get("total"), 0), "list": list(data.get("list") or [])}

    def get_all_followings(self, mid: int) -> list[dict]:
        entries: list[dict] = []
        page = 1
        while page <= MAX_FOLLOWING_PAGES:
            data = self.get_followings(mid, page=page)
            rows = data["list"]
            if not rows:
                break
            entries.extend(rows)
            if len(entries) >= data["total"]:
                break
            page += 1
        return entries

    # --------------------------------------------------------------- archives

    def get_user_archives(self, mid: int, page: int = 1, page_size: int = ARCHIVE_PAGE_SIZE) -> dict:
        """Wbi-signed UP uploads page, newest first (RESEARCH §5)."""
        data = self._request(
            "GET",
            f"{API_BASE}/x/space/wbi/arc/search",
            params={"mid": mid, "pn": page, "ps": page_size, "order": "pubdate"},
            wbi=True,
        )
        data = dict(data or {})
        page_info = dict(data.get("page") or {})
        vlist = dict(data.get("list") or {}).get("vlist") or []
        return {"total": _as_int(page_info.get("count"), 0), "vlist": list(vlist)}

    def get_latest_archive(self, mid: int) -> dict | None:
        vlist = self.get_user_archives(mid, page=1)["vlist"]
        return vlist[0] if vlist else None

    # ---------------------------------------------------------------- history

    def get_history(self, page: int = 1, page_size: int = HISTORY_PAGE_SIZE) -> dict:
        """Watch-history search page; `business=archive` narrows to videos
        (RESEARCH §6.1: the param name is `business`, cross-checked against
        three independent projects; NOT `business_type`)."""
        data = self._request(
            "GET",
            f"{API_BASE}/x/web-interface/history/search",
            params={"pn": page, "ps": page_size, "keyword": "", "business": "archive"},
        )
        data = dict(data or {})
        page_info = dict(data.get("page") or {})
        return {"total": _as_int(page_info.get("total"), 0), "list": list(data.get("list") or [])}

    # ------------------------------------------------------------------ misc

    def close(self) -> None:
        self._http.close()


def _parse_body(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        # 404/5xx/redirects: endpoint path or transport changed — typed so
        # route handlers can answer 502 with a real cause, never a raw 500.
        raise UpstreamHttpError(response.status_code)
    try:
        body = response.json()
    except ValueError:
        raise UpstreamHttpError(response.status_code, "response is not valid JSON") from None
    if not isinstance(body, dict):
        raise UpstreamHttpError(response.status_code, "response JSON is not an object")
    return body


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
