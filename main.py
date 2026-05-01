"""Order Automation Platform — FastAPI + APScheduler entrypoint."""
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from core.database import engine, Base, SessionLocal
from core.models import Vendor
from api.routes import router
from jobs.scheduler import create_scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/order_automation.log"),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler

    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")

    # Seed default REV'IT vendor if not exists
    db = SessionLocal()
    try:
        existing = db.query(Vendor).filter(Vendor.code == "REV").first()
        if not existing:
            rev = Vendor(
                code="REV",
                name="REV'IT!",
                connector_type="revit_sftp",
                config_json={
                    "dc_id": 30,
                    "dc_code": "REV",
                    "dc_name": "REV'IT!",
                    "sftp_host_env": "REVIT_SFTP_HOST",
                    "sell_to_customer": config.REVIT_SELL_TO_CUSTOMER,
                    "bill_to_customer": config.REVIT_BILL_TO_CUSTOMER,
                    "currency": config.REVIT_CURRENCY,
                },
                is_active=True,
            )
            db.add(rev)
            db.commit()
            logger.info("Seeded REV'IT vendor")
        elif existing.config_json and "dc_id" not in existing.config_json:
            # One-time upgrade to fulfillment-based polling
            existing.config_json = {**existing.config_json, "dc_id": 30, "dc_code": "REV"}
            db.commit()
            logger.info("Upgraded REV'IT vendor config with dc_id=30")

        # Seed Leatt (email-delivery) vendor. Inactive by default until
        # Gmail OAuth creds and LEATT_EMAIL_TO are configured.
        leatt_ready = bool(
            config.GMAIL_REFRESH_TOKEN and config.LEATT_EMAIL_TO,
        )
        leatt_cfg = {
            "dc_id": 26,
            "dc_code": "LET",
            "dc_name": "Leatt",
            "vendor_name": "Leatt",
            "email_to": config.LEATT_EMAIL_TO,
            "email_cc": config.LEATT_EMAIL_CC,
            "reply_to": config.LEATT_EMAIL_REPLY_TO,
            "buyer_account": config.LEATT_DEALER_ACCOUNT,
            "account_label": "Dealer Account",
            "carrier_preference": "FedEx Ground",
        }
        existing_leatt = db.query(Vendor).filter(Vendor.code == "LET").first()
        if not existing_leatt:
            db.add(Vendor(
                code="LET",
                name="Leatt",
                connector_type="email_generic",
                config_json=leatt_cfg,
                is_active=leatt_ready,
            ))
            db.commit()
            logger.info(
                "Seeded Leatt vendor (active=%s — set GMAIL_REFRESH_TOKEN "
                "+ LEATT_EMAIL_TO to enable)",
                leatt_ready,
            )
        elif existing_leatt.connector_type == "leatt_email":
            # Migrate legacy connector_type → email_generic
            existing_leatt.connector_type = "email_generic"
            existing_leatt.config_json = {**leatt_cfg, **(existing_leatt.config_json or {}),
                                          "account_label": "Dealer Account",
                                          "vendor_name": "Leatt"}
            db.commit()
            logger.info("Migrated Leatt vendor to email_generic connector")

        # Seed all email-based vendors from the rollout spreadsheet.
        # Each is created inactive + force_shadow=True (belt-and-suspenders),
        # so go-live for any of them is two explicit flips by ops:
        #   1. set is_active = True
        #   2. scripts/set_vendor_shadow.py <CODE> off
        # On existing rows we merge the spreadsheet truth into config_json
        # (email_to, dealer #, etc.) but never trample force_shadow / is_active.
        spreadsheet_vendors = [
            # Round 1
            {"round": 1, "code": "6D", "name": "6D Helmets", "dc_id": 22,
             "email_to": "jcuriel@6dhelmets.com", "email_cc": "",
             "buyer_account": "", "account_label": "Account"},
            {"round": 1, "code": "AIR", "name": "Airoh", "dc_id": 41,
             "email_to": "sales@airohusa.com", "email_cc": "",
             "buyer_account": "", "account_label": "Account"},
            {"round": 1, "code": "SHU", "name": "Schuberth", "dc_id": 32,
             "email_to": "sales-sna@schuberth.com", "email_cc": "",
             "buyer_account": "23691", "account_label": "Customer #"},
            # Round 2 — Klim oversees 509/Klim/Klim East; efisher@ on CC
            {"round": 2, "code": "509", "name": "509", "dc_id": 38,
             "email_to": "dealers@ride509.com", "email_cc": "efisher@klim.com",
             "buyer_account": "C425150", "account_label": "Account"},
            {"round": 2, "code": "KLIM", "name": "Klim", "dc_id": 23,
             "email_to": "orders@klim.com", "email_cc": "efisher@klim.com",
             "buyer_account": "C129952", "account_label": "Account"},
            {"round": 2, "code": "KLIM-E", "name": "Klim East", "dc_id": 29,
             "email_to": "orders@klim.com", "email_cc": "efisher@klim.com",
             "buyer_account": "C129952", "account_label": "Account"},
            # Round 3 — approved
            {"round": 3, "code": "LS2", "name": "LS2", "dc_id": 27,
             "email_to": "bazookabondo@cs.com", "email_cc": "",
             "buyer_account": "3119", "account_label": "Account"},
            {"round": 3, "code": "BELL", "name": "Bell Helmets", "dc_id": 5,
             "email_to": "belldropship@vista-actionsports.com", "email_cc": "",
             "buyer_account": "1023923", "account_label": "Account"},
            {"round": 3, "code": "HOLLEY", "name": "Holley", "dc_id": 33,
             "email_to": "csregion1@holley.com", "email_cc": "",
             "buyer_account": "80751", "account_label": "Account"},
            # Round 4 — SMK (intake email + final method TBD; seed for visibility)
            {"round": 4, "code": "SMK", "name": "SMK", "dc_id": 37,
             "email_to": "", "email_cc": "",
             "buyer_account": "", "account_label": "Account"},
        ]
        for v in spreadsheet_vendors:
            desired_cfg = {
                "round": v["round"],
                "dc_id": v["dc_id"],
                "dc_code": v["code"],
                "dc_name": v["name"],
                "vendor_name": v["name"],
                "email_to": v["email_to"],
                "email_cc": v["email_cc"],
                "buyer_account": v["buyer_account"],
                "account_label": v["account_label"],
                "carrier_preference": "FedEx Ground",
            }
            existing = db.query(Vendor).filter(Vendor.code == v["code"]).first()
            if existing:
                # Merge spreadsheet truth in, but don't trample ops-set keys
                merged = {**(existing.config_json or {}), **desired_cfg}
                # force_shadow stays whatever ops set (default True if never set)
                merged.setdefault("force_shadow", True)
                if merged != (existing.config_json or {}):
                    existing.config_json = merged
                    logger.info("Updated %s (%s) config from spreadsheet",
                                v["name"], v["code"])
                continue
            db.add(Vendor(
                code=v["code"],
                name=v["name"],
                connector_type="email_generic",
                config_json={**desired_cfg, "force_shadow": True},
                is_active=False,
            ))
            logger.info(
                "Seeded %s (%s) — inactive + caged (force_shadow=True). "
                "To go live: set is_active=True AND set_vendor_shadow.py %s off",
                v["name"], v["code"], v["code"],
            )
        db.commit()
    finally:
        db.close()

    # Start scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

    if config.SHADOW_MODE:
        logger.warning("SHADOW MODE is ON — orders will be generated but NOT sent to vendors")

    yield

    # Shutdown
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Order Automation",
    description="Speed Addicts dropship order automation platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    socket_path = config.SOCKET_PATH
    if socket_path:
        uvicorn.run(
            "main:app",
            uds=socket_path,
            reload=False,
            log_level=config.LOG_LEVEL.lower(),
        )
    else:
        uvicorn.run(
            "main:app",
            host=config.APP_HOST,
            port=config.APP_PORT,
            reload=False,
            log_level=config.LOG_LEVEL.lower(),
        )
