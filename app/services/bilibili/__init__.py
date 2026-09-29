"""Bilibili upstream integration (owned by the bilibili agent).

Design constraints (from docs/RESEARCH_BILIBILI.md once research lands):
- One httpx.Client per BiliClient with browser-like headers (UA, Referer, Origin).
- Wbi-signed GETs for endpoints that require it (followings, arc search).
- Rate limiting: min interval between calls + jitter; exponential backoff on
  -412/-352; those codes raise RiskControlError which the app records as a
  risk_control reminder and pauses syncing.
- Auth errors (-101) raise AuthExpiredError -> login_status becomes 'expired'
  and a login_expired reminder is created.
"""
