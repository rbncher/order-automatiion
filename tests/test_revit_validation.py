"""REV'IT connector line-item validation."""
from connectors.revit.connector import RevitConnector


def _c() -> RevitConnector:
    return RevitConnector(vendor_config={})


def _line(ean="8700001234567", sku="REV-TEST-1", ship=True):
    d = {"ean": ean, "sku": sku, "mpn": "TEST-1", "quantity": 1}
    if ship:
        d.update({
            "ship_to_name": "Buyer",
            "ship_to_address1": "123 Main",
            "ship_to_country": "US",
        })
    return d


def test_valid_line_passes():
    assert _c().validate_line_items([_line()]) == []


def test_missing_ean_flagged():
    errors = _c().validate_line_items([_line(ean="")])
    assert len(errors) == 1
    assert "REV-TEST-1" in errors[0]


def test_missing_ship_to_flagged():
    line = _line()
    line["ship_to_name"] = ""
    line["ship_to_address1"] = ""
    errors = _c().validate_line_items([line])
    assert any("name" in e.lower() for e in errors)
    assert any("address" in e.lower() for e in errors)


def test_empty_batch_no_errors():
    # Nothing to send ≠ invalid; caller handles empty separately
    assert _c().validate_line_items([]) == []
