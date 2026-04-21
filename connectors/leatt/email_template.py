"""Format a human-readable PO email for Leatt (and email-delivery vendors).

The template is intentionally vendor-agnostic — Leatt is the first
user but any email-delivery vendor can share it. Tune per vendor via
the connector's config_json (sender, greeting, carrier preference).
"""
from __future__ import annotations

from html import escape


def _money(v) -> str:
    if v is None:
        return ""
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return ""


def format_subject(po_number: str, rithum_order_id: int | str) -> str:
    return f"New PO {po_number} (Order {rithum_order_id}) — Speed Addicts dropship"


def format_plain(
    *,
    po_number: str,
    rithum_order_id: int | str,
    line_items: list[dict],
    carrier_preference: str | None = None,
    buyer_account: str | None = None,
    special_instructions: str | None = None,
) -> str:
    """Plain-text body, readable in any mail client."""
    if not line_items:
        raise ValueError("Cannot format an empty PO email")

    first = line_items[0]
    ship_to_lines = [
        first.get("ship_to_name") or "",
        first.get("ship_to_address1") or "",
        first.get("ship_to_address2") or "",
        ", ".join(p for p in [
            first.get("ship_to_city"),
            first.get("ship_to_state"),
            first.get("ship_to_postal"),
        ] if p),
        first.get("ship_to_country") or "",
    ]
    ship_to = "\n".join(ln for ln in ship_to_lines if ln)
    contact_bits = [first.get("ship_to_email"), first.get("ship_to_phone")]
    contact = " / ".join(b for b in contact_bits if b)

    lines = [
        f"Hello,",
        "",
        f"Please process the following dropship order on behalf of Speed Addicts.",
        "",
        f"PO Number:       {po_number}",
        f"Rithum Order ID: {rithum_order_id}",
    ]
    if buyer_account:
        lines.append(f"Dealer Account:  {buyer_account}")
    if carrier_preference:
        lines.append(f"Ship Via:        {carrier_preference}")
    lines += [
        "",
        "SHIP TO",
        "-------",
        ship_to,
    ]
    if contact:
        lines.append(contact)
    lines += ["", "ITEMS", "-----"]

    # SKU / MPN / Title / Qty / Price
    for i, item in enumerate(line_items, 1):
        lines.append(
            f"{i}. {item.get('sku','')} "
            f"(MPN {item.get('mpn','') or '—'}) — "
            f"{item.get('title','')} "
            f"× {item.get('quantity',0)} @ {_money(item.get('unit_price'))}"
        )

    total_qty = sum(int(i.get("quantity") or 0) for i in line_items)
    lines += ["", f"Total: {len(line_items)} line(s), {total_qty} unit(s)"]

    if special_instructions:
        lines += ["", "NOTES", "-----", special_instructions]

    lines += [
        "",
        "Please reply with tracking (email body or PDF invoice attachment) once the ",
        f"order ships. Use PO {po_number} on all correspondence.",
        "",
        "Thank you,",
        "Speed Addicts Dropship Automation",
    ]
    return "\n".join(lines)


def format_html(
    *,
    po_number: str,
    rithum_order_id: int | str,
    line_items: list[dict],
    carrier_preference: str | None = None,
    buyer_account: str | None = None,
    special_instructions: str | None = None,
) -> str:
    """HTML body with a styled item table. Keep styles inline for email safety."""
    if not line_items:
        raise ValueError("Cannot format an empty PO email")

    first = line_items[0]
    ship_to_html = "<br>".join(
        escape(x) for x in [
            first.get("ship_to_name") or "",
            first.get("ship_to_address1") or "",
            first.get("ship_to_address2") or "",
            ", ".join(p for p in [
                first.get("ship_to_city"),
                first.get("ship_to_state"),
                first.get("ship_to_postal"),
            ] if p),
            first.get("ship_to_country") or "",
        ] if x
    )
    contact_bits = [first.get("ship_to_email"), first.get("ship_to_phone")]
    contact_html = escape(" · ".join(b for b in contact_bits if b))

    rows = []
    for i, item in enumerate(line_items, 1):
        rows.append(
            "<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{i}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;font-family:monospace;'>{escape(item.get('sku',''))}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;font-family:monospace;'>{escape(item.get('mpn','') or '—')}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{escape(item.get('title',''))}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right;'>{int(item.get('quantity') or 0)}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right;'>{escape(_money(item.get('unit_price')))}</td>"
            "</tr>"
        )

    meta_rows = [
        ("PO Number", escape(po_number)),
        ("Rithum Order ID", escape(str(rithum_order_id))),
    ]
    if buyer_account:
        meta_rows.append(("Dealer Account", escape(buyer_account)))
    if carrier_preference:
        meta_rows.append(("Ship Via", escape(carrier_preference)))

    meta_html = "".join(
        f"<tr><td style='padding:2px 10px 2px 0;color:#666;'>{k}</td>"
        f"<td style='padding:2px 0;font-family:monospace;'>{v}</td></tr>"
        for k, v in meta_rows
    )

    notes_html = ""
    if special_instructions:
        notes_html = (
            "<h3 style='margin-top:24px;color:#111;'>Notes</h3>"
            f"<p style='color:#333;'>{escape(special_instructions)}</p>"
        )

    return f"""\
<!doctype html>
<html>
<body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#111;max-width:720px;">
  <p>Hello,</p>
  <p>Please process the following dropship order on behalf of Speed Addicts.</p>

  <table style="border-collapse:collapse;margin:16px 0;">{meta_html}</table>

  <h3 style="margin-top:20px;color:#111;">Ship To</h3>
  <p style="color:#333;">{ship_to_html}<br><span style="color:#666;font-size:90%;">{contact_html}</span></p>

  <h3 style="margin-top:20px;color:#111;">Items</h3>
  <table style="border-collapse:collapse;width:100%;font-size:14px;">
    <thead>
      <tr style="background:#f6f6f6;">
        <th style="padding:8px 10px;text-align:left;">#</th>
        <th style="padding:8px 10px;text-align:left;">SKU</th>
        <th style="padding:8px 10px;text-align:left;">MPN</th>
        <th style="padding:8px 10px;text-align:left;">Title</th>
        <th style="padding:8px 10px;text-align:right;">Qty</th>
        <th style="padding:8px 10px;text-align:right;">Unit</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  {notes_html}

  <p style="margin-top:24px;color:#333;">
    Please reply with tracking (email body or PDF invoice attachment) once the order ships.
    Use <b>PO {escape(po_number)}</b> on all correspondence.
  </p>
  <p style="color:#666;margin-top:24px;">Thank you,<br>Speed Addicts Dropship Automation</p>
</body>
</html>
"""
