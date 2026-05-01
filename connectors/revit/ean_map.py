"""REV'IT EAN lookup, sourced from REV'IT's authoritative article-data export.

REV'IT's order interface keys on EAN (13-digit barcode), not on SKU. Rithum's
catalog occasionally lacks EAN for REV'IT products, especially older variants.
This module provides a fallback: given a Rithum MPN (which equals
`{ItemNo}-{Variant}` in REV'IT's article numbering), return the EAN.

The data file is generated from `Article Data EANcodes REV'IT!.xlsx`. Refresh
it whenever REV'IT sends an updated list (covers 2004-now per their note).
"""
import json
import logging
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "revit_ean_map.json"
_cache: dict[str, str] | None = None
_lock = Lock()


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        if not _DATA_PATH.exists():
            logger.warning("REV'IT EAN map missing at %s — lookups will return None", _DATA_PATH)
            _cache = {}
            return _cache
        with _DATA_PATH.open() as f:
            _cache = json.load(f)
        logger.info("REV'IT EAN map loaded: %d entries", len(_cache))
        return _cache


def lookup(mpn: str | None) -> str | None:
    """Return the 13-digit EAN for a REV'IT MPN, or None if not in the map."""
    if not mpn:
        return None
    return _load().get(mpn.strip()) or None


def size() -> int:
    return len(_load())
