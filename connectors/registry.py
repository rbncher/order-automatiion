"""Connector discovery and instantiation."""
import logging
from connectors.base import VendorConnector
from connectors.email_generic.connector import EmailGenericConnector
from connectors.revit.connector import RevitConnector

logger = logging.getLogger(__name__)

# Map connector_type to class
CONNECTOR_CLASSES: dict[str, type[VendorConnector]] = {
    "revit_sftp": RevitConnector,
    "email_generic": EmailGenericConnector,
    "leatt_email": EmailGenericConnector,  # legacy alias — Leatt uses email_generic
}


def get_connector(connector_type: str, vendor_code: str, vendor_config: dict) -> VendorConnector:
    """Instantiate a vendor connector by type."""
    cls = CONNECTOR_CLASSES.get(connector_type)
    if not cls:
        raise ValueError(f"Unknown connector type: {connector_type}")
    return cls(vendor_code=vendor_code, vendor_config=vendor_config)
