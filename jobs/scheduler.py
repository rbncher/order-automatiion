"""APScheduler setup and job registration."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from jobs import poll_rithum, place_orders, retrieve_tracking, post_tracking, reconciliation

logger = logging.getLogger(__name__)


def create_scheduler() -> BackgroundScheduler:
    """Create and configure the job scheduler."""
    scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,          # If multiple runs missed, only run once
            "max_instances": 1,        # Never run same job concurrently
            "misfire_grace_time": 300,  # 5 min grace for missed jobs
        },
    )

    # Poll Rithum for unshipped orders — every 15 minutes
    scheduler.add_job(
        poll_rithum.run,
        trigger=IntervalTrigger(minutes=15),
        id="poll_rithum",
        name="Poll Rithum for unshipped orders",
        replace_existing=True,
    )

    # Place orders with vendors — every 15 minutes (offset by 5 min)
    scheduler.add_job(
        place_orders.run,
        trigger=IntervalTrigger(minutes=15, start_date="2026-01-01 00:05:00"),
        id="place_orders",
        name="Submit POs to vendors",
        replace_existing=True,
    )

    # Retrieve tracking from vendors — every 2 hours
    scheduler.add_job(
        retrieve_tracking.run,
        trigger=IntervalTrigger(hours=2),
        id="retrieve_tracking",
        name="Retrieve tracking from vendors",
        replace_existing=True,
    )

    # Post tracking to Rithum — every 15 minutes
    scheduler.add_job(
        post_tracking.run,
        trigger=IntervalTrigger(minutes=15, start_date="2026-01-01 00:10:00"),
        id="post_tracking",
        name="Post tracking to Rithum",
        replace_existing=True,
    )

    # Reconciliation — every hour
    scheduler.add_job(
        reconciliation.run,
        trigger=IntervalTrigger(hours=1),
        id="reconciliation",
        name="Reconciliation check",
        replace_existing=True,
    )

    logger.info("Scheduler configured with %d jobs", len(scheduler.get_jobs()))
    return scheduler
