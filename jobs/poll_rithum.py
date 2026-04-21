"""Discover new Rithum Fulfillments at our configured DCs and ingest them.

Ingest only — the actual PO send happens in place_orders. A fulfillment
ingested here will have a POBatch row (status='pending') plus one
OrderLineItem per fulfillment item (status='pending').
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from clients.rithum import RithumClient
from core.database import SessionLocal
from core.models import Vendor, POBatch, JobRun
from core.safety import ingest_line_item, check_fulfillment_submitted

logger = logging.getLogger(__name__)


def _item_lookup(order: dict) -> dict[int, dict]:
    """Build {OrderItemID: order_item} from an order's Items for cross-reference."""
    return {it["ID"]: it for it in order.get("Items", []) if it.get("ID")}


def _ship_to_from_order(order: dict) -> dict:
    name = " ".join(filter(None, [
        order.get("ShippingFirstName"),
        order.get("ShippingLastName"),
    ]))
    return {
        "ship_to_name": name,
        "ship_to_address1": order.get("ShippingAddressLine1", "") or "",
        "ship_to_address2": order.get("ShippingAddressLine2", "") or "",
        "ship_to_city": order.get("ShippingCity", "") or "",
        "ship_to_state": order.get("ShippingStateOrProvince", "") or "",
        "ship_to_postal": order.get("ShippingPostalCode", "") or "",
        "ship_to_country": order.get("ShippingCountry", "") or "",
        "ship_to_email": order.get("BuyerEmailAddress", "") or "",
        "ship_to_phone": order.get("ShippingDaytimePhone", "") or "",
    }


def _ingest_fulfillment(
    db: Session,
    client: RithumClient,
    vendor: Vendor,
    dc_id: int,
    fulfillment: dict,
    order: dict,
) -> POBatch | None:
    """Create POBatch + OrderLineItem rows for one new fulfillment. Return the batch."""
    ful_id = fulfillment["ID"]
    order_id = order["ID"]

    # Idempotency: skip if already ingested
    if check_fulfillment_submitted(db, ful_id):
        return None

    # Fulfillment-level items only carry SKU + OrderItemID + Quantity. Cross-ref
    # the Order-level Items (expanded on the order) for Title + UnitPrice.
    ful_items = client.get_fulfillment_items(ful_id)
    if not ful_items:
        logger.warning(
            "Fulfillment %d has no items — skipping", ful_id,
        )
        return None

    order_items_by_id = _item_lookup(order)
    ship_to = _ship_to_from_order(order)

    # Bulk product lookup for EAN/MPN
    skus = list({fi.get("Sku") for fi in ful_items if fi.get("Sku")})
    products = client.get_products_by_skus(skus) if skus else {}

    # PO number = {DC_CODE}-{FulfillmentID} — globally unique, ties back cleanly
    po_number = f"{vendor.code}-{ful_id}"

    total_qty = sum(int(fi.get("Quantity") or 0) for fi in ful_items)

    batch = POBatch(
        vendor_id=vendor.id,
        rithum_fulfillment_id=ful_id,
        rithum_order_id=order_id,
        po_number=po_number,
        file_name=f"{po_number}.csv",
        line_count=len(ful_items),
        total_quantity=total_qty,
        status="pending",
    )
    db.add(batch)
    db.flush()  # assigns batch.id

    for fi in ful_items:
        sku = fi.get("Sku") or ""
        order_item_id = fi.get("OrderItemID")
        order_item = order_items_by_id.get(order_item_id) or {}
        product = products.get(sku) or {}

        data = {
            "rithum_order_id": order_id,
            "rithum_item_id": order_item_id,
            "rithum_fulfillment_id": ful_id,
            "dc_id": dc_id,
            "vendor_id": vendor.id,
            "site_order_id": str(order.get("SiteOrderID") or "") or None,
            "sku": sku,
            "ean": product.get("EAN") or "",
            "mpn": product.get("MPN") or "",
            "title": order_item.get("Title") or "",
            "quantity": int(fi.get("Quantity") or 1),
            "unit_price": (
                Decimal(str(order_item.get("UnitPrice")))
                if order_item.get("UnitPrice") is not None else None
            ),
            **ship_to,
            "requested_carrier": order.get("RequestedShippingCarrier", "") or "",
            "requested_class": order.get("RequestedShippingClass", "") or "",
        }

        line_item = ingest_line_item(db, data)
        if line_item is not None:
            line_item.po_number = po_number
            line_item.po_batch_id = batch.id

    return batch


def run():
    """Poll Rithum for New Fulfillments at each active vendor's DC."""
    db: Session = SessionLocal()
    job = JobRun(job_name="poll_rithum")
    db.add(job)
    db.commit()

    total_ingested = 0
    total_scanned = 0

    try:
        client = RithumClient()
        client.authenticate()

        vendors = db.query(Vendor).filter(Vendor.is_active == True).all()
        if not vendors:
            logger.warning("No active vendors configured")
            job.status = "success"
            return

        for vendor in vendors:
            dc_id = vendor.config_json.get("dc_id") if vendor.config_json else None
            if not dc_id:
                logger.info(
                    "Vendor %s has no dc_id configured — skipping",
                    vendor.code,
                )
                continue

            logger.info(
                "Polling Rithum fulfillments for vendor %s (DC %d)",
                vendor.code, dc_id,
            )

            for wrap in client.fetch_new_fulfillments(dc_id=dc_id):
                total_scanned += 1
                fulfillment = wrap["Fulfillment"]
                order = wrap["Order"]

                try:
                    batch = _ingest_fulfillment(
                        db, client, vendor, dc_id, fulfillment, order,
                    )
                    if batch is not None:
                        db.commit()
                        total_ingested += 1
                        logger.info(
                            "Ingested fulfillment %d (order %d) -> PO %s, %d items",
                            fulfillment["ID"], order["ID"],
                            batch.po_number, batch.line_count,
                        )
                except Exception:
                    logger.exception(
                        "Failed to ingest fulfillment %d (order %d)",
                        fulfillment.get("ID"), order.get("ID"),
                    )
                    db.rollback()

        job.items_processed = total_ingested
        job.status = "success"
        job.details_json = {"scanned": total_scanned, "ingested": total_ingested}
        logger.info(
            "poll_rithum done: scanned %d New fulfillments, ingested %d",
            total_scanned, total_ingested,
        )

    except Exception as e:
        logger.exception("poll_rithum failed: %s", e)
        job.status = "failed"
        job.error_message = str(e)
        db.rollback()

    finally:
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.close()
