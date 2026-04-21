"""Idempotency, duplicate detection, and reconciliation helpers."""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import insert, select, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from core.models import OrderLineItem, POBatch, AuditLog

logger = logging.getLogger(__name__)


def make_idempotency_key(rithum_fulfillment_id: int, rithum_item_id: int) -> str:
    """Generate the idempotency key for a Rithum Fulfillment line item."""
    return f"rithum:{rithum_fulfillment_id}:{rithum_item_id}"


def ingest_line_item(db: Session, data: dict) -> OrderLineItem | None:
    """
    Insert a new order line item, returning it. If it already exists
    (duplicate), return None silently.
    """
    key = make_idempotency_key(data["rithum_fulfillment_id"], data["rithum_item_id"])

    # Check if already exists (fast path)
    existing = (
        db.query(OrderLineItem)
        .filter(OrderLineItem.idempotency_key == key)
        .first()
    )
    if existing:
        return None

    item = OrderLineItem(
        rithum_order_id=data["rithum_order_id"],
        rithum_item_id=data["rithum_item_id"],
        rithum_fulfillment_id=data["rithum_fulfillment_id"],
        dc_id=data["dc_id"],
        idempotency_key=key,
        vendor_id=data["vendor_id"],
        site_order_id=data.get("site_order_id"),
        sku=data["sku"],
        ean=data.get("ean"),
        mpn=data.get("mpn"),
        title=data.get("title"),
        quantity=data["quantity"],
        unit_price=data.get("unit_price"),
        ship_to_name=data.get("ship_to_name"),
        ship_to_address1=data.get("ship_to_address1"),
        ship_to_address2=data.get("ship_to_address2"),
        ship_to_city=data.get("ship_to_city"),
        ship_to_state=data.get("ship_to_state"),
        ship_to_postal=data.get("ship_to_postal"),
        ship_to_country=data.get("ship_to_country"),
        ship_to_email=data.get("ship_to_email"),
        ship_to_phone=data.get("ship_to_phone"),
        requested_carrier=data.get("requested_carrier"),
        requested_class=data.get("requested_class"),
        status="pending",
    )
    db.add(item)

    # Audit
    db.add(AuditLog(
        entity_type="order_line_item",
        entity_id=0,  # will be set after flush
        action="ingested",
        new_value="pending",
        details_json={"rithum_order_id": data["rithum_order_id"],
                      "rithum_item_id": data["rithum_item_id"],
                      "sku": data["sku"]},
    ))

    try:
        db.flush()
        # Update audit log with real ID
        db.query(AuditLog).filter(
            AuditLog.entity_id == 0,
            AuditLog.entity_type == "order_line_item",
            AuditLog.action == "ingested",
        ).update({"entity_id": item.id})
        return item
    except Exception:
        db.rollback()
        logger.warning("Duplicate line item ignored: %s", key)
        return None


def check_po_exists(db: Session, po_number: str) -> bool:
    """Check if a PO has already been sent to a vendor."""
    return db.query(POBatch).filter(
        POBatch.po_number == po_number,
        POBatch.status.in_(["sent", "pending_fulfillment", "shipped", "complete"]),
    ).first() is not None


def check_fulfillment_submitted(db: Session, rithum_fulfillment_id: int) -> POBatch | None:
    """Return the existing POBatch for a Rithum fulfillment, or None."""
    return db.query(POBatch).filter(
        POBatch.rithum_fulfillment_id == rithum_fulfillment_id,
    ).first()


def get_stuck_orders(db: Session, pending_hours: int = 2, submitted_hours: int = 48) -> dict:
    """Find orders stuck in a state longer than expected."""
    now = datetime.now(timezone.utc)
    results = {}

    # Pending too long
    stuck_pending = db.query(OrderLineItem).filter(
        OrderLineItem.status == "pending",
        OrderLineItem.created_at < now - timedelta(hours=pending_hours),
    ).all()
    if stuck_pending:
        results["stuck_pending"] = [
            {"id": i.id, "sku": i.sku, "created_at": str(i.created_at)}
            for i in stuck_pending
        ]

    # Submitted / pending fulfillment but no tracking
    stuck_submitted = db.query(OrderLineItem).filter(
        OrderLineItem.status.in_(["submitted", "pending_fulfillment"]),
        OrderLineItem.submitted_at < now - timedelta(hours=submitted_hours),
    ).all()
    if stuck_submitted:
        results["stuck_submitted"] = [
            {"id": i.id, "sku": i.sku, "status": i.status, "submitted_at": str(i.submitted_at)}
            for i in stuck_submitted
        ]

    # Failed items
    failed = db.query(OrderLineItem).filter(
        OrderLineItem.status == "failed",
    ).all()
    if failed:
        results["failed"] = [
            {"id": i.id, "sku": i.sku, "error": i.last_error, "retries": i.retry_count}
            for i in failed
        ]

    return results
