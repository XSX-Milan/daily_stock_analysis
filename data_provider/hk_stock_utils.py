# -*- coding: utf-8 -*-
"""Hong Kong stock code helpers used by recommendation modules."""

from __future__ import annotations

import re

_HK_PREFIXED_PATTERN = re.compile(r"^HK(\d{5})$", re.IGNORECASE)
_HK_PLAIN_PATTERN = re.compile(r"^(\d{1,5})$")
_HK_SUFFIX_PATTERN = re.compile(r"^(\d{1,5})\.HK$", re.IGNORECASE)

HK_INDEX_CODE_MAP: dict[str, str] = {
    "HSI": "HSI",
    "HSCEI": "HSCEI",
    "HSTECH": "HSTECH",
}


def normalize_hk_code(code: str) -> str | None:
    value = str(code or "").strip().upper()
    if not value:
        return None

    prefixed = _HK_PREFIXED_PATTERN.match(value)
    if prefixed:
        return prefixed.group(1)

    suffixed = _HK_SUFFIX_PATTERN.match(value)
    if suffixed:
        return suffixed.group(1).zfill(5)

    plain = _HK_PLAIN_PATTERN.match(value)
    if plain:
        return plain.group(1).zfill(5)

    return None


def normalize_hk_stock_code(code: str) -> str | None:
    return normalize_hk_code(code)


def is_hk_stock_code(code: str) -> bool:
    return normalize_hk_code(code) is not None


def get_hk_index_codes() -> dict[str, str]:
    return dict(HK_INDEX_CODE_MAP)
