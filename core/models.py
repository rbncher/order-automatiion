"""SQLAlchemy ORM models for all tables."""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, Text, Numeric, Date,
    DateTime, ForeignKey, Index, UniqueConstraint, JSON,
)
from sqlalchemy.orm import relationship
from core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)          # 'REV', 'TUCKER', etc.
    name = Column(String(100), nullable=False)
    connector_type = Column(String(50), nullable=False)             # 'revit_sftp', 'email_pdf', 'api'
    config_json = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    order_line_items = relationship("OrderLineItem", back_populates="vendor")
    po_batches = relationship("POBatch", back_populates="vendor")


class OrderLineItem(Base):
    """Central state machine table — one row per Rithum line item routed to a vendor."""
    __tablename__ = "order_line_items"
    __table_args__ = (
        UniqueConstraint("rithum_order_id", "rithum_item_id", name="uq_rithum_line"),
        Index("idx_oli_status", "status"),
        Index("idx_oli_vendor", "vendor_id", "status"),
        Index("idx_oli_po", "po_number"),
        Index("idx_oli_fulfillment", "rithum_fulfillment_id"),
        Index("idx_oli_created", "created_at"),
    )

    id = Column(Integer, primary_key=True)

    # Rithum identifiers
    rithum_order_id = Column(Integer, nullable=False)
    rithum_item_id = Column(Integer, nullable=False)
    rithum_fulfillment_id = Column(Integer, nullable=False)
    dc_id = Column(Integer, nullable=False)
    idempotency_key = Column(String(100), unique=True, nullable=False)  # rithum:{fulfillment_id}:{item_id}

    # Vendor
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)

    # Rithum order data snapshot
    site_order_id = Column(String(50))              # marketplace order ID
    sku = Column(String(100), nullable=False)
    ean = Column(String(13))
    mpn = Column(String(50))                        # vendor article code
    title = Column(String(300))
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2))

    # Ship-to
    ship_to_name = Column(String(200))
    ship_to_address1 = Column(String(200))
    ship_to_address2 = Column(String(200))
    ship_to_city = Column(String(100))
    ship_to_state = Column(String(50))
    ship_to_postal = Column(String(20))
    ship_to_country = Column(String(10))
    ship_to_email = Column(String(200))
    ship_to_phone = Column(String(50))

    # Shipping
    requested_carrier = Column(String(50))
    requested_class = Column(String(50))

    # PO reference
    po_number = Column(String(50))
    po_batch_id = Column(Integer, ForeignKey("po_batches.id"), nullable=True)

    # State machine
    status = Column(String(30), nullable=False, default="pending")
    # pending -> submitted -> pending_fulfillment -> shipped -> tracking_posted -> complete
    # pending -> failed; any -> cancelled

    # Tracking
    tracking_number = Column(String(100))
    carrier = Column(String(50))
    ship_date = Column(Date)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    submitted_at = Column(DateTime(timezone=True))
    shipped_at = Column(DateTime(timezone=True))
    tracking_posted_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    # Error tracking
    retry_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)

    vendor = relationship("Vendor", back_populates="order_line_items")
    po_batch = relationship("POBatch", back_populates="line_items")


class POBatch(Base):
    """One outbound PO per Rithum Fulfillment."""
    __tablename__ = "po_batches"
    __table_args__ = (
        Index("idx_pob_fulfillment", "rithum_fulfillment_id", unique=True),
        Index("idx_pob_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    rithum_fulfillment_id = Column(Integer, nullable=False)
    rithum_order_id = Column(Integer, nullable=False)
    po_number = Column(String(50), unique=True, nullable=False)
    file_name = Column(String(200))
    file_content = Column(Text)                     # full payload for audit/replay
    line_count = Column(Integer, nullable=False)
    total_quantity = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    # pending -> sent -> pending_fulfillment -> shipped -> complete | failed
    sent_at = Column(DateTime(timezone=True))
    pending_marked_at = Column(DateTime(timezone=True))
    tracking_number = Column(String(100))
    carrier = Column(String(50))
    shipped_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    vendor = relationship("Vendor", back_populates="po_batches")
    line_items = relationship("OrderLineItem", back_populates="po_batch")


class AuditLog(Base):
    """Every state change and external call."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(30), nullable=False)    # 'order_line_item', 'po_batch'
    entity_id = Column(Integer, nullable=False)
    action = Column(String(50), nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    details_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_by = Column(String(50), default="system")

    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_created", "created_at"),
    )


class JobRun(Base):
    """Scheduler execution history for health dashboard."""
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String(50), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False, default="running")
    items_processed = Column(Integer, default=0)
    error_message = Column(Text)
    details_json = Column(JSON)

    __table_args__ = (
        Index("idx_job_runs_name", "job_name", "started_at"),
    )
