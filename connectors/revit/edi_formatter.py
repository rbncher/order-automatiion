"""Generate REV'IT EDI CSV files (ORDHDR + ORDLIN + ORDSUM).

Format per K3 Technical Design Document V3.
Semicolon-delimited, no quoting.
"""
from datetime import date


def format_order(
    po_number: str,
    order_date: date,
    sell_to_customer: str,
    line_items: list[dict],
    ship_to: dict | None = None,
    bill_to_customer: str = "",
    currency: str = "USD",
    order_type: int = 2,       # 2 = Dropship
    shipping_agent: str = "",
    shipping_agent_service_code: str = "",
    remark: str = "",
) -> str:
    """
    Generate a complete REV'IT EDI order file as a string.

    line_items: list of dicts with keys:
        ean (str, 13 digits), quantity (int),
        description1 (str, optional), description2 (str, optional),
        unit_price (float, optional), item_no (str, optional),
        variant_code (str, optional), colour_code (str, optional),
        size_code (str, optional)

    ship_to: dict with keys:
        code, name1, name2, address1, address2, city, postal, country, state,
        email, phone

    Returns the full CSV content as a string.
    """
    lines = []

    # Format dates as YYYYMMDD
    date_str = order_date.strftime("%Y%m%d")

    # Ship-to fields (fields 8-16 in spec)
    st = ship_to or {}
    ship_to_code = st.get("code", "")
    ship_to_name1 = st.get("name1", "")
    ship_to_name2 = st.get("name2", "")
    ship_to_addr1 = st.get("address1", "")
    ship_to_addr2 = st.get("address2", "")
    ship_to_city = st.get("city", "")
    ship_to_postal = st.get("postal", "")
    ship_to_country = st.get("country", "")
    ship_to_state = st.get("state", "")
    ship_to_email = st.get("email", "")
    ship_to_phone = st.get("phone", "")

    # ORDHDR: 24 fields
    header_fields = [
        "ORDHDR",                           # 1  Record ID
        po_number,                          # 2  Document number
        date_str,                           # 3  Document date
        date_str,                           # 4  Delivery date
        po_number,                          # 5  Your Reference
        sell_to_customer,                   # 6  Sell-to Customer nr
        "",                                 # 7  Sell to Contact
        ship_to_code,                       # 8  Ship-to-code
        ship_to_name1,                      # 9  Ship-to-Name 1
        ship_to_name2,                      # 10 Ship-to-Name 2
        ship_to_addr1,                      # 11 Ship-to-Address 1
        ship_to_addr2,                      # 12 Ship-to-Address 2
        ship_to_city,                       # 13 Ship-to City
        ship_to_postal,                     # 14 Ship-to Postal code
        ship_to_country,                    # 15 Ship-to Country
        ship_to_state,                      # 16 Ship-to State
        shipping_agent,                     # 17 Shipping Agent
        str(order_type),                    # 18 Ordertype (2=Dropship)
        bill_to_customer or sell_to_customer,  # 19 Bill-to Customer nr
        currency,                           # 20 Currency Code
        _sanitize(remark),                  # 21 Remark (no semicolons!)
        ship_to_email,                      # 22 Ship-to E-mail
        ship_to_phone,                      # 23 Ship-to Phone No.
        shipping_agent_service_code,        # 24 Shipping Agent Service Code
    ]
    lines.append(";".join(header_fields))

    # ORDLIN: one per line item
    total_qty = 0
    for idx, item in enumerate(line_items, start=1):
        qty = int(item["quantity"])
        total_qty += qty

        line_fields = [
            "ORDLIN",                           # 1  Record ID
            str(idx),                           # 2  Line nr
            str(item.get("ean", "")),           # 3  EAN/Item nr (13 digits)
            item.get("description1", ""),       # 4  Description 1
            item.get("description2", ""),       # 5  Description 2
            str(qty),                           # 6  Order Quantity
            item.get("unit_measure", ""),       # 7  Quantity unit per measure
            _format_price(item.get("unit_price")),  # 8  Net unit price
            item.get("item_no", ""),            # 9  Item no. NAV
            item.get("variant_code", ""),       # 10 Variant Code
            item.get("colour_code", ""),        # 11 Colour Code
            item.get("size_code", ""),          # 12 Size Code
        ]
        lines.append(";".join(line_fields))

    # ORDSUM
    sum_fields = [
        "ORDSUM",                   # 1 Record ID
        str(len(line_items)),       # 2 Number of ORDLIN
        str(total_qty),             # 3 Sum Order Quantity
    ]
    lines.append(";".join(sum_fields))

    return "\n".join(lines) + "\n"


def _sanitize(text: str) -> str:
    """Remove semicolons from text to prevent CSV corruption."""
    return text.replace(";", ",").replace("\n", " ").replace("\r", "")


def _format_price(price) -> str:
    """Format price for EDI. REV'IT uses comma as decimal separator in EU."""
    if price is None:
        return ""
    return str(price)
