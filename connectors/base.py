"""Abstract base class for vendor connectors."""
from abc import ABC, abstractmethod

from core.schemas import TrackingInfo


class VendorConnector(ABC):
    """Every vendor integration implements this interface."""

    def __init__(self, vendor_code: str, vendor_config: dict):
        self.vendor_code = vendor_code
        self.config = vendor_config

    @abstractmethod
    def place_order(self, po_number: str, line_items: list[dict]) -> bool:
        """
        Submit a purchase order to the vendor.

        line_items: list of dicts with keys: ean, mpn, sku, quantity, unit_price,
            ship_to_name, ship_to_address1, etc.

        Returns True on successful submission.
        Raises on failure.
        """

    @abstractmethod
    def retrieve_tracking(self, po_numbers: list[str]) -> list[TrackingInfo]:
        """
        Check for new tracking info from vendor for the given PO numbers.
        Returns list of TrackingInfo objects.
        """

    @abstractmethod
    def check_health(self) -> dict:
        """Return connectivity/health status. Must include 'ok': bool."""

    def check_stock(self, eans: list[str]) -> dict[str, dict] | None:
        """Optional: check stock availability. Returns {ean: {available: bool, qty: int}}."""
        return None

    def build_payload(self, po_number: str, line_items: list[dict]) -> str | None:
        """Optional: return the exact payload (CSV/EDI/email body) that place_order
        would send. Used by the dashboard for audit preview. Default: None."""
        return None

    def validate_line_items(self, line_items: list[dict]) -> list[str]:
        """Return a list of human-readable validation errors for the batch.

        Empty list = passes. Default: no validation. Subclasses override with
        vendor-specific required fields (e.g. REV'IT requires EAN)."""
        return []
