# TrackBridge

Cargo tracking MVP for China → Kazakhstan: warehouse workers scan parcels on a phone (PWA), clients and managers in Kazakhstan get Telegram / WhatsApp notifications.

**Stack:** FastAPI · PostgreSQL · SQLAlchemy 2 (async) · Alembic · Jinja2 + HTMX + Alpine.js + Tailwind (no Node build) · aiogram 3 · WhatsApp Cloud API · Docker Compose.

## Quick start

```bash
cp .env.example .env          # set API_KEYS at minimum
docker compose up --build     # runs migrations, then serves on :8000
```

- Scanner PWA: http://localhost:8000/warehouse/scan (⚙️ → enter API key, worker ID, warehouse)
- Admin UI (register parcels, browse/search recent ones): http://localhost:8000/admin. It shares the API key and worker ID stored in the browser with the scanner page.
- API docs: http://localhost:8000/docs

The camera scanner needs **HTTPS** on phones (browser rule). Put Caddy/nginx/Cloudflare Tunnel in front for production. A USB/Bluetooth barcode scanner works without HTTPS: scan → Enter jumps to weight → Enter submits.

## Local development (without Docker)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+asyncpg://trackbridge:trackbridge@localhost:5432/trackbridge API_KEYS=dev
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
.venv/bin/pytest            # tests use a temp SQLite DB, no Postgres needed
```

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET  | `/warehouse/scan` | — (key entered in UI) | Mobile scanner page |
| GET  | `/admin` | — (key entered in UI) | Admin page: register parcels, search recent ones |
| POST | `/api/v1/parcels/receive` | `X-API-Key` | Scan: set weight/volume, status → `received_at_china_wh`, notify |
| GET  | `/api/v1/parcels/track/{code}` | public | Status + history (no PII) |
| POST | `/api/v1/parcels` | `X-API-Key` | Register a parcel (client phone/name) |
| GET  | `/api/v1/parcels/{code}` | `X-API-Key` | Full parcel incl. client & audit log |
| POST | `/api/v1/parcels/{code}/status` | `X-API-Key` | Advance status (`in_transit`, `customs`, …), notify |
| GET/POST | `/api/v1/warehouses` | `X-API-Key` | List / create warehouses |
| POST | `/telegram/webhook` | Telegram secret header | Bot updates |
| GET  | `/health` | — | Liveness + DB check |

Optional `X-Worker-Id` header is stored in `status_history.changed_by`.

Errors are JSON: `{"detail": "...", "code": "not_found" | "conflict"}` (404/409); 401 for a bad key; 422 for validation.

### Behaviour notes
- Tracking codes are trimmed and upper-cased; phones normalized to E.164 (`8 701…` → `+7701…`).
- Statuses only move **forward**; going backwards returns 409.
- Re-scanning an already received parcel updates weight/volume, returns `status_changed: false` and sends no duplicate notification. Scanning a parcel that has already shipped returns 409.
- The status change uses `SELECT … FOR UPDATE`, so two workers scanning the same box at once won't both send a notification.

## Notifications

Each channel turns on when its env vars are set (see `.env.example`). A failure in one channel never blocks the others.

**Telegram:** create a bot with @BotFather, set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `PUBLIC_BASE_URL` (HTTPS). The webhook is registered on startup. Clients press /start → *Share phone number*. This links their chat to the phone stored on their parcels. They can also send a tracking code to check its status. `TELEGRAM_MANAGER_CHAT_IDS` get every status change.

**WhatsApp:** set `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID`. For production, create and approve a template in Meta Business Manager with 3 body params (`{{1}}` code, `{{2}}` status, `{{3}}` name) and set `WHATSAPP_TEMPLATE_NAME`. Without a template, plain text is sent, which Meta only delivers inside the 24h customer service window. Transient errors (429/5xx/network) are retried 3×.

## Known MVP limitations / next steps
- Notifications run as FastAPI `BackgroundTasks` after commit. If the process restarts between commit and send, that notification is lost. Upgrade path: write an `outbox` row in the same transaction and drain it with a worker.
- One shared API key per device and no per-worker accounts. Rotate keys via `API_KEYS` (comma-separated, several may be valid at once).
- The admin UI registers and lists parcels only. Changing a status past "received" (in transit, customs, …) and creating warehouses still go through `/docs` or the API.
- Tailwind is loaded from its play CDN (fine for an internal tool; switch to the standalone CLI if page weight matters).
