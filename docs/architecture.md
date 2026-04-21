# Order Automation Platform — Architecture

## Overview

Automated dropship order processing system that bridges Rithum (ChannelAdvisor) with vendor-specific EDI/email/B2B integrations. Pulls unshipped orders from Rithum, sends them to vendors, retrieves tracking, and pushes tracking back to Rithum.

## Data Flow

```
Rithum API (Unshipped Orders)
       │
       ▼  poll_rithum job (every 15 min)
┌─────────────────────────┐
│   PostgreSQL Database    │
│   (order_line_items)     │
│   status: pending        │
└─────────────────────────┘
       │
       ▼  place_orders job (every 15 min)
┌─────────────────────────┐
│   Vendor Connector       │
│   (REV'IT: SFTP EDI)    │
│   (Email: SMTP PDF)      │
│   status: submitted      │
└─────────────────────────┘
       │
       ▼  retrieve_tracking job (every 2 hrs)
┌─────────────────────────┐
│   Tracking Parser        │
│   (REV'IT: invoice CSV)  │
│   (Email: IMAP inbox)    │
│   status: shipped        │
└─────────────────────────┘
       │
       ▼  post_tracking job (every 15 min)
┌─────────────────────────┐
│   Rithum Fulfillments    │
│   POST /v1/Fulfillments  │
│   status: complete       │
└─────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Web Framework | FastAPI + Uvicorn |
| Dashboard UI | Jinja2 + HTMX + Tailwind CSS |
| Database | PostgreSQL (SQLAlchemy ORM, Alembic migrations) |
| Scheduler | APScheduler |
| SFTP | Paramiko |
| Email | imaplib / smtplib |
| Process Manager | systemd |

## Safety Mechanisms

| Risk | Prevention |
|------|-----------|
| Duplicate ingestion | `idempotency_key` UNIQUE constraint |
| Duplicate PO send | Row-level `SELECT FOR UPDATE` lock |
| Duplicate SFTP upload | `po_batches` UNIQUE po_number |
| Duplicate tracking writeback | Check `rithum_fulfillment_id IS NULL` |
| Dropped order | Hourly reconciliation vs Rithum |
| Stuck order | Alerts: pending >2h, submitted >48h |

## Database Tables

- **vendors** — Vendor configuration (code, name, connector type, JSONB config)
- **order_line_items** — Central state machine (one row per Rithum line item)
- **po_batches** — Every PO file sent to a vendor (with full content for audit)
- **audit_log** — Every state change and external API call
- **job_runs** — Scheduler execution history

## State Machine

```
pending → submitted → shipped → tracking_posted → complete
  ↓          ↓          ↓            ↓
failed    failed     failed       failed
  ↓
pending (retry)
```

## Vendor Connector Interface

Each vendor implements a connector class:
- `place_order(po_number, line_items)` — Send PO to vendor
- `retrieve_tracking()` — Fetch tracking updates
- `check_health()` — Test connectivity

### Connector Types
1. **revit_sftp** — SFTP-based EDI with CSV order files (REV'IT)
2. **email_pdf** — Email PDF PO + IMAP tracking monitor
3. **api** — Direct API/EDI connection (future)

## Deployment

Runs on EC2 instance (ftp.ridefivenine.com) alongside existing ascot and cron-jobs.
Uses systemd for process management, Nginx for reverse proxy + SSL.
Environment variables stored in `~/.ascot_env`.
