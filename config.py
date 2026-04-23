"""Central configuration — env vars, constants, API URLs."""
import os

# ---------------------------------------------------------------------------
# Rithum / ChannelAdvisor API
# ---------------------------------------------------------------------------
RITHUM_APP_ID = os.environ.get("RITHUM_APP_ID", "")
RITHUM_SECRET = os.environ.get("RITHUM_SECRET", "")
RITHUM_REFRESH_TOKEN = os.environ.get("RITHUM_REFRESH_TOKEN", "")

RITHUM_TOKEN_URL = "https://api.channeladvisor.com/oauth2/token"
RITHUM_API_BASE = "https://api.channeladvisor.com/v1"
RITHUM_PROFILE_ID = 12022010

RITHUM_PAGE_SIZE = 250
RITHUM_RATE_LIMIT_SLEEP = 10  # seconds on 429
RITHUM_MAX_RETRIES = 6

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///order_automation.db",  # dev default; use postgres in prod
)

# ---------------------------------------------------------------------------
# REV'IT SFTP (populated per-vendor via vendors table, but env fallback)
# ---------------------------------------------------------------------------
REVIT_SFTP_HOST = os.environ.get("REVIT_SFTP_HOST", "")
REVIT_SFTP_USER = os.environ.get("REVIT_SFTP_USER", "")
REVIT_SFTP_PASS = os.environ.get("REVIT_SFTP_PASS", "")
REVIT_SFTP_PORT = int(os.environ.get("REVIT_SFTP_PORT", "22"))
REVIT_SFTP_ORDER_DIR = os.environ.get("REVIT_SFTP_ORDER_DIR", "/Speed Addicts")
REVIT_SFTP_STOCK_DIR = os.environ.get("REVIT_SFTP_STOCK_DIR", "/")
REVIT_SELL_TO_CUSTOMER = os.environ.get("REVIT_SELL_TO_CUSTOMER", "")
REVIT_BILL_TO_CUSTOMER = os.environ.get("REVIT_BILL_TO_CUSTOMER", "")
REVIT_CURRENCY = os.environ.get("REVIT_CURRENCY", "USD")
REVIT_SHIPPING_AGENT = os.environ.get("REVIT_SHIPPING_AGENT", "FEDEX")
# 15=Ground, 13=2-day Air, 11=Standard Overnight, 16=Home Delivery, 18=Express Saver
REVIT_SHIPPING_SERVICE_CODE = os.environ.get("REVIT_SHIPPING_SERVICE_CODE", "15")

# ---------------------------------------------------------------------------
# Email (for tracking retrieval & email PO workflow)
# ---------------------------------------------------------------------------
IMAP_HOST = os.environ.get("IMAP_HOST", "")
IMAP_USER = os.environ.get("IMAP_USER", "")  # invoices@speedaddicts.com
IMAP_PASS = os.environ.get("IMAP_PASS", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

# ---------------------------------------------------------------------------
# Gmail API (outbound PO emails from dropship@speedaddicts.com)
# ---------------------------------------------------------------------------
GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "")
GMAIL_SEND_AS = os.environ.get("GMAIL_SEND_AS", "dropship@speedaddicts.com")

# ---------------------------------------------------------------------------
# Leatt (email delivery)
# ---------------------------------------------------------------------------
# During testing route to schad@speedaddicts.com; swap to real intake for prod.
LEATT_EMAIL_TO = os.environ.get("LEATT_EMAIL_TO", "")
LEATT_EMAIL_CC = os.environ.get("LEATT_EMAIL_CC", "")
LEATT_EMAIL_REPLY_TO = os.environ.get("LEATT_EMAIL_REPLY_TO", "")
LEATT_DEALER_ACCOUNT = os.environ.get("LEATT_DEALER_ACCOUNT", "20874")

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "8000"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
SHADOW_MODE = os.environ.get("SHADOW_MODE", "true").lower() == "true"

SOCKET_PATH = os.environ.get("SOCKET_PATH", "/run/order-automation/order-automation.sock")

# PO number prefix
PO_PREFIX = "SA"
