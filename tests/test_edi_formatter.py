"""Tests for REV'IT EDI formatter."""
from datetime import date
from connectors.revit.edi_formatter import format_order


def test_basic_order():
    """Test generating a basic dropship order."""
    csv = format_order(
        po_number="SA-REV-20260331-001",
        order_date=date(2026, 3, 31),
        sell_to_customer="C11192",
        line_items=[
            {
                "ean": "8700001169998",
                "description1": "Connector NEON Vest",
                "description2": "",
                "quantity": 2,
                "unit_price": None,
                "item_no": "FAR039",
                "variant_code": "0410-L",
                "colour_code": "0410",
                "size_code": "L",
            },
            {
                "ean": "8700001169981",
                "description1": "Connector NEON Vest",
                "description2": "",
                "quantity": 1,
                "unit_price": None,
                "item_no": "FAR039",
                "variant_code": "0410-M",
                "colour_code": "0410",
                "size_code": "M",
            },
        ],
        ship_to={
            "name1": "John Smith",
            "address1": "123 Main St",
            "city": "Anytown",
            "postal": "12345",
            "country": "US",
            "state": "NY",
            "email": "john@example.com",
            "phone": "555-1234",
        },
        currency="USD",
    )

    lines = csv.strip().split("\n")
    assert len(lines) == 4  # ORDHDR + 2 ORDLIN + ORDSUM

    # Check ORDHDR
    hdr = lines[0].split(";")
    assert hdr[0] == "ORDHDR"
    assert hdr[1] == "SA-REV-20260331-001"
    assert hdr[2] == "20260331"
    assert hdr[5] == "C11192"
    assert hdr[8] == "John Smith"   # Ship-to-Name 1 (field 9 in spec, 0-indexed=8)
    assert hdr[10] == "123 Main St" # Ship-to-Address 1
    assert hdr[12] == "Anytown"     # Ship-to City
    assert hdr[13] == "12345"       # Ship-to Postal
    assert hdr[14] == "US"          # Ship-to Country
    assert hdr[15] == "NY"          # Ship-to State
    assert hdr[17] == "2"           # Ordertype = Dropship

    # Check ORDLIN 1
    line1 = lines[1].split(";")
    assert line1[0] == "ORDLIN"
    assert line1[1] == "1"
    assert line1[2] == "8700001169998"
    assert line1[5] == "2"  # quantity
    assert line1[8] == "FAR039"
    assert line1[9] == "0410-L"

    # Check ORDLIN 2
    line2 = lines[2].split(";")
    assert line2[0] == "ORDLIN"
    assert line2[1] == "2"
    assert line2[2] == "8700001169981"
    assert line2[5] == "1"

    # Check ORDSUM
    summary = lines[3].split(";")
    assert summary[0] == "ORDSUM"
    assert summary[1] == "2"   # 2 lines
    assert summary[2] == "3"   # total qty = 2 + 1


def test_empty_ship_to():
    """Test order with no ship-to (uses sell-to defaults)."""
    csv = format_order(
        po_number="SA-REV-20260401-001",
        order_date=date(2026, 4, 1),
        sell_to_customer="C11192",
        line_items=[
            {"ean": "8700001169998", "quantity": 1},
        ],
    )
    lines = csv.strip().split("\n")
    assert len(lines) == 3  # ORDHDR + ORDLIN + ORDSUM
    assert lines[0].startswith("ORDHDR;")
    assert lines[2].startswith("ORDSUM;1;1")


def test_semicolon_in_remark():
    """Ensure semicolons in remark are sanitized."""
    csv = format_order(
        po_number="TEST-001",
        order_date=date(2026, 1, 1),
        sell_to_customer="C11192",
        line_items=[{"ean": "1234567890123", "quantity": 1}],
        remark="Please rush; urgent order; thanks",
    )
    # Remark should not contain semicolons
    hdr = csv.strip().split("\n")[0]
    fields = hdr.split(";")
    # Field 21 is remark (0-indexed: 20)
    assert ";" not in fields[20]
    assert "Please rush" in fields[20]
