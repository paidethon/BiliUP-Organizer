"""Tests for the Wbi signing module (app/services/bilibili/wbi.py).

Golden values are the official test vectors from docs/RESEARCH_BILIBILI.md
§3.2 (bilibili-API-collect docs/misc/sign/wbi.md):
- img_key/sub_key -> mixin_key = ea1db124af3c7062474693fa704f4ff8
- params foo=114, bar=514, zab=1919810, wts=1702204169
  -> w_rid = 8f6f2b5b3d485fe1886cec6a0be8c5d4
"""

from __future__ import annotations

import hashlib
from urllib.parse import quote

import pytest

from app.services.bilibili.errors import BiliError
from app.services.bilibili.wbi import (
    MIXIN_KEY_ENC_TAB,
    extract_key,
    get_mixin_keys,
    parse_nav_keys,
    sign_params,
)

IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"
MIXIN_KEY = "ea1db124af3c7062474693fa704f4ff8"
OFFICIAL_WTS = 1702204169
OFFICIAL_W_RID = "8f6f2b5b3d485fe1886cec6a0be8c5d4"


def test_mixin_key_matches_official_vector() -> None:
    mixin, raw = get_mixin_keys(IMG_KEY, SUB_KEY)
    assert raw == IMG_KEY + SUB_KEY
    assert mixin == MIXIN_KEY


def test_permutation_table_is_the_documented_64_entries() -> None:
    assert len(MIXIN_KEY_ENC_TAB) == 64
    assert sorted(MIXIN_KEY_ENC_TAB) == list(range(64))


def test_sign_params_matches_official_vector() -> None:
    signed = sign_params(
        {"foo": "114", "bar": "514", "zab": 1919810}, IMG_KEY, SUB_KEY, now=OFFICIAL_WTS
    )
    assert signed["wts"] == str(OFFICIAL_WTS)
    assert signed["w_rid"] == OFFICIAL_W_RID


def test_sign_params_keys_sorted_values_filtered_and_encoded() -> None:
    signed = sign_params(
        {"z": "a b", "a": "x!y'z()*w", "m": "中文"}, IMG_KEY, SUB_KEY, now=OFFICIAL_WTS
    )
    keys = [k for k in signed if k != "w_rid"]
    assert keys == sorted(keys)
    # !'()* stripped from values (wbi.md step 4)
    assert signed["a"] == "xyzw"
    # values stay raw in the dict; encodeURIComponent-style %20/uppercase-hex
    # encoding happens when building the md5 query (recomputed below)
    assert signed["z"] == "a b"
    assert signed["m"] == "中文"
    query = "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in signed.items() if k != "w_rid"
    )
    assert signed["w_rid"] == hashlib.md5((query + MIXIN_KEY).encode("utf-8")).hexdigest()


def test_sign_params_does_not_mutate_input() -> None:
    params = {"foo": "114"}
    sign_params(params, IMG_KEY, SUB_KEY, now=OFFICIAL_WTS)
    assert params == {"foo": "114"}


def test_sign_params_accepts_non_string_values() -> None:
    signed = sign_params({"n": 1919810, "b": True}, IMG_KEY, SUB_KEY, now=OFFICIAL_WTS)
    assert signed["n"] == "1919810"
    assert signed["b"] == "True"


def test_parse_nav_keys_and_extract_key() -> None:
    data = {
        "wbi_img": {
            "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
            "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
        }
    }
    assert parse_nav_keys(data) == (IMG_KEY, SUB_KEY)
    assert extract_key(f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png") == IMG_KEY


def test_parse_nav_keys_requires_both_urls() -> None:
    with pytest.raises(BiliError):
        parse_nav_keys({"wbi_img": {"img_url": f"https://x/{IMG_KEY}.png"}})
    with pytest.raises(BiliError):
        parse_nav_keys({})
