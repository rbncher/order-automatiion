"""Dump REV'IT PO CSVs for vendor sign-off (Peter @ REV'IT).

In shadow mode, place_orders still renders the CSV and saves it to
POBatch.file_content. This script lists recent REV'IT batches and writes
their CSVs to a directory so ops can attach them to a confirmation email.

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

from core.database import SessionLocal
from core.models import POBatch, Vendor


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

        # Write phase
        os.makedirs(args.out, exist_ok=True)
        wrote = 0
        skipped = 0
        for b in batches:
            if not b.file_content:
                print(f"  skip {b.po_number}: no file_content (never rendered)")
                skipped += 1
                continue
            path = os.path.join(args.out, f"{b.po_number}.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write(b.file_content)
            print(f"  wrote {path} ({len(b.file_content)} bytes)")
            wrote += 1

        print(f"\nWrote {wrote} CSV(s) to {args.out}/ (skipped {skipped})")
        if wrote:
            print(f"Forward to Peter @ REV'IT:")
            print(f"  scp 'ec2:{args.out}/*.csv' .")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
