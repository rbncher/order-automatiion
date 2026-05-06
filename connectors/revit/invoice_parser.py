"""Parse REV'IT invoice CSV files for tracking information.

The invoice CSV is semicolon-delimited with fields:
Document No.;PO/Customer Order No.;Shipment Date;Posting Date;Item No.;
Description;Variant;Quantity;Unit Price Excl. VAT;Line Discount %;
Line Discount Amount;Net Amount per Unit after Discount Incl. VAT;
Net. Line Amount after Discount;Order Type;Customer No.;Customer Name;
Order No. REV'IT!;EAN Code;Tracking No.;Box ID;SKU;Weight;Dimensions;Composition
"""
import csv
import io
import logging
from datetime import datetime

from core.schemas import TrackingInfo

logger = logging.getLogger(__name__)


def parse_invoice_csv(csv_content: str) -> list[TrackingInfo]:
    """
    Parse a REV'IT invoice CSV and extract tracking information.

    Returns a list of TrackingInfo objects, one per unique (PO#, tracking#, SKU) combo.
    """
    results = []
    reader = csv.DictReader(
        io.StringIO(csv_content),
        delimiter=";",
    )

    for row in reader:
        po_number = (row.get("PO/Customer Order No.") or "").strip()
        tracking = (row.get("Tracking No.") or "").strip()
        sku = (row.get("SKU") or "").strip()
        ean = (row.get("EAN Code") or "").strip()
        ship_date_str = (row.get("Shipment Date") or "").strip()

        if not po_number or not tracking:
            continue

        # Parse ship date (format: DD-MM-YY)
        ship_date = None
        if ship_date_str:
            try:
                ship_date = datetime.strptime(ship_date_str, "%d-%m-%y").date()
            except ValueError:
                try:
                    ship_date = datetime.strptime(ship_date_str, "%Y-%m-%d").date()
                except ValueError:
                    logger.warning("Could not parse ship date: %s", ship_date_str)

        # Parse quantity
        qty_str = (row.get("Quantity") or "0").strip().replace(",", ".")
        try:
            quantity = int(float(qty_str))
        except ValueError:
            quantity = None

        results.append(TrackingInfo(
            po_number=po_number,
            sku=sku or None,
            ean=ean or None,
            tracking_number=tracking,
            carrier=None,  # Filled in by the connector from shipping_agent
            ship_date=ship_date,
            quantity=quantity,
        ))

    logger.info("Parsed %d tracking records from invoice CSV", len(results))
    return results


def group_tracking_by_po(tracking_list: list[TrackingInfo]) -> dict[str, list[TrackingInfo]]:
    """Group tracking info by PO number."""
    groups: dict[str, list[TrackingInfo]] = {}
    for t in tracking_list:
        groups.setdefault(t.po_number, []).append(t)
    return groups
