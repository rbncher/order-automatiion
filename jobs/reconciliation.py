"""Reconciliation job — detect stuck, missing, or orphaned orders."""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.models import JobRun
from core.safety import get_stuck_orders

logger = logging.getLogger(__name__)


def run():
    """Check for stuck or missing orders and log alerts."""
    db: Session = SessionLocal()
    job = JobRun(job_name="reconciliation")
    db.add(job)
    db.commit()

    try:
        issues = get_stuck_orders(db, pending_hours=2, submitted_hours=48)
        total_issues = sum(len(v) for v in issues.values())

        if issues:
            logger.warning("Reconciliation found %d issues:", total_issues)
            for category, items in issues.items():
                logger.warning("  %s: %d items", category, len(items))
                for item in items[:5]:  # log first 5
                    logger.warning("    %s", item)
                if len(items) > 5:
                    logger.warning("    ... and %d more", len(items) - 5)
        else:
            logger.info("Reconciliation: no issues found")

        job.items_processed = total_issues
        job.status = "success"
        job.details_json = issues if issues else None

    except Exception as e:
        logger.exception("Reconciliation failed: %s", e)
        job.status = "failed"
        job.error_message = str(e)

    finally:
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.close()
