"""Order line item state machine — single point of state mutation."""
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from core.models import OrderLineItem, AuditLog

logger = logging.getLogger(__name__)

VALID_TRANSITIONS = {
    "pending":              ["submitted", "failed", "cancelled"],
    "submitted":            ["pending_fulfillment", "shipped", "failed", "cancelled"],
    "pending_fulfillment":  ["shipped", "failed", "cancelled"],
    "shipped":              ["tracking_posted", "failed"],
    "tracking_posted":      ["complete", "failed"],
    "failed":               ["pending"],  # retry resets to pending
}

# Map status -> timestamp field to set
STATUS_TIMESTAMP = {
    "submitted": "submitted_at",
    "shipped": "shipped_at",
    "tracking_posted": "tracking_posted_at",
    "complete": "completed_at",
}


class InvalidTransitionError(Exception):
    pass


def transition(
    db: Session,
    line_item_id: int,
    new_status: str,
    details: dict | None = None,
    created_by: str = "system",
) -> OrderLineItem:
    """
    Transition a line item to a new status.

    Acquires a row lock (SELECT FOR UPDATE), validates the transition,
    updates the status + timestamp, and writes an audit log entry.
    All in the caller's transaction.
    """
    # Row lock to prevent concurrent mutations
    item = (
        db.query(OrderLineItem)
        .filter(OrderLineItem.id == line_item_id)
        .with_for_update()
        .one()
    )

    old_status = item.status

    # Validate transition
    allowed = VALID_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition order_line_item {line_item_id} "
            f"from '{old_status}' to '{new_status}'. "
            f"Allowed: {allowed}"
        )

    # Update status
    item.status = new_status
    item.updated_at = datetime.now(timezone.utc)

    # Set the relevant timestamp
    ts_field = STATUS_TIMESTAMP.get(new_status)
    if ts_field:
        setattr(item, ts_field, datetime.now(timezone.utc))

    # On retry (failed -> pending), increment retry count
    if old_status == "failed" and new_status == "pending":
        item.retry_count += 1

    # On failure, store the error message
    if new_status == "failed" and details and "error" in details:
        item.last_error = details["error"]

    # Audit log
    audit = AuditLog(
        entity_type="order_line_item",
        entity_id=line_item_id,
        action="status_change",
        old_value=old_status,
        new_value=new_status,
        details_json=details,
        created_by=created_by,
    )
    db.add(audit)

    logger.info(
        "order_line_item %d: %s -> %s (by %s)",
        line_item_id, old_status, new_status, created_by,
    )

    return item
