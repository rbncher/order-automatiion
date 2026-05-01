"""Backfill missing EANs on existing REV'IT line items from the local map.

poll_rithum already does this fallback for *new* fulfillments, but rows that
were ingested before the EAN map landed may still be sitting with empty EAN
fields. Run this once after deploying the map so the dashboard reflects what
will actually go on the wire.

Usage:
  python scripts/backfill_revit_eans.py            # dry run, summary only
  python scripts/backfill_revit_eans.py --apply    # commit changes

Only touches OrderLineItems where:
  - vendor.code = 'REV'
  - ean is empty / NULL
  - status in ('pending', 'submitted')   # don't rewrite history past send
"""
import argparse
import sys
from collections import Counter

from sqlalchemy.orm import Session

from connectors.revit import ean_map as revit_ean_map
from core.database import SessionLocal
from core.models import OrderLineItem, Vendor


def main(apply: bool) -> int:
    db: Session = SessionLocal()
    try:
        rev = db.query(Vendor).filter(Vendor.code == "REV").first()
        if not rev:
            print("No REV vendor row found — nothing to do.")
            return 0

        rows = (
            db.query(OrderLineItem)
            .filter(OrderLineItem.vendor_id == rev.id)
            .filter(OrderLineItem.status.in_(["pending", "submitted"]))
            .filter((OrderLineItem.ean == None) | (OrderLineItem.ean == ""))  # noqa: E711
            .all()
        )

        counts = Counter()
        examples = {"filled": [], "no_match": [], "no_mpn": []}

        for r in rows:
            if not r.mpn:
                counts["no_mpn"] += 1
                if len(examples["no_mpn"]) < 5:
                    examples["no_mpn"].append((r.id, r.sku))
                continue
            ean = revit_ean_map.lookup(r.mpn)
            if not ean:
                counts["no_match"] += 1
                if len(examples["no_match"]) < 5:
                    examples["no_match"].append((r.id, r.sku, r.mpn))
                continue
            counts["filled"] += 1
            if len(examples["filled"]) < 5:
                examples["filled"].append((r.id, r.sku, r.mpn, ean))
            if apply:
                r.ean = ean

        print(f"REV'IT line items with empty EAN, in pending/submitted: {len(rows)}")
        print(f"  Map size:          {revit_ean_map.size():,} entries")
        print(f"  Would fill:        {counts['filled']}")
        print(f"  No match in map:   {counts['no_match']}")
        print(f"  Missing MPN:       {counts['no_mpn']}")

        if examples["filled"]:
            print("\nSample fills (id, sku, mpn -> ean):")
            for ex in examples["filled"]:
                print(f"  {ex[0]:>6}  {ex[1]:<25} {ex[2]:<25} -> {ex[3]}")
        if examples["no_match"]:
            print("\nSample MPNs not in map (id, sku, mpn):")
            for ex in examples["no_match"]:
                print(f"  {ex[0]:>6}  {ex[1]:<25} {ex[2]}")
        if examples["no_mpn"]:
            print("\nSample rows missing MPN (id, sku):")
            for ex in examples["no_mpn"]:
                print(f"  {ex[0]:>6}  {ex[1]}")

        if apply and counts["filled"]:
            db.commit()
            print(f"\nCommitted {counts['filled']} row update(s).")
        elif apply:
            print("\nNothing to commit.")
        else:
            print("\nDry run — pass --apply to commit.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true",
                   help="Commit EAN fills (default is a dry-run summary).")
    args = p.parse_args()
    sys.exit(main(apply=args.apply))
