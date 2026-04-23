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

        # Seed Priority-1 email vendors as inactive. Ops flips active after
        # confirming PO format with each vendor.
        #   email_to from rollout spreadsheet; buyer_account/label from same.
        p1_email_vendors = [
            {
                "code": "6D",
                "name": "6D Helmets",
                "dc_id": 22,
                "email_to": "jcuriel@6dhelmets.com",
                "buyer_account": "",
                "account_label": "Account",
            },
            {
                "code": "AIR",
                "name": "Airoh",
                "dc_id": 41,
                "email_to": "suziek@airohusa.com",
                "buyer_account": "",
                "account_label": "Account",
            },
            {
                "code": "SHU",
                "name": "Schuberth",
                "dc_id": 32,
                "email_to": "sales-sna@schuberth.com",
                "buyer_account": "23691",
                "account_label": "Customer #",
            },
            {
                "code": "SMK",
                "name": "SMK",
                "dc_id": 37,
                "email_to": "",  # TBD per spreadsheet
                "buyer_account": "",
                "account_label": "Account",
            },
        ]
        for v in p1_email_vendors:
            if db.query(Vendor).filter(Vendor.code == v["code"]).first():
                continue
            db.add(Vendor(
                code=v["code"],
                name=v["name"],
                connector_type="email_generic",
                config_json={
                    "dc_id": v["dc_id"],
                    "dc_code": v["code"],
                    "dc_name": v["name"],
                    "vendor_name": v["name"],
                    "email_to": v["email_to"],
                    "email_cc": "",
                    "buyer_account": v["buyer_account"],
                    "account_label": v["account_label"],
                    "carrier_preference": "FedEx Ground",
                },
                is_active=False,  # ops activates after confirming PO format
            ))
            logger.info("Seeded %s (%s) — inactive pending PO format confirmation",
                        v["name"], v["code"])
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
