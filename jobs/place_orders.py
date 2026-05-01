"""Send pending POBatches to their vendors and mark Rithum fulfillments Pending.

Operates on POBatch rows created by poll_rithum (status='pending').
On success → POBatch status='sent', line items 'submitted', then
Rithum fulfillment is patched to ExternalFulfillmentStatus='Pending' →
POBatch status='pending_fulfillment', line items 'pending_fulfillment'.

If a POBatch is already 'sent' but the Rithum mark failed on a prior
run, we retry just the Rithum mark (idempotent).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from clients.rithum import RithumClient
from core import shadow
from core.database import SessionLocal
from core.models import Vendor, OrderLineItem, POBatch, JobRun
from core.state_machine import transition
from connectors.registry import get_connector

logger = logging.getLogger(__name__)


def _line_dicts_for_batch(db: Session, batch: POBatch) -> list[dict]:
    """Build the connector payload from OrderLineItem rows attached to a POBatch."""
    items = (
        db.query(OrderLineItem)
        .filter(OrderLineItem.po_batch_id == batch.id)
        .order_by(OrderLineItem.id)
        .all()
    )
    return [
        {
            "line_item_id": it.id,
            "rithum_order_id": it.rithum_order_id,
            "rithum_item_id": it.rithum_item_id,
            "ean": it.ean,
            "mpn": it.mpn,
            "sku": it.sku,
            "title": it.title,
            "quantity": it.quantity,
            "unit_price": float(it.unit_price) if it.unit_price is not None else None,
            "ship_to_name": it.ship_to_name,
            "ship_to_address1": it.ship_to_address1,
            "ship_to_address2": it.ship_to_address2,
            "ship_to_city": it.ship_to_city,
            "ship_to_state": it.ship_to_state,
            "ship_to_postal": it.ship_to_postal,
            "ship_to_country": it.ship_to_country,
            "ship_to_email": it.ship_to_email,
            "ship_to_phone": it.ship_to_phone,
        }
        for it in items
    ]


def _mark_rithum_pending(
    rithum: RithumClient,
    batch: POBatch,
    db: Session,
) -> bool:
    """Patch the Rithum fulfillment to 'Pending' and advance DB state. Returns success."""
    try:
        rithum.mark_fulfillment_pending(
            fulfillment_id=batch.rithum_fulfillment_id,
            po_number=batch.po_number,
        )
    except Exception as e:
        logger.exception(
            "Rithum mark_fulfillment_pending failed for %s (fulfillment %d)",
            batch.po_number, batch.rithum_fulfillment_id,
        )
        batch.last_error = f"rithum mark: {e}"[:2000]
        db.commit()
        return False

    batch.status = "pending_fulfillment"
    batch.pending_marked_at = datetime.now(timezone.utc)
    for item in (
        db.query(OrderLineItem).filter(OrderLineItem.po_batch_id == batch.id).all()
    ):
        if item.status == "submitted":
            transition(db, item.id, "pending_fulfillment",
                       {"rithum_fulfillment_id": batch.rithum_fulfillment_id})
    db.commit()
    return True


def _send_batch(
    connector,
    rithum: RithumClient,
    batch: POBatch,
    vendor: Vendor,
    db: Session,
) -> bool:
    """Send one POBatch to its vendor. Handles shadow mode. Returns success."""
    line_dicts = _line_dicts_for_batch(db, batch)
    if not line_dicts:
        logger.warning("POBatch %s has no line items — skipping", batch.po_number)
        return False

    # Vendor-specific pre-flight validation (e.g. REV'IT requires EAN)
    errors = connector.validate_line_items(line_dicts)
    if errors:
        msg = "; ".join(errors)
        logger.warning(
            "POBatch %s failed validation: %s", batch.po_number, msg,
        )
        batch.status = "failed"
        batch.last_error = f"validation: {msg}"[:2000]
        for item in (
            db.query(OrderLineItem)
            .filter(OrderLineItem.po_batch_id == batch.id)
            .all()
        ):
            try:
                transition(db, item.id, "failed", {"error": msg})
            except Exception:
                pass
        db.commit()
        return False

    # Capture the payload for audit before sending
    try:
        payload = connector.build_payload(batch.po_number, line_dicts)
        if payload:
            batch.file_content = payload
            db.commit()
    except Exception:
        logger.exception(
            "Failed to capture payload for PO %s (continuing send anyway)",
            batch.po_number,
        )

    try:
        ok = connector.place_order(batch.po_number, line_dicts)
    except Exception as e:
        logger.exception(
            "Connector %s.place_order failed for PO %s",
            vendor.connector_type, batch.po_number,
        )
        batch.status = "failed"
        batch.last_error = str(e)[:2000]
        for item in (
            db.query(OrderLineItem)
            .filter(OrderLineItem.po_batch_id == batch.id)
            .all()
        ):
            try:
                transition(db, item.id, "failed", {"error": str(e)})
            except Exception:
                pass
        db.commit()
        return False

    if not ok:
        logger.warning(
            "Connector returned False for PO %s (%s)",
            batch.po_number, vendor.code,
        )
        return False

    # Connector accepted the PO
    batch.status = "sent"
    batch.sent_at = datetime.now(timezone.utc)
    for item in (
        db.query(OrderLineItem).filter(OrderLineItem.po_batch_id == batch.id).all()
    ):
        if item.status == "pending":
            transition(db, item.id, "submitted",
                       {"po_number": batch.po_number, "vendor": vendor.code})
    db.commit()

    logger.info(
        "Sent PO %s to %s (%d items)",
        batch.po_number, vendor.code, batch.line_count,
    )

    # Skip the Rithum mutation in shadow mode (global or per-vendor)
    if shadow.is_shadow(vendor.config_json):
        logger.info(
            "SHADOW (%s): not marking Rithum fulfillment %d Pending",
            shadow.reason(vendor.config_json),
            batch.rithum_fulfillment_id,
        )
        return True

    return _mark_rithum_pending(rithum, batch, db)


def run():
    """Send any POBatches that are pending or half-submitted."""
    db: Session = SessionLocal()
    job = JobRun(job_name="place_orders")
    db.add(job)
    db.commit()

    sent = 0
    resumed = 0

    try:
        rithum = RithumClient()
        rithum.authenticate()

        # 1) Finish half-done batches: connector succeeded but Rithum mark didn't.
        # Skip vendors still in shadow (global or per-vendor).
        for batch in (
            db.query(POBatch)
            .filter(POBatch.status == "sent")
            .order_by(POBatch.sent_at)
            .all()
        ):
            vendor = db.query(Vendor).get(batch.vendor_id)
            if vendor and not shadow.is_shadow(vendor.config_json):
                if _mark_rithum_pending(rithum, batch, db):
                    resumed += 1

        # 2) Fresh pending batches
        pending_batches = (
            db.query(POBatch)
            .filter(POBatch.status == "pending")
            .order_by(POBatch.created_at)
            .all()
        )
        for batch in pending_batches:
            vendor = db.query(Vendor).get(batch.vendor_id)
            if not vendor or not vendor.is_active:
                continue
            connector = get_connector(
                vendor.connector_type, vendor.code, vendor.config_json,
            )
            if _send_batch(connector, rithum, batch, vendor, db):
                sent += 1

        job.items_processed = sent
        job.status = "success"
        job.details_json = {"sent": sent, "resumed_rithum_mark": resumed}
        logger.info(
            "place_orders done: sent %d, resumed rithum-mark on %d",
            sent, resumed,
        )

    except Exception as e:
        logger.exception("place_orders failed: %s", e)
        job.status = "failed"
        job.error_message = str(e)
        db.rollback()

    finally:
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.close()
