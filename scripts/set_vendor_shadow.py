"""Set or clear the per-vendor shadow flag without manually editing SQL.

Usage:
  python scripts/set_vendor_shadow.py LET on      # cage Leatt in shadow
  python scripts/set_vendor_shadow.py LET off     # uncage Leatt
  python scripts/set_vendor_shadow.py             # show current state of all vendors

When global SHADOW_MODE=true, every vendor is in shadow regardless of the
per-vendor flag — this script only affects behavior once the global is off.
"""
import argparse
import sys

from sqlalchemy.orm.attributes import flag_modified

import config
from core.database import SessionLocal
from core.models import Vendor


def show_all() -> int:
    db = SessionLocal()
    try:
        print(f"global SHADOW_MODE = {config.SHADOW_MODE}\n")
        print(f"{'CODE':<6} {'NAME':<24} {'ACTIVE':<7} {'FORCE_SHADOW':<13} EFFECTIVE")
        print("-" * 70)
        for v in db.query(Vendor).order_by(Vendor.code).all():
            cfg = v.config_json or {}
            force = bool(cfg.get("force_shadow"))
            effective = "SHADOW" if (config.SHADOW_MODE or force) else "LIVE"
            print(f"{v.code:<6} {v.name:<24} {str(v.is_active):<7} "
                  f"{str(force):<13} {effective}")
        return 0
    finally:
        db.close()


def set_flag(code: str, value: bool) -> int:
    db = SessionLocal()
    try:
        v = db.query(Vendor).filter(Vendor.code == code).first()
        if not v:
            print(f"No vendor with code {code!r}", file=sys.stderr)
            return 1
        cfg = dict(v.config_json or {})
        prev = bool(cfg.get("force_shadow"))
        cfg["force_shadow"] = value
        v.config_json = cfg
        flag_modified(v, "config_json")
        db.commit()
        print(f"{v.code} ({v.name}): force_shadow {prev} -> {value}")
        if config.SHADOW_MODE:
            print("Note: global SHADOW_MODE is still on, so this flag is masked.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("code", nargs="?", help="Vendor code (e.g. LET, REV, 6D)")
    p.add_argument("state", nargs="?", choices=["on", "off"],
                   help="on = force shadow, off = allow live sends")
    args = p.parse_args()

    if not args.code:
        sys.exit(show_all())
    if not args.state:
        print("Both code and state are required (or pass neither for status).",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(set_flag(args.code.upper(), args.state == "on"))
