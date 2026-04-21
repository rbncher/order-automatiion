"""Leatt vendor connector — email-based PO delivery via Gmail API.

Rithum fulfillment at DC 26 (Leatt) → we email a human-readable PO to
Leatt's intake address from dropship@speedaddicts.com. Leatt's team
manually processes the order and replies with tracking (email body
or PDF invoice attachment).

Tracking retrieval is not in this connector yet — handled by a
separate email-scrape job that watches invoices@speedaddicts.com.
"""
import logging

import config
from clients.gmail import GmailClient
from connectors.base import VendorConnector
from connectors.leatt.email_template import (
    format_html, format_plain, format_subject,
)
from core.schemas import TrackingInfo

logger = logging.getLogger(__name__)


class LeattConnector(VendorConnector):
    """Email-based PO delivery for Leatt."""

    def __init__(self, vendor_code: str = "LET", vendor_config: dict | None = None):
        cfg = vendor_config or {}
        super().__init__(vendor_code, cfg)

        # Routing
        self.email_to = cfg.get("email_to") or config.LEATT_EMAIL_TO
        self.email_cc = cfg.get("email_cc") or config.LEATT_EMAIL_CC
        self.email_from = cfg.get("email_from") or config.GMAIL_SEND_AS
        self.reply_to = cfg.get("reply_to") or config.LEATT_EMAIL_REPLY_TO

        # PO content
        self.carrier_preference = cfg.get("carrier_preference") or "FedEx Ground"
        self.buyer_account = cfg.get("buyer_account") or config.LEATT_DEALER_ACCOUNT
        self.special_instructions = cfg.get("special_instructions") or ""

        # Gmail transport (lazily authenticated)
        self._gmail: GmailClient | None = None

    def _client(self) -> GmailClient:
        if self._gmail is None:
            self._gmail = GmailClient(send_as=self.email_from)
        return self._gmail

    # ------------------------------------------------------------------
    # VendorConnector interface
    # ------------------------------------------------------------------

    def validate_line_items(self, line_items: list[dict]) -> list[str]:
        """Leatt requires SKU, quantity, and a full ship-to address."""
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
        """Return the plain-text email body. Used for dashboard preview."""
        rithum_order_id = (line_items[0].get("rithum_order_id")
                           if line_items else "") or ""
        return format_plain(
            po_number=po_number,
            rithum_order_id=rithum_order_id,
            line_items=line_items,
            carrier_preference=self.carrier_preference,
            buyer_account=self.buyer_account,
            special_instructions=self.special_instructions,
        )

    def place_order(self, po_number: str, line_items: list[dict]) -> bool:
        """Send the PO as an email to Leatt via Gmail API."""
        if not line_items:
            raise ValueError("Cannot place empty order")
        if not self.email_to:
            raise RuntimeError(
                "Leatt connector not configured — set LEATT_EMAIL_TO (or "
                "vendor config_json.email_to)",
            )

        rithum_order_id = line_items[0].get("rithum_order_id") or ""

        subject = format_subject(po_number, rithum_order_id)
        body_text = format_plain(
            po_number=po_number,
            rithum_order_id=rithum_order_id,
            line_items=line_items,
            carrier_preference=self.carrier_preference,
            buyer_account=self.buyer_account,
            special_instructions=self.special_instructions,
        )
        body_html = format_html(
            po_number=po_number,
            rithum_order_id=rithum_order_id,
            line_items=line_items,
            carrier_preference=self.carrier_preference,
            buyer_account=self.buyer_account,
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
            reply_to=self.reply_to or self.email_from,
            from_addr=self.email_from,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        result = client.send(msg)
        gmail_id = result.get("id")
        logger.info(
            "Leatt: sent PO %s to %s (Gmail message id %s)",
            po_number, self.email_to, gmail_id,
        )
        return True

    def retrieve_tracking(self, po_numbers: list[str]) -> list[TrackingInfo]:
        """Not implemented yet — tracking comes via a separate email-watcher job."""
        return []

    def check_health(self) -> dict:
        """Verify Gmail OAuth token can be refreshed and destinations are set."""
        if not self.email_to:
            return {"ok": False, "error": "LEATT_EMAIL_TO not configured"}
        try:
            return self._client().check_health()
        except Exception as e:
            return {"ok": False, "error": str(e)}
