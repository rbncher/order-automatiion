"""Pydantic schemas for API and internal data transfer."""
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel


class OrderLineItemCreate(BaseModel):
    rithum_order_id: int
    rithum_item_id: int
    vendor_id: int
    site_order_id: str | None = None
    sku: str
    ean: str | None = None
    mpn: str | None = None
    title: str | None = None
    quantity: int
    unit_price: Decimal | None = None
    ship_to_name: str | None = None
    ship_to_address1: str | None = None
    ship_to_address2: str | None = None
    ship_to_city: str | None = None
    ship_to_state: str | None = None
    ship_to_postal: str | None = None
    ship_to_country: str | None = None
    ship_to_email: str | None = None
    ship_to_phone: str | None = None
    requested_carrier: str | None = None
    requested_class: str | None = None


class OrderLineItemResponse(BaseModel):
    id: int
    rithum_order_id: int
    rithum_item_id: int
    vendor_code: str | None = None
    sku: str
    ean: str | None = None
    quantity: int
    status: str
    po_number: str | None = None
    tracking_number: str | None = None
    carrier: str | None = None
    ship_date: date | None = None
    created_at: datetime
    updated_at: datetime
    last_error: str | None = None
    retry_count: int = 0

    class Config:
        from_attributes = True


class TrackingInfo(BaseModel):
    """Tracking data returned by a vendor connector."""
    po_number: str
    sku: str | None = None
    ean: str | None = None
    tracking_number: str
    carrier: str | None = None
    ship_date: date | None = None
    quantity: int | None = None


class VendorHealth(BaseModel):
    code: str
    name: str
    connector_type: str
    is_active: bool
    pending_count: int = 0
    submitted_count: int = 0
    failed_count: int = 0
    last_order_at: datetime | None = None


class DashboardStats(BaseModel):
    total_orders_today: int = 0
    total_pending: int = 0
    total_submitted: int = 0
    total_shipped: int = 0
    total_complete: int = 0
    total_failed: int = 0
    vendors: list[VendorHealth] = []
