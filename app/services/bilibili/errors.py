from __future__ import annotations


class BiliError(Exception):
    """Upstream Bilibili API error with its business code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"bilibili error {code}: {message}")
        self.code = code
        self.message = message


class AuthExpiredError(BiliError):
    """-101 / missing session: stored cookies no longer work."""

    def __init__(self, message: str = "bilibili session expired") -> None:
        super().__init__(-101, message)


class RiskControlError(BiliError):
    """-412 / -352: request blocked by risk control; stop and back off."""

    def __init__(self, code: int = -412, message: str = "risk control triggered") -> None:
        super().__init__(code, message)
