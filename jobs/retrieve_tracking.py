"""Ask each vendor for tracking on POs still awaiting fulfillment.

Targets POBatches with status='pending_fulfillment'. On match, updates
the batch (tracking_number, carrier, shipped_at, status='shipped'),
transitions line items to 'shipped', and leaves the Rithum writeback
to post_tracking.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.models import Vendor, OrderLineItem, POBatch, JobRun
from core.state_machine import transition
from connectors.registry import get_connector

logger = logging.getLogger(__name__)


def _apply_tracking(db: Session, batch: POBatch, tracking) -> int:
    """Apply a TrackingInfo to a POBatch + its line items. Return items advanced."""
    ship_date = tracking.ship_date
    shipped_at = (
        datetime.combine(ship_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        if ship_date else datetime.now(timezone.utc)
    )

    batch.tracking_number = tracking.tracking_number
    batch.carrier = tracking.carrier or "Other"
    batch.shipped_at = shipped_at
    batch.status = "shipped"

    advanced = 0
    for item in (
        db.query(OrderLineItem).filter(OrderLineItem.po_batch_id == batch.id).all()
    ):
        item.tracking_number = tracking.tracking_number
        item.carrier = batch.carrier
        item.ship_date = ship_date
        try:
            if item.status in ("submitted", "pending_fulfillment"):
                transition(db, item.id, "shipped", {
                    "tracking_number": tracking.tracking_number,
                    "carrier": batch.carrier,
                    "ship_date": str(ship_date) if ship_date else None,
                })
                advanced += 1
        except Exception:
            logger.exception("Failed to advance item %d to shipped", item.id)
    db.commit()
    return advanced


def run():
    """For each vendor, poll for tracking against its unshipped POBatches."""
    db: Session = SessionLocal()
    job = JobRun(job_name="retrieve_tracking")
    db.add(job)
    db.commit()

    total_tracked = 0

    try:
        vendors = db.query(Vendor).filter(Vendor.is_active == True).all()

        for vendor in vendors:
            awaiting = (
                db.query(POBatch)
                .filter(
                    POBatch.vendor_id == vendor.id,
                    POBatch.status.in_(("sent", "pending_fulfillment")),
                )
                .all()
            )
            if not awaiting:
                continue

            po_numbers = [b.po_number for b in awaiting]
            logger.info(
                "retrieve_tracking: %s — %d POs awaiting", vendor.code, len(po_numbers),
            )

            connector = get_connector(
                vendor.connector_type, vendor.code, vendor.config_json,
            )

            try:
                tracking_list = connector.retrieve_tracking(po_numbers) or []
            except Exception:
                logger.exception("Connector retrieve_tracking failed for %s", vendor.code)
                continue

            if not tracking_list:
                logger.info("No new tracking from %s", vendor.code)
                continue

            # Index POBatches by po_number for matching
            by_po = {b.po_number: b for b in awaiting}
            for t in tracking_list:
                batch = by_po.get(t.po_number)
                if not batch:
                    continue
                total_tracked += _apply_tracking(db, batch, t)

        job.items_processed = total_tracked
        job.status = "success"
        logger.info("retrieve_tracking done: %d items advanced", total_tracked)

    except Exception as e:
        logger.exception("retrieve_tracking failed: %s", e)
        job.status = "failed"
        job.error_message = str(e)
        db.rollback()

    finally:
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.close()
