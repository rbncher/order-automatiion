"""Ask each vendor for tracking on POs still awaiting fulfillment.

Targets POBatches with status='pending_fulfillment'. On match, updates
the batch (tracking_number, carrier, shipped_at, status='shipped'),
transitions line items to 'shipped', and leaves the Rithum writeback
to post_tracking.
"""
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.models import Vendor, OrderLineItem, POBatch, JobRun
from core.state_machine import transition
from connectors.registry import get_connector

logger = logging.getLogger(__name__)


def _apply_tracking(db: Session, batch: POBatch, tracking_records: list) -> int:
    """Apply all tracking records for one POBatch.

    Each line item is matched to its specific tracking by EAN; the POBatch
    itself stores the "primary" tracking (the one covering the most line
    items). Multi-box shipments are logged so we can surface the gap until
    the schema supports per-batch tracking arrays.
    """
    if not tracking_records:
        return 0

    by_ean = {t.ean: t for t in tracking_records if t.ean}
    by_sku = {t.sku: t for t in tracking_records if t.sku}

    distinct_trackings = sorted({t.tracking_number for t in tracking_records})
    if len(distinct_trackings) > 1:
        logger.warning(
            "PO %s: split shipment — %d distinct trackings %s. Line items get "
            "per-EAN tracking; POBatch.tracking_number stores primary only.",
            batch.po_number, len(distinct_trackings), distinct_trackings,
        )

    # Primary = tracking covering the most line items (stable tiebreak by value)
    counts: dict[str, int] = defaultdict(int)
    for t in tracking_records:
        counts[t.tracking_number] += 1
    primary_num = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    primary = next(t for t in tracking_records if t.tracking_number == primary_num)

    earliest_ship = min(
        (t.ship_date for t in tracking_records if t.ship_date),
        default=None,
    )
    shipped_at = (
        datetime.combine(earliest_ship, datetime.min.time()).replace(tzinfo=timezone.utc)
        if earliest_ship else datetime.now(timezone.utc)
    )

    batch.tracking_number = primary.tracking_number
    batch.carrier = primary.carrier or "Other"
    batch.shipped_at = shipped_at
    batch.status = "shipped"

    advanced = 0
    for item in (
        db.query(OrderLineItem).filter(OrderLineItem.po_batch_id == batch.id).all()
    ):
        match = (
            (by_ean.get(item.ean) if item.ean else None)
            or (by_sku.get(item.sku) if item.sku else None)
            or primary
        )
        item.tracking_number = match.tracking_number
        item.carrier = match.carrier or batch.carrier
        item.ship_date = match.ship_date or earliest_ship
        try:
            if item.status in ("submitted", "pending_fulfillment"):
                transition(db, item.id, "shipped", {
                    "tracking_number": match.tracking_number,
                    "carrier": item.carrier,
                    "ship_date": str(item.ship_date) if item.ship_date else None,
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

            batches_by_po = {b.po_number: b for b in awaiting}
            trackings_by_po: dict[str, list] = defaultdict(list)
            for t in tracking_list:
                if t.po_number in batches_by_po:
                    trackings_by_po[t.po_number].append(t)
            for po_number, recs in trackings_by_po.items():
                total_tracked += _apply_tracking(
                    db, batches_by_po[po_number], recs,
                )

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
