"""Push tracking back to Rithum per Fulfillment.

Operates on POBatch rows with status='shipped' (set by retrieve_tracking
once we've parsed tracking from the vendor). Posts tracking via
ship_fulfillment which PATCHes the Rithum Fulfillment with
TrackingNumber, ShippingCarrier, ShippedDateUtc and
ExternalFulfillmentStatus='Complete'.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

import config
from clients.rithum import RithumClient
from core.database import SessionLocal
from core.models import OrderLineItem, POBatch, JobRun
from core.state_machine import transition

logger = logging.getLogger(__name__)


def _post_one(rithum: RithumClient, batch: POBatch, db: Session) -> bool:
    tracking = batch.tracking_number
    if not tracking:
        logger.warning("POBatch %s has no tracking_number; skipping", batch.po_number)
        return False

    ship_dt = batch.shipped_at or datetime.now(timezone.utc)
    if ship_dt.tzinfo is None:
        ship_dt = ship_dt.replace(tzinfo=timezone.utc)

    try:
        rithum.ship_fulfillment(
            fulfillment_id=batch.rithum_fulfillment_id,
            tracking_number=tracking,
            carrier=batch.carrier or "Other",
            ship_date=ship_dt.isoformat().replace("+00:00", "Z"),
        )
    except Exception as e:
        logger.exception(
            "Rithum ship_fulfillment failed for PO %s (fulfillment %d)",
            batch.po_number, batch.rithum_fulfillment_id,
        )
        batch.last_error = f"ship: {e}"[:2000]
        db.commit()
        return False

    batch.status = "complete"
    db.commit()

    for item in (
        db.query(OrderLineItem)
        .filter(OrderLineItem.po_batch_id == batch.id)
        .all()
    ):
        try:
            if item.status == "shipped":
                transition(db, item.id, "tracking_posted",
                           {"tracking_number": tracking})
            if item.status == "tracking_posted":
                transition(db, item.id, "complete")
        except Exception:
            logger.exception(
                "Failed to transition item %d after tracking post", item.id,
            )
    db.commit()

    logger.info(
        "Posted tracking to Rithum for PO %s (fulfillment %d): %s",
        batch.po_number, batch.rithum_fulfillment_id, tracking,
    )
    return True


def run():
    """Post tracking for any POBatches marked 'shipped' locally."""
    db: Session = SessionLocal()
    job = JobRun(job_name="post_tracking")
    db.add(job)
    db.commit()

    posted = 0

    try:
        rithum = RithumClient()
        rithum.authenticate()

        batches = (
            db.query(POBatch)
            .filter(POBatch.status == "shipped")
            .order_by(POBatch.shipped_at)
            .all()
        )

        if not batches:
            job.status = "success"
            return

        if config.SHADOW_MODE:
            logger.info(
                "SHADOW MODE: would post tracking for %d batches, skipping",
                len(batches),
            )
            job.status = "success"
            job.details_json = {"shadow_skipped": len(batches)}
            return

        for batch in batches:
            if _post_one(rithum, batch, db):
                posted += 1

        job.items_processed = posted
        job.status = "success"
        logger.info("post_tracking done: %d batches posted", posted)

    except Exception as e:
        logger.exception("post_tracking failed: %s", e)
        job.status = "failed"
        job.error_message = str(e)
        db.rollback()

    finally:
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.close()
