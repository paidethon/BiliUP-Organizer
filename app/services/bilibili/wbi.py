from __future__ import annotations

from typing import Any

# Frozen interface (implemented by the bilibili agent):
#
# MIXIN_KEY_ENC_TAB: tuple[int, ...]  # exact 64->32 permutation table
#
# def get_mixin_keys(img_key: str, sub_key: str) -> tuple[str, str]: ...
# def sign_params(params: dict[str, Any], img_key: str, sub_key: str,
#                 now: int | None = None) -> dict[str, Any]:
#     """Adds wts, sorts, filters !'()* from values, urlencodes, md5-signates
#     and returns the final query dict including w_rid and wts."""

MIXIN_KEY_ENC_TAB: tuple[int, ...] = ()


def sign_params(params: dict[str, Any], img_key: str, sub_key: str, now: int | None = None) -> dict[str, Any]:
    raise NotImplementedError("implemented by the bilibili agent")
