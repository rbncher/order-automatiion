"""Connector discovery and instantiation."""
import logging
from connectors.base import VendorConnector
from connectors.revit.connector import RevitConnector

logger = logging.getLogger(__name__)

# Map connector_type to class
CONNECTOR_CLASSES: dict[str, type[VendorConnector]] = {
    "revit_sftp": RevitConnector,
    # "email_pdf": EmailPdfConnector,  # Phase 2
    # "api": ApiConnector,             # Phase 3
}


def get_connector(connector_type: str, vendor_code: str, vendor_config: dict) -> VendorConnector:
    """Instantiate a vendor connector by type."""
    cls = CONNECTOR_CLASSES.get(connector_type)
    if not cls:
        raise ValueError(f"Unknown connector type: {connector_type}")
    return cls(vendor_code=vendor_code, vendor_config=vendor_config)
