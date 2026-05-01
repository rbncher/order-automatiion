"""Send a real Leatt-format PO email to two test recipients.

Bypasses shadow mode and the vendor table — injects Gmail creds directly
and uses the production email_generic templates so the output matches
exactly what a live send would produce. Subject is prefixed [TEST] so
recipients can see at a glance this is a format sample.

Recipients are hard-coded to the addresses the user asked for:
  schad@speedaddicts.com, rbncher@gmail.com

Usage:
  GMAIL_CLIENT_ID=... GMAIL_CLIENT_SECRET=... GMAIL_REFRESH_TOKEN=... \
    python scripts/send_test_po.py
"""
import os
import sys

from clients.gmail import GmailClient
from connectors.email_generic.email_template import (
    format_subject, format_plain, format_html,
)


RECIPIENTS = ["schad@speedaddicts.com", "rbncher@gmail.com"]

# Sample Leatt PO — realistic shape, fictional buyer details.
PO_NUMBER = "LET-887182"
RITHUM_ORDER_ID = 806270
BUYER_ACCOUNT = "20874"
ACCOUNT_LABEL = "Dealer Account"
CARRIER = "FedEx Ground"

LINE_ITEMS = [
    {
        "sku": "LET-5024060643",
        "mpn": "5024060643",
        "ean": "6009879194512",
        "title": "Leatt 3DF AirFit Evo Back Protector",
        "quantity": 1,
        "unit_price": 153.00,
        "rithum_order_id": RITHUM_ORDER_ID,
        "ship_to_name": "Efren Gonzalez",
        "ship_to_address1": "1815 W 108th St",
        "ship_to_address2": "",
        "ship_to_city": "Los Angeles",
        "ship_to_state": "CA",
        "ship_to_postal": "90047",
        "ship_to_country": "US",
        "ship_to_phone": "310-555-0142",
    },
    {
        "sku": "LET-1023064150",
        "mpn": "1023064150",
        "ean": "6009879201111",
        "title": "Leatt Moto 3.5 Jacket - Stealth / L",
        "quantity": 1,
        "unit_price": 189.99,
        "rithum_order_id": RITHUM_ORDER_ID,
        "ship_to_name": "Efren Gonzalez",
        "ship_to_address1": "1815 W 108th St",
        "ship_to_city": "Los Angeles",
        "ship_to_state": "CA",
        "ship_to_postal": "90047",
        "ship_to_country": "US",
    },
]


def main() -> int:
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()
    send_as = os.environ.get("GMAIL_SEND_AS", "dropship@speedaddicts.com")
    reply_to = os.environ.get("OPS_EMAIL", "ops@speedaddicts.com")

    if not (client_id and client_secret and refresh_token):
        print(
            "ERROR: set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN "
            "in the environment first.",
            file=sys.stderr,
        )
        return 1

    subject = "[TEST] " + format_subject(PO_NUMBER, RITHUM_ORDER_ID)
    body_text = format_plain(
        po_number=PO_NUMBER,
        rithum_order_id=RITHUM_ORDER_ID,
        line_items=LINE_ITEMS,
        carrier_preference=CARRIER,
        buyer_account=BUYER_ACCOUNT,
        account_label=ACCOUNT_LABEL,
    )
    body_html = format_html(
        po_number=PO_NUMBER,
        rithum_order_id=RITHUM_ORDER_ID,
        line_items=LINE_ITEMS,
        carrier_preference=CARRIER,
        buyer_account=BUYER_ACCOUNT,
        account_label=ACCOUNT_LABEL,
    )

    client = GmailClient(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        send_as=send_as,
    )
    msg = client.build_message(
        to=RECIPIENTS,
        from_addr=send_as,
        reply_to=reply_to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )
    result = client.send(msg)

    print(f"Sent. Gmail message id: {result.get('id')}")
    print(f"From:     {send_as}")
    print(f"Reply-To: {reply_to}")
    print(f"To:       {', '.join(RECIPIENTS)}")
    print(f"Subj:     {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
