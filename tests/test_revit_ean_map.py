"""REV'IT local EAN map — sourced from Article Data EANcodes export."""
from connectors.revit import ean_map


def test_map_loads_and_has_entries():
    # The shipped JSON file should have on the order of tens of thousands of
    # entries. Don't lock to an exact number (REV'IT will refresh the file
    # over time), just sanity-check it isn't empty or comically small.
    assert ean_map.size() > 1000


def test_known_mpn_resolves():
    # First entry from the article-data export.
    assert ean_map.lookup("FAR018-3540-35-38") == "8700001050142"


def test_unknown_mpn_returns_none():
    assert ean_map.lookup("DOES-NOT-EXIST-9999") is None


def test_empty_input_returns_none():
    assert ean_map.lookup("") is None
    assert ean_map.lookup(None) is None


def test_lookup_strips_whitespace():
    assert ean_map.lookup("  FAR018-3540-35-38  ") == "8700001050142"
