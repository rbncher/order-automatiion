"""Leatt connector validation + email template formatting."""
from connectors.leatt.connector import LeattConnector
from connectors.leatt.email_template import (
    format_subject, format_plain, format_html,
)


def _line(**overrides):
    d = {
        "rithum_order_id": 801617,
        "sku": "LET-5024060643",
        "mpn": "5024060643",
        "ean": "1234567890123",
        "title": "Leatt 3DF AirFit Evo Back Protector",
        "quantity": 1,
        "unit_price": 153.0,
        "ship_to_name": "Efren Gonzalez",
        "ship_to_address1": "1815 W 108th St",
        "ship_to_city": "Los Angeles",
        "ship_to_state": "CA",
        "ship_to_postal": "90047",
        "ship_to_country": "US",
        "ship_to_email": "buyer@example.com",
        "ship_to_phone": "1234567890",
    }
    d.update(overrides)
    return d


def test_validate_passes_on_complete_line():
    c = LeattConnector(vendor_config={})
    assert c.validate_line_items([_line()]) == []


def test_validate_flags_missing_ship_to():
    c = LeattConnector(vendor_config={})
    errors = c.validate_line_items([_line(ship_to_name="", ship_to_address1="")])
    assert any("name" in e.lower() for e in errors)
    assert any("address" in e.lower() for e in errors)


def test_validate_flags_bad_quantity():
    c = LeattConnector(vendor_config={})
    errors = c.validate_line_items([_line(quantity=0)])
    assert any("quantity" in e.lower() for e in errors)


def test_subject_contains_po_and_order():
    s = format_subject("LET-887182", 806270)
    assert "LET-887182" in s and "806270" in s


def test_plain_body_includes_sku_and_ship_to():
    body = format_plain(
        po_number="LET-887182",
        rithum_order_id=806270,
        line_items=[_line()],
        buyer_account="DLR20874",
    )
    assert "LET-887182" in body
    assert "806270" in body
    assert "LET-5024060643" in body
    assert "Efren Gonzalez" in body
    assert "DLR20874" in body
    assert "$153.00" in body


def test_html_body_escapes_values():
    body = format_html(
        po_number="LET-1",
        rithum_order_id=1,
        line_items=[_line(title="<script>alert('x')</script>")],
    )
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_build_payload_uses_line_item_order_id():
    c = LeattConnector(vendor_config={"email_to": "x@example.com"})
    body = c.build_payload("LET-1", [_line()])
    assert "801617" in body


def test_place_order_rejects_empty_lines():
    c = LeattConnector(vendor_config={"email_to": "x@example.com"})
    try:
        c.place_order("LET-1", [])
    except ValueError:
        return
    assert False, "expected ValueError on empty line items"
