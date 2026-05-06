"""Dump REV'IT PO CSVs for vendor sign-off (Peter @ REV'IT).

Pulls each batch's stored CSV from POBatch.file_content; for older batches
that predate the file_content capture, re-renders on the fly using the
OrderLineItem rows still attached to the batch.

Usage:
  # List recent REV'IT batches (no files written)
  python scripts/dump_revit_csvs.py

  # Write the latest N batches to /tmp/revit_csvs/
  python scripts/dump_revit_csvs.py --write --limit 3

  # Write a specific PO
  python scripts/dump_revit_csvs.py --po REV-12345 --write

  # Write to a custom directory
  python scripts/dump_revit_csvs.py --write --out /home/ec2-user/revit_samples
"""
import argparse
import os
import sys

from connectors.revit.connector import RevitConnector
from core.database import SessionLocal
from core.models import POBatch, Vendor
from jobs.place_orders import _line_dicts_for_batch


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true",
                   help="Write CSVs to disk (default: list only)")
    p.add_argument("--limit", type=int, default=5,
                   help="How many most-recent batches to consider (default 5)")
    p.add_argument("--po", help="Dump just this PO number")
    p.add_argument("--out", default="/tmp/revit_csvs",
                   help="Output directory (default /tmp/revit_csvs)")
    args = p.parse_args()

    db = SessionLocal()
    try:
        rev = db.query(Vendor).filter(Vendor.code == "REV").first()
        if not rev:
            print("No REV vendor in DB", file=sys.stderr)
            return 1

        q = db.query(POBatch).filter(POBatch.vendor_id == rev.id)
        if args.po:
            q = q.filter(POBatch.po_number == args.po)
        else:
            q = q.order_by(POBatch.id.desc()).limit(args.limit)
        batches = q.all()

        if not batches:
            print("No REV'IT POBatches found.")
            print("If you expected some, check that poll_rithum has run and "
                  "that there were pending REV'IT fulfillments.")
            return 0

        print(f"{'PO':<22} {'STATUS':<22} {'ITEMS':<6} {'HAS_CSV':<8} SENT_AT")
        print("-" * 90)
        for b in batches:
            has_csv = "yes" if b.file_content else "NO"
            sent = b.sent_at.isoformat() if b.sent_at else "-"
            print(f"{b.po_number:<22} {b.status:<22} {b.line_count:<6} "
                  f"{has_csv:<8} {sent}")

        if not args.write:
            print("\n(use --write to save the CSVs to disk)")
            return 0

        # Write phase: prefer stored file_content, fall back to re-render
        os.makedirs(args.out, exist_ok=True)
        connector = RevitConnector(vendor_config=rev.config_json)
        wrote = 0
        rerendered = 0
        skipped = 0
        for b in batches:
            csv_content = b.file_content
            if not csv_content:
                # Old batch from before file_content capture — re-render
                line_dicts = _line_dicts_for_batch(db, b)
                if not line_dicts:
                    print(f"  skip {b.po_number}: no line items in DB")
                    skipped += 1
                    continue
                errors = connector.validate_line_items(line_dicts)
                if errors:
                    print(f"  skip {b.po_number}: validator errors -> "
                          f"{'; '.join(errors)}")
                    print(f"    (run scripts/backfill_revit_eans.py --apply "
                          f"if EANs are missing)")
                    skipped += 1
                    continue
                try:
                    csv_content = connector.build_payload(b.po_number, line_dicts)
                    rerendered += 1
                except Exception as e:
                    print(f"  skip {b.po_number}: build_payload raised {e!r}")
                    skipped += 1
                    continue

            path = os.path.join(args.out, f"{b.po_number}.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write(csv_content)
            tag = " (re-rendered)" if not b.file_content else ""
            print(f"  wrote {path} ({len(csv_content)} bytes){tag}")
            wrote += 1

        print(f"\nWrote {wrote} CSV(s) to {args.out}/ "
              f"(re-rendered {rerendered}, skipped {skipped})")
        if wrote:
            print(f"Forward to Peter @ REV'IT:")
            print(f"  scp 'ec2:{args.out}/*.csv' .")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
