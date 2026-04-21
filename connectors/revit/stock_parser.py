"""Parse REV'IT stock file (stock_revit_rsu.csv).

CSV format: EAN,SKUCode,LifecycleStatus,Stock Status1,Stock Status2,Stock Status3,ETA,Sale
- Stock Status1: Y=in stock, N=out of stock
- Stock Status2: 1=in stock, 0=not
- Stock Status3: quantity count (or "30+")
- Sale: Y=closeout/out of MAP, N=current (may lag NL by a few days)
- ETA: date or empty
"""
import csv
import io
import logging

logger = logging.getLogger(__name__)


def parse_stock_file(csv_content: str) -> dict[str, dict]:
    """
    Parse the REV'IT stock file.

    Returns: {ean: {sku: str, available: bool, lifecycle: str, qty_range: str, eta: str}}
    """
    result = {}
    reader = csv.DictReader(io.StringIO(csv_content))

    for row in reader:
        ean = (row.get("EAN") or "").strip()
        if not ean:
            continue

        available = (row.get("Stock Status1") or "").strip().upper() == "Y"
        qty_range = (row.get("Stock Status3") or "0").strip()

        result[ean] = {
            "sku": (row.get("SKUCode") or "").strip(),
            "available": available,
            "lifecycle": (row.get("LifecycleStatus") or "").strip(),
            "qty_range": qty_range,
            "eta": (row.get("ETA") or "").strip(),
        }

    logger.info("Parsed %d stock entries from REV'IT stock file", len(result))
    return result
