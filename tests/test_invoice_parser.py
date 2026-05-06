"""Tests for REV'IT invoice CSV parser."""
from connectors.revit.invoice_parser import parse_invoice_csv, group_tracking_by_po

SAMPLE_CSV = """Document No.;PO/Customer Order No.;Shipment Date;Posting Date;Item No.;Description;Variant;Quantity;Unit Price Excl. VAT;Line Discount %;Line Discount Amount;Net Amount per Unit after Discount Incl. VAT;Net. Line Amount after Discount;Order Type;Customer No.;Customer Name;Order No. REV'IT!;EAN Code;Tracking No.;Box ID;SKU;Weight;Dimensions;Composition
SI2534658;SA-REV-20260331-001;08-04-25;08-04-25;FAR089;Tube Fanatic;0010-ONE S;6,00;20,26;16,67;20,26;0,00;101,30;WEBSHOPORD;C12617;ANILA S.R.O.;SO2528666;8700001369633;05222769468079;574057;FAR0890010-ONE S;0,01;1x1x1;47% Acrylic
SI2534658;SA-REV-20260331-001;08-04-25;08-04-25;FBR078;Shoes Jetspeed;1010-44;2,00;75,98;16,67;25,33;0,00;126,63;WEBSHOPORD;C12617;ANILA S.R.O.;SO2528666;8700001357883;05222769468079;574057;FBR0781010-44;1,5;36x29x13;Uppers
SI2534658;SA-REV-20260401-001;08-04-25;08-04-25;FGS203;Gloves Mosca 2;1010-M;3,00;27,86;16,67;13,93;0,00;69,65;WEBSHOPORD;C12617;ANILA S.R.O.;SO2529076;8700001382922;05222769468374;574536;FGS2031010-M;0,01;1x1x1;62% polyamide"""


def test_parse_invoice():
    """Test parsing invoice CSV."""
    results = parse_invoice_csv(SAMPLE_CSV)
    assert len(results) == 3

    # First item
    assert results[0].po_number == "SA-REV-20260331-001"
    assert results[0].tracking_number == "05222769468079"
    assert results[0].sku == "FAR0890010-ONE S"
    assert results[0].ean == "8700001369633"
    assert results[0].quantity == 6
    # Parser leaves carrier unset; the connector fills it from shipping_agent
    assert results[0].carrier is None

    # Third item (different PO)
    assert results[2].po_number == "SA-REV-20260401-001"


def test_group_by_po():
    """Test grouping tracking by PO number."""
    results = parse_invoice_csv(SAMPLE_CSV)
    groups = group_tracking_by_po(results)

    assert "SA-REV-20260331-001" in groups
    assert "SA-REV-20260401-001" in groups
    assert len(groups["SA-REV-20260331-001"]) == 2
    assert len(groups["SA-REV-20260401-001"]) == 1


def test_empty_csv():
    """Test parsing empty CSV."""
    results = parse_invoice_csv("header1;header2\n")
    assert results == []


def test_missing_tracking():
    """Lines without tracking should be skipped."""
    csv = """Document No.;PO/Customer Order No.;Shipment Date;Posting Date;Item No.;Description;Variant;Quantity;Unit Price Excl. VAT;Line Discount %;Line Discount Amount;Net Amount per Unit after Discount Incl. VAT;Net. Line Amount after Discount;Order Type;Customer No.;Customer Name;Order No. REV'IT!;EAN Code;Tracking No.;Box ID;SKU;Weight;Dimensions;Composition
SI123;PO-001;01-01-26;01-01-26;FAR089;Test;0010;1,00;10,00;0;0;0;10;ORD;C123;Test;;8700001369633;;574057;FAR089;0,01;1x1;test"""
    results = parse_invoice_csv(csv)
    assert len(results) == 0  # no tracking number
