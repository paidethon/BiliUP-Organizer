"""Read-only LumiRSS discovery: probe candidate base URLs and auto-fill settings.

Detection only ever issues GET requests — it never POSTs to (or otherwise
mutates) the LumiRSS instance. The only write is to this app's own settings
row. The API token cannot be discovered read-only, so detection fills
base_url + inbox_endpoint and leaves whatever token is already stored.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.services.settings_store import get_section_raw, update_section

log = logging.getLogger(__name__)

_PROBE_PATHS = ("/healthz", "/")
_PROBE_PORTS = ("18080", "8787", "3000")
_PROBE_TIMEOUT = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)


def _default_gateway() -> str | None:
    """Docker bridge gateway = the host as seen from inside the container."""
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 3 and fields[1] == "00000000" and fields[3] == "00000000":
                raw = fields[2]
                ip = ".".join(str(int(raw[i : i + 2], 16)) for i in (6, 4, 2, 0))
                if ip:
                    return ip
    except (OSError, ValueError):
        return None
    return None


def _candidates(explicit: str | None) -> list[str]:
    out: list[str] = []
    if explicit:
        out.append(explicit.strip())
    env_url = os.environ.get("LUMIRSS_BASE_URL", "").strip()
    if env_url:
        out.append(env_url)
    gateway = _default_gateway()
    hosts: list[str] = []
    if gateway:
        hosts.append(gateway)
    hosts += ["127.0.0.1", "localhost", "host.docker.internal"]
    for host in hosts:
        for port in _PROBE_PORTS:
            out.append(f"http://{host}:{port}")
    seen: set[str] = set()
    unique: list[str] = []
    for url in out:
        url = url.rstrip("/")
        if url and url not in seen and not url.startswith("https://"):
            seen.add(url)
            unique.append(url)
    return unique[:10]


def _probe(base_url: str) -> tuple[bool, bool]:
    """Return (reachable, identity_confirmed). GET-only."""
    with httpx.Client(timeout=_PROBE_TIMEOUT, follow_redirects=True) as client:
        for path in _PROBE_PATHS:
            try:
                resp = client.get(base_url + path)
            except httpx.HTTPError:
                continue
            if resp.status_code >= 500:
                continue
            text = resp.text[:4000].lower()
            return True, "lumirss" in text or "lumi rss" in text
    return False, False


def detect_and_configure(db: Session, base_url: str | None = None) -> dict:
    tried = _candidates(base_url)
    for candidate in tried:
        reachable, verified = _probe(candidate)
        if not reachable:
            continue
        current = get_section_raw(db, "lumirss")
        endpoint = str(current.get("inbox_endpoint") or "").strip() or None
        update_section(
            db,
            "lumirss",
            {"base_url": candidate, **({"inbox_endpoint": endpoint} if endpoint else {})},
        )
        fresh = get_section_raw(db, "lumirss")
        return {
            "ok": True,
            "base_url": candidate,
            "verified": verified,
            "token_present": bool(fresh.get("token")),
            "enabled": bool(fresh.get("enabled")),
            "tried": tried,
            "message": (
                f"已检测到 LumiRSS（{candidate}）并写入 Base URL 与 Inbox 端点；"
                + ("Token 已配置。" if fresh.get("token") else "Token 无法只读探测，请手动填写后保存。")
            ),
        }
    return {
        "ok": False,
        "base_url": None,
        "verified": False,
        "token_present": False,
        "tried": tried,
        "message": "未探测到 LumiRSS 服务；可手动填写 Base URL（只做 GET 探测，不会改动 LumiRSS）",
    }
