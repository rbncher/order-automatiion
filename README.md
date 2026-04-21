# Order Automation Platform

Automated dropship order processing for Speed Addicts. Pulls unshipped orders from Rithum (ChannelAdvisor), sends them to vendor-specific integrations (EDI/SFTP, email, B2B), retrieves tracking, and pushes tracking back to Rithum.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (or source ~/.ascot_env)
export RITHUM_APP_ID=...
export RITHUM_SECRET=...
export RITHUM_REFRESH_TOKEN=...

# Run (starts FastAPI + scheduler)
python main.py
```

Dashboard: http://localhost:8000 (default login: admin / changeme)

## Architecture

See [docs/architecture.md](docs/architecture.md) for full details.

```
Rithum API → poll_rithum → DB (pending) → place_orders → Vendor SFTP/Email
                                                              ↓
Rithum API ← post_tracking ← DB (shipped) ← retrieve_tracking ← Vendor
```

## Current Vendors

| Vendor | Code | Type | Status |
|--------|------|------|--------|
| REV'IT! | REV | SFTP EDI | Phase 1 |

## Environment Variables

### Required
- `RITHUM_APP_ID` — Rithum OAuth2 app ID
- `RITHUM_SECRET` — Rithum OAuth2 secret
- `RITHUM_REFRESH_TOKEN` — Rithum OAuth2 refresh token

### REV'IT (when ready)
- `REVIT_SFTP_HOST` — REV'IT SFTP hostname
- `REVIT_SFTP_USER` — SFTP username
- `REVIT_SFTP_PASS` — SFTP password
- `REVIT_SELL_TO_CUSTOMER` — Your REV'IT customer number
- `REVIT_BILL_TO_CUSTOMER` — Bill-to customer number

### Dashboard
- `DASHBOARD_USERS` — Format: `admin:sha256hash,viewer:sha256hash`
- `SESSION_SECRET` — Random secret for session cookies
- `APP_PORT` — Web server port (default: 8000)

### Optional
- `DATABASE_URL` — PostgreSQL connection string (default: SQLite)
- `SHADOW_MODE` — `true` to generate orders without sending (default: true)
- `LOG_LEVEL` — INFO, DEBUG, WARNING (default: INFO)

## Running Tests

```bash
python -m pytest tests/ -v
```

## Project Structure

```
order-automation/
├── main.py                 # FastAPI + scheduler entrypoint
├── config.py               # Environment variables and constants
├── core/                   # Database, models, state machine, safety
├── clients/                # Rithum API client, SFTP client
├── connectors/             # Vendor integrations (REV'IT, email, etc.)
├── jobs/                   # Scheduled jobs (poll, place, track, reconcile)
├── api/                    # FastAPI routes and auth
├── templates/              # Jinja2 + HTMX dashboard templates
├── tests/                  # Unit tests
└── docs/                   # Architecture and EDI specs
```

## Safety

- **No duplicates**: Idempotency keys with UNIQUE constraints
- **No dropped orders**: Hourly reconciliation against Rithum
- **Audit trail**: Every state change logged
- **Shadow mode**: Validate orders before enabling live submission
