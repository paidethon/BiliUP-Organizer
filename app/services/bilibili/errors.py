from __future__ import annotations


class BiliError(Exception):
    """Upstream Bilibili API error with its business code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"bilibili error {code}: {message}")
        self.code = code
        self.message = message
        self.kind = "upstream"


class AuthExpiredError(BiliError):
    """-101 / missing session: stored cookies no longer work."""

    def __init__(self, message: str = "bilibili session expired") -> None:
        super().__init__(-101, message)
        self.kind = "auth"


class RiskControlError(BiliError):
    """-412 / -352: request blocked by risk control; stop and back off."""

    def __init__(self, code: int = -412, message: str = "risk control triggered") -> None:
        super().__init__(code, message)
        self.kind = "risk_control"


class AccountCancelledError(BiliError):
    """22013: the TARGET UP's account is cancelled (注销) while still sitting in
    the following list; upstream rejects any relation mutation for it. Per-UP
    skippable — push callers record the mid and keep going."""

    def __init__(self, message: str = "账号已注销，无法完成操作") -> None:
        super().__init__(22013, message)
        self.kind = "cancelled"


class CsrfError(BiliError):
    """-111: bili_jct CSRF token rejected by upstream."""

    def __init__(self, message: str = "bilibili csrf check failed") -> None:
        super().__init__(-111, message)
        self.kind = "csrf"


class UpstreamHttpError(BiliError):
    """Non-200 transport-level response (404/5xx/non-JSON body): the endpoint
    path or response contract changed, or the network path is broken. Distinct
    from business-code errors so route handlers can map it to 502/504 with a
    meaningful message instead of an opaque 500."""

    def __init__(self, status: int, message: str | None = None) -> None:
        super().__init__(-1, message or f"http {status}")
        self.status = status
        self.kind = "http"


class UpstreamContractError(BiliError):
    """code==0 envelope arrived but the data payload shape does not match the
    documented contract (list vs object, missing keys). Never silently coerce."""

    def __init__(self, message: str) -> None:
        super().__init__(-2, message)
        self.kind = "contract"


class UpstreamParamError(BiliError):
    """221xx business errors (group missing / user not followed / privacy)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(code, message)
        self.kind = "param"
