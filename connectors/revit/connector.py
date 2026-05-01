"""REV'IT vendor connector — SFTP-based EDI order placement + email tracking."""
import logging
from datetime import date

import config
from clients.sftp import SFTPClient
from connectors.base import VendorConnector
from connectors.revit.edi_formatter import format_order
from connectors.revit.invoice_parser import parse_invoice_csv, group_tracking_by_po
from connectors.revit.stock_parser import parse_stock_file
from core import shadow
from core.schemas import TrackingInfo

logger = logging.getLogger(__name__)


class RevitConnector(VendorConnector):
    """REV'IT integration via SFTP EDI + email invoice tracking."""

    def __init__(self, vendor_code: str = "REV", vendor_config: dict | None = None):
        cfg = vendor_config or {}
        super().__init__(vendor_code, cfg)

        # SFTP config (from vendor config or env vars)
        self.sftp_host = cfg.get("sftp_host") or config.REVIT_SFTP_HOST
        self.sftp_user = cfg.get("sftp_user") or config.REVIT_SFTP_USER
        self.sftp_pass = cfg.get("sftp_pass") or config.REVIT_SFTP_PASS
        self.sftp_port = int(cfg.get("sftp_port", config.REVIT_SFTP_PORT))
        self.order_dir = cfg.get("sftp_order_dir") or config.REVIT_SFTP_ORDER_DIR
        self.stock_dir = cfg.get("sftp_stock_dir") or config.REVIT_SFTP_STOCK_DIR

        # REV'IT customer config
        self.sell_to_customer = cfg.get("sell_to_customer") or config.REVIT_SELL_TO_CUSTOMER
        self.bill_to_customer = cfg.get("bill_to_customer") or config.REVIT_BILL_TO_CUSTOMER
        self.currency = cfg.get("currency") or config.REVIT_CURRENCY
        self.shipping_agent = cfg.get("shipping_agent") or config.REVIT_SHIPPING_AGENT
        self.shipping_service_code = cfg.get("shipping_service_code") or config.REVIT_SHIPPING_SERVICE_CODE

    def _get_sftp(self) -> SFTPClient:
        return SFTPClient(
            host=self.sftp_host,
            username=self.sftp_user,
            password=self.sftp_pass,
            port=self.sftp_port,
        )

    def validate_line_items(self, line_items: list[dict]) -> list[str]:
        """REV'IT requires a 13-digit numeric EAN on every line plus a ship-to
        with street address. REV'IT's EDI processor rejects the whole order if
        any EAN is missing or malformed, so we fail fast here."""
        errors: list[str] = []
        for i, item in enumerate(line_items, start=1):
            sku = item.get("sku") or f"line {i}"
            ean = (item.get("ean") or "").strip()
            if not ean:
                errors.append(f"Missing EAN for SKU {sku}")
            elif len(ean) != 13 or not ean.isdigit():
                errors.append(
                    f"Invalid EAN for SKU {sku}: {ean!r} (must be 13 digits)"
                )
        if line_items:
            first = line_items[0]
            if not (first.get("ship_to_name") or "").strip():
                errors.append("Missing ship-to name")
            if not (first.get("ship_to_address1") or "").strip():
                errors.append("Missing ship-to address")
            if not (first.get("ship_to_country") or "").strip():
                errors.append("Missing ship-to country")
        return errors

    def build_payload(self, po_number: str, line_items: list[dict]) -> str:
        """Build the REV'IT EDI CSV for a PO without sending it."""
        if not line_items:
            raise ValueError("Cannot build payload for empty order")

        first = line_items[0]
        ship_to = {
            "name1": first.get("ship_to_name", ""),
            "address1": first.get("ship_to_address1", ""),
            "address2": first.get("ship_to_address2", ""),
            "city": first.get("ship_to_city", ""),
            "postal": first.get("ship_to_postal", ""),
            "country": first.get("ship_to_country", ""),
            "state": first.get("ship_to_state", ""),
            "email": first.get("ship_to_email", ""),
            "phone": first.get("ship_to_phone", ""),
        }

        edi_items = []
        for item in line_items:
            # Parse variant code from MPN: e.g. "FAR039-0410-L" -> variant "0410-L"
            mpn = item.get("mpn", "")
            parts = mpn.split("-", 1) if mpn else []
            item_no = parts[0] if parts else ""
            variant_code = parts[1] if len(parts) > 1 else ""

            variant_parts = variant_code.split("-", 1) if variant_code else []
            colour_code = variant_parts[0] if variant_parts else ""
            size_code = variant_parts[1] if len(variant_parts) > 1 else ""

            edi_items.append({
                "ean": item.get("ean", ""),
                "description1": item.get("title", "")[:35],
                "description2": "",
                "quantity": item["quantity"],
                "unit_price": item.get("unit_price"),
                "item_no": item_no,
                "variant_code": variant_code,
                "colour_code": colour_code,
                "size_code": size_code,
            })

        return format_order(
            po_number=po_number,
            order_date=date.today(),
            sell_to_customer=self.sell_to_customer,
            line_items=edi_items,
            ship_to=ship_to,
            bill_to_customer=self.bill_to_customer,
            currency=self.currency,
            order_type=2,  # Dropship
            shipping_agent=self.shipping_agent,
            shipping_agent_service_code=self.shipping_service_code,
        )

    def place_order(self, po_number: str, line_items: list[dict]) -> bool:
        """Generate EDI CSV and upload to REV'IT SFTP."""
        csv_content = self.build_payload(po_number, line_items)

        if shadow.is_shadow(self.config):
            logger.info(
                "SHADOW (%s): Would upload PO %s to REV'IT SFTP (%d items)\n%s",
                shadow.reason(self.config),
                po_number, len(line_items), csv_content,
            )
            return True

        # Upload to SFTP
        filename = f"{po_number}.csv"
        remote_path = f"{self.order_dir}/{filename}"

        with self._get_sftp() as sftp:
            sftp.upload_string(csv_content, remote_path)

        logger.info("Uploaded PO %s to REV'IT SFTP: %s", po_number, remote_path)
        return True

    def retrieve_tracking(self, po_numbers: list[str]) -> list[TrackingInfo]:
        """
        Retrieve tracking from REV'IT invoice CSV.

        For now, this expects the CSV content to be provided externally
        (via email parsing). In future, could also check SFTP for invoice files.
        """
        # This will be called by the email-based tracking job
        # which passes CSV content. For SFTP-based retrieval:
        try:
            with self._get_sftp() as sftp:
                invoice_dir = f"{self.stock_dir}/invoices"
                files = sftp.list_dir(invoice_dir)
                results = []
                for f in files:
                    if f.endswith(".csv"):
                        content = sftp.download_string(f"{invoice_dir}/{f}")
                        tracking = parse_invoice_csv(content)
                        # Filter to only our PO numbers
                        for t in tracking:
                            if t.po_number in po_numbers:
                                results.append(t)
                return results
        except Exception as e:
            logger.warning("Could not retrieve tracking from SFTP: %s", e)
            return []

    def retrieve_tracking_from_csv(self, csv_content: str, po_numbers: list[str]) -> list[TrackingInfo]:
        """Parse tracking from a provided CSV string (e.g., from email attachment)."""
        all_tracking = parse_invoice_csv(csv_content)
        return [t for t in all_tracking if t.po_number in po_numbers]

    def check_health(self) -> dict:
        """Test SFTP connectivity."""
        if not self.sftp_host:
            return {"ok": False, "error": "SFTP host not configured"}
        try:
            sftp = self._get_sftp()
            ok = sftp.check_health()
            return {"ok": ok}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def fetch_uploaded_order(self, po_number: str) -> str | None:
        """Download a previously-uploaded PO CSV from REV'IT SFTP (if still present).

        REV'IT moves processed files into `/Speed Addicts/_Imported` and errors
        into `/Speed Addicts/_Error`. Check the drop folder first, then both.
        """
        filename = f"{po_number}.csv"
        candidates = [
            f"{self.order_dir}/{filename}",
            f"{self.order_dir}/_Imported/{filename}",
            f"{self.order_dir}/_Error/{filename}",
        ]
        try:
            with self._get_sftp() as sftp:
                for path in candidates:
                    try:
                        return sftp.download_string(path)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("Could not connect to REV'IT SFTP to fetch %s: %s",
                           po_number, e)
        return None

    def check_stock(self, eans: list[str]) -> dict[str, dict] | None:
        """Download and parse REV'IT stock file from SFTP."""
        try:
            with self._get_sftp() as sftp:
                content = sftp.download_string(f"{self.stock_dir}/stock_revit_rsu.csv")
                all_stock = parse_stock_file(content)
                if eans:
                    return {ean: all_stock[ean] for ean in eans if ean in all_stock}
                return all_stock
        except Exception as e:
            logger.warning("Could not fetch stock from REV'IT: %s", e)
            return None
