"""Tests for the order line item state machine."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.models import Vendor, OrderLineItem, AuditLog
from core.state_machine import transition, InvalidTransitionError

# Use in-memory SQLite for tests
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine)


@pytest.fixture
def db():
    session = TestSession()
    # Create test vendor
    vendor = Vendor(code="TEST", name="Test Vendor", connector_type="test")
    session.add(vendor)
    session.flush()

    yield session, vendor

    session.rollback()
    session.close()


def _create_item(session, vendor, status="pending"):
    item = OrderLineItem(
        rithum_order_id=1,
        rithum_item_id=100,
        rithum_fulfillment_id=1000,
        dc_id=30,
        idempotency_key=f"rithum:1000:100:{status}",
        vendor_id=vendor.id,
        sku="TEST-SKU",
        quantity=1,
        status=status,
    )
    session.add(item)
    session.flush()
    return item


def test_valid_transitions(db):
    session, vendor = db

    # pending -> submitted
    item = _create_item(session, vendor, "pending")
    result = transition(session, item.id, "submitted", {"po": "PO-001"})
    assert result.status == "submitted"
    assert result.submitted_at is not None

    # Check audit log
    audit = session.query(AuditLog).filter(
        AuditLog.entity_id == item.id,
    ).first()
    assert audit is not None
    assert audit.old_value == "pending"
    assert audit.new_value == "submitted"


def test_invalid_transition(db):
    session, vendor = db

    item = _create_item(session, vendor, "pending")
    with pytest.raises(InvalidTransitionError):
        transition(session, item.id, "complete")


def test_failure_stores_error(db):
    session, vendor = db

    item = _create_item(session, vendor, "pending")
    transition(session, item.id, "failed", {"error": "SFTP timeout"})
    assert item.status == "failed"
    assert item.last_error == "SFTP timeout"


def test_retry_increments_count(db):
    session, vendor = db

    item = _create_item(session, vendor, "pending")
    transition(session, item.id, "failed", {"error": "test"})
    assert item.retry_count == 0

    # Reset idempotency key for re-creation workaround
    transition(session, item.id, "pending")
    assert item.retry_count == 1
    assert item.status == "pending"


def test_full_lifecycle(db):
    session, vendor = db

    item = _create_item(session, vendor, "pending")
    transition(session, item.id, "submitted")
    transition(session, item.id, "shipped")
    transition(session, item.id, "tracking_posted")
    transition(session, item.id, "complete")
    assert item.status == "complete"
    assert item.completed_at is not None

    # Should have 4 audit entries
    audits = session.query(AuditLog).filter(
        AuditLog.entity_id == item.id,
    ).all()
    assert len(audits) == 4
