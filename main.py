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
