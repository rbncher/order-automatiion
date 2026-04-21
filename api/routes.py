"""FastAPI routes for dashboard and API endpoints."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text
from sqlalchemy.orm import Session

import config
from core.database import get_db
from core.models import Vendor, OrderLineItem, POBatch, AuditLog, JobRun
from core.state_machine import transition
from api.auth import (
    verify_password, create_session, get_current_user, logout,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")


# Status groupings for the dashboard
ITEM_STATUSES = [
    "pending", "submitted", "pending_fulfillment",
    "shipped", "tracking_posted", "complete",
    "failed", "cancelled",
]
BATCH_STATUSES = [
    "pending", "sent", "pending_fulfillment",
    "shipped", "complete", "failed",
]


def _render(request: Request, name: str, context: dict) -> HTMLResponse:
    context["request"] = request
    return templates.TemplateResponse(request=request, name=name, context=context)


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _render(request, "login.html", {})


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if verify_password(username, password):
        session_id = create_session(username)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            "session_id", session_id,
            httponly=True, samesite="lax", max_age=86400,
        )
        return response
    return _render(request, "login.html", {"error": "Invalid credentials"})


@router.get("/logout")
async def logout_route(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        logout(session_id)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_id")
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Fulfillment-level counts (POBatch)
    batch_counts = dict(
        db.query(POBatch.status, func.count(POBatch.id))
        .group_by(POBatch.status)
        .all()
    )
    today_batches = (
        db.query(func.count(POBatch.id))
        .filter(POBatch.created_at >= today_start)
        .scalar() or 0
    )

    # Line-item counts (for failure alerts)
    item_counts = dict(
        db.query(OrderLineItem.status, func.count(OrderLineItem.id))
        .group_by(OrderLineItem.status)
        .all()
    )

    # Vendor stats — fulfillment-centric
    vendors = db.query(Vendor).filter(Vendor.is_active == True).all()
    vendor_stats = []
    for v in vendors:
        v_batch_counts = dict(
            db.query(POBatch.status, func.count(POBatch.id))
            .filter(POBatch.vendor_id == v.id)
            .group_by(POBatch.status)
            .all()
        )
        last_activity = (
            db.query(func.max(POBatch.created_at))
            .filter(POBatch.vendor_id == v.id)
            .scalar()
        )
        cfg = v.config_json or {}
        vendor_stats.append({
            "code": v.code,
            "name": v.name,
            "connector_type": v.connector_type,
            "dc_id": cfg.get("dc_id", "—"),
            "dc_name": cfg.get("dc_name", "—"),
            "is_active": v.is_active,
            "pending": v_batch_counts.get("pending", 0),
            "sent": v_batch_counts.get("sent", 0),
            "pending_fulfillment": v_batch_counts.get("pending_fulfillment", 0),
            "shipped": v_batch_counts.get("shipped", 0),
            "complete": v_batch_counts.get("complete", 0),
            "failed": v_batch_counts.get("failed", 0),
            "last_activity_at": last_activity,
        })

    recent_jobs = (
        db.query(JobRun)
        .order_by(JobRun.started_at.desc())
        .limit(10)
        .all()
    )

    recent_errors = (
        db.query(POBatch)
        .filter(POBatch.status == "failed")
        .order_by(POBatch.created_at.desc())
        .limit(5)
        .all()
    )

    return _render(request, "dashboard.html", {
        "user": user,
        "shadow_mode": config.SHADOW_MODE,
        "today_batches": today_batches,
        "batch_counts": batch_counts,
        "item_counts": item_counts,
        "vendor_stats": vendor_stats,
        "recent_jobs": recent_jobs,
        "recent_errors": recent_errors,
    })


# ---------------------------------------------------------------------------
# Fulfillments (one row per Rithum Fulfillment / POBatch)
# ---------------------------------------------------------------------------

@router.get("/fulfillments", response_class=HTMLResponse)
async def fulfillments_list(
    request: Request,
    status: str = "",
    vendor: str = "",
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    query = db.query(POBatch).join(Vendor)
    if status:
        query = query.filter(POBatch.status == status)
    if vendor:
        query = query.filter(Vendor.code == vendor)

    batches = query.order_by(POBatch.created_at.desc()).limit(200).all()
    vendors = db.query(Vendor).filter(Vendor.is_active == True).all()

    # Preload first ship_to for each batch (for display)
    batch_rows = []
    for b in batches:
        first_item = (
            db.query(OrderLineItem)
            .filter(OrderLineItem.po_batch_id == b.id)
            .order_by(OrderLineItem.id)
            .first()
        )
        batch_rows.append({"b": b, "first_item": first_item})

    return _render(request, "fulfillments.html", {
        "user": user,
        "batch_rows": batch_rows,
        "vendors": vendors,
        "statuses": BATCH_STATUSES,
        "filter_status": status,
        "filter_vendor": vendor,
    })


@router.get("/fulfillments/{batch_id}/download")
async def fulfillment_download(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db),
):
    """Serve the PO payload (CSV/EDI) as a file download.

    Prefers the DB-stored content. If missing (legacy row) and the connector
    supports building the payload on demand, rebuild and persist it.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    batch = db.query(POBatch).filter(POBatch.id == batch_id).first()
    if not batch:
        return PlainTextResponse("Not found", status_code=404)

    content = batch.file_content
    if not content and batch.vendor:
        # Rebuild from current line items (idempotent; same inputs → same CSV)
        from connectors.registry import get_connector
        connector = get_connector(
            batch.vendor.connector_type,
            batch.vendor.code,
            batch.vendor.config_json,
        )
        items = (
            db.query(OrderLineItem)
            .filter(OrderLineItem.po_batch_id == batch.id)
            .order_by(OrderLineItem.id)
            .all()
        )
        line_dicts = [{
            "ean": it.ean, "mpn": it.mpn, "sku": it.sku, "title": it.title,
            "quantity": it.quantity,
            "unit_price": float(it.unit_price) if it.unit_price is not None else None,
            "ship_to_name": it.ship_to_name,
            "ship_to_address1": it.ship_to_address1,
            "ship_to_address2": it.ship_to_address2,
            "ship_to_city": it.ship_to_city,
            "ship_to_state": it.ship_to_state,
            "ship_to_postal": it.ship_to_postal,
            "ship_to_country": it.ship_to_country,
            "ship_to_email": it.ship_to_email,
            "ship_to_phone": it.ship_to_phone,
        } for it in items]
        try:
            content = connector.build_payload(batch.po_number, line_dicts)
            if content:
                batch.file_content = content
                db.commit()
        except Exception:
            logger.exception("Could not rebuild payload for %s", batch.po_number)

    if not content:
        return PlainTextResponse(
            "No payload stored for this PO yet.", status_code=404,
        )

    filename = batch.file_name or f"{batch.po_number}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/fulfillments/{batch_id}", response_class=HTMLResponse)
async def fulfillment_detail(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    batch = db.query(POBatch).filter(POBatch.id == batch_id).first()
    if not batch:
        return HTMLResponse("Not found", status_code=404)

    items = (
        db.query(OrderLineItem)
        .filter(OrderLineItem.po_batch_id == batch.id)
        .order_by(OrderLineItem.id)
        .all()
    )

    # Aggregate audit trail across the batch's line items
    item_ids = [it.id for it in items]
    audit = []
    if item_ids:
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "order_line_item",
                AuditLog.entity_id.in_(item_ids),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(100)
            .all()
        )

    return _render(request, "fulfillment_detail.html", {
        "user": user,
        "batch": batch,
        "items": items,
        "audit": audit,
    })


# ---------------------------------------------------------------------------
# Legacy /orders — redirects to /fulfillments (keep the item-level detail view)
# ---------------------------------------------------------------------------

@router.get("/orders", response_class=HTMLResponse)
async def orders_redirect():
    return RedirectResponse(url="/fulfillments", status_code=301)


@router.get("/orders/{item_id}", response_class=HTMLResponse)
async def order_detail(request: Request, item_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    item = db.query(OrderLineItem).filter(OrderLineItem.id == item_id).first()
    if not item:
        return HTMLResponse("Not found", status_code=404)

    audit = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "order_line_item", AuditLog.entity_id == item_id)
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    return _render(request, "order_detail.html", {
        "user": user,
        "item": item,
        "audit": audit,
    })


@router.post("/orders/{item_id}/retry")
async def retry_order(request: Request, item_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        transition(db, item_id, "pending", {"reason": "manual retry"}, created_by=user)
        db.commit()
    except Exception as e:
        logger.warning("Retry failed for %d: %s", item_id, e)

    return RedirectResponse(url=f"/orders/{item_id}", status_code=303)


@router.post("/orders/{item_id}/cancel")
async def cancel_order(request: Request, item_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        transition(db, item_id, "cancelled", {"reason": "manual cancel"}, created_by=user)
        db.commit()
    except Exception as e:
        logger.warning("Cancel failed for %d: %s", item_id, e)

    return RedirectResponse(url=f"/orders/{item_id}", status_code=303)


# ---------------------------------------------------------------------------
# API endpoints (JSON)
# ---------------------------------------------------------------------------

@router.get("/api/health")
async def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "shadow_mode": config.SHADOW_MODE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/stats")
async def api_stats(db: Session = Depends(get_db)):
    return {
        "batches": dict(
            db.query(POBatch.status, func.count(POBatch.id))
            .group_by(POBatch.status).all()
        ),
        "items": dict(
            db.query(OrderLineItem.status, func.count(OrderLineItem.id))
            .group_by(OrderLineItem.status).all()
        ),
    }
