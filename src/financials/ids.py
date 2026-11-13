"""Deterministic identifiers: replaying the same inputs yields the same IDs."""

from __future__ import annotations

import hashlib


def stable_id(prefix: str, *parts: object) -> str:
    joined = "\x1f".join("" if p is None else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:24]}"
