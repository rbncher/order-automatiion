"""Generic email-delivery vendor connector.

Covers any vendor that accepts a dropship PO via a plain email to a fixed
intake address (6D, Airoh, Schuberth, SMK, Leatt, ...). All per-vendor
variation lives in Vendor.config_json; no per-vendor code.

Required config_json keys:
  email_to          destination address

Optional config_json keys:
  vendor_name            human label used in logs (defaults to vendor_code)
  email_cc               CC address
  email_from             send-as address (defaults to GMAIL_SEND_AS)
  reply_to               reply-to address
  buyer_account          dealer/customer number printed in the PO body
  account_label          label for buyer_account field (e.g. "Dealer Account",
                         "Customer #"). Default "Account".
  carrier_preference     e.g. "FedEx Ground"
  special_instructions   free-text notes appended to the email
"""
import logging

import config
from clients.gmail import GmailClient
from connectors.base import VendorConnector
from connectors.email_generic.email_template import (
    format_html, format_plain, format_subject,
)
from core.schemas import TrackingInfo

logger = logging.getLogger(__name__)


class EmailGenericConnector(VendorConnector):
    def __init__(self, vendor_code: str, vendor_config: dict | None = None):
        cfg = vendor_config or {}
        super().__init__(vendor_code, cfg)

        self.vendor_name = cfg.get("vendor_name") or vendor_code
        self.email_to = (cfg.get("email_to") or "").strip()
        self.email_cc = (cfg.get("email_cc") or "").strip()
        self.email_from = cfg.get("email_from") or config.GMAIL_SEND_AS
        # Vendor replies must land in the monitored ops inbox, not dropship@.
        self.reply_to = (cfg.get("reply_to") or config.OPS_EMAIL or "").strip()

        self.carrier_preference = (cfg.get("carrier_preference") or "").strip()
        self.buyer_account = (cfg.get("buyer_account") or "").strip()
        self.account_label = (cfg.get("account_label") or "Account").strip()
        self.special_instructions = cfg.get("special_instructions") or ""

        self._gmail: GmailClient | None = None

    def _client(self) -> GmailClient:
        if self._gmail is None:
            self._gmail = GmailClient(send_as=self.email_from)
        return self._gmail

    def validate_line_items(self, line_items: list[dict]) -> list[str]:
        errors: list[str] = []
        for i, item in enumerate(line_items, start=1):
            if not (item.get("sku") or "").strip():
                errors.append(f"Missing SKU on line {i}")
            if int(item.get("quantity") or 0) <= 0:
                errors.append(f"Invalid quantity on line {i}")
        if line_items:
            first = line_items[0]
            if not (first.get("ship_to_name") or "").strip():
                errors.append("Missing ship-to name")
            if not (first.get("ship_to_address1") or "").strip():
                errors.append("Missing ship-to address")
            if not (first.get("ship_to_city") or "").strip():
                errors.append("Missing ship-to city")
            if not (first.get("ship_to_postal") or "").strip():
                errors.append("Missing ship-to postal code")
        return errors

    def build_payload(self, po_number: str, line_items: list[dict]) -> str:
        rithum_order_id = (line_items[0].get("rithum_order_id")
                           if line_items else "") or ""
        return format_plain(
            po_number=po_number,
            rithum_order_id=rithum_order_id,
            line_items=line_items,
            carrier_preference=self.carrier_preference,
            buyer_account=self.buyer_account,
            account_label=self.account_label,
            special_instructions=self.special_instructions,
        )

    def place_order(self, po_number: str, line_items: list[dict]) -> bool:
        if not line_items:
            raise ValueError("Cannot place empty order")
        if not self.email_to:
            raise RuntimeError(
                f"{self.vendor_name} ({self.vendor_code}) connector not configured — "
                f"set vendor config_json.email_to",
            )

        rithum_order_id = line_items[0].get("rithum_order_id") or ""
        subject = format_subject(po_number, rithum_order_id)
        body_text = format_plain(
            po_number=po_number,
            rithum_order_id=rithum_order_id,
            line_items=line_items,
            carrier_preference=self.carrier_preference,
            buyer_account=self.buyer_account,
            account_label=self.account_label,
            special_instructions=self.special_instructions,
        )
        body_html = format_html(
            po_number=po_number,
            rithum_order_id=rithum_order_id,
            line_items=line_items,
            carrier_preference=self.carrier_preference,
            buyer_account=self.buyer_account,
            account_label=self.account_label,
            special_instructions=self.special_instructions,
        )

        if config.SHADOW_MODE:
            logger.info(
                "SHADOW MODE: Would email PO %s to %s (cc %s)\nSubject: %s\n\n%s",
                po_number, self.email_to, self.email_cc or "—",
                subject, body_text,
            )
            return True

        client = self._client()
        msg = client.build_message(
            to=self.email_to,
            cc=self.email_cc or None,
            reply_to=self.reply_to,
            from_addr=self.email_from,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        result = client.send(msg)
        gmail_id = result.get("id")
        logger.info(
            "%s: sent PO %s to %s (Gmail message id %s)",
            self.vendor_name, po_number, self.email_to, gmail_id,
        )
        return True

    def retrieve_tracking(self, po_numbers: list[str]) -> list[TrackingInfo]:
        return []

    def check_health(self) -> dict:
        if not self.email_to:
            return {"ok": False, "error": f"{self.vendor_code}: email_to not configured"}
        try:
            return self._client().check_health()
        except Exception as e:
            return {"ok": False, "error": str(e)}
