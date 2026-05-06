# Portfolio Trade Execution Engine

Single-click portfolio rebalancer with broker-agnostic execution. **5 Indian brokers supported** (Zerodha, Fyers, Upstox, Groww, Angel One) via a clean adapter pattern. Real broker auth + real broker quotes; orders are executed as **mock fills** locally per assignment scope (no real trades).


read the full docs here for v1 (all brokers) - 

read the docs for v2 (zerodha only) - 
## Quick start

```bash
docker compose up --build
```

Then open <http://localhost:8000>. Sign up (any email + 6-char password), pick a broker, enter your API credentials, connect, and execute a batch.

## Architecture

```
┌──────────┐   ┌────────────────────────┐   ┌──────────────┐
│  Browser │──▶│  FastAPI               │──▶│ BrokerAdapter│──▶ broker HTTP
│  (Alpine)│   │  ├ /auth /settings     │   │   (5 impls)  │
│          │◀──│  ├ /broker /execute    │◀──│              │
│  WS+poll │   │  └ /ws/notifications   │   └──────────────┘
└──────────┘   └────────┬───────────────┘
                        ▼
              SQLite (WAL) — users, holdings, batches, orders
```

- **FastAPI** for the HTTP + WebSocket surface
- **SQLite + WAL** for state — `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`. Concurrent reads + single writer, no extra service needed.
- **`asyncio.BackgroundTasks`** for execution — no Celery, no Redis. Simple and sufficient for single-user demo.
- **In-memory ConnectionManager** for WebSocket fanout.

## The Adapter Pattern (the assignment's core ask)

Every broker is an isolated module that implements one abstract interface:

```python
class BrokerAdapter(ABC):
    def get_login_url(self) -> str: ...
    def exchange_request_token(self, request_token: str) -> tuple[str|None, str|None]: ...
    def get_holdings(self) -> list[dict]: ...
    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict: ...
```

Adding a 6th broker = **one new file** + **one line in `factory.py`**. Routes, engine, schemas, and frontend stay untouched.

### Why thin custom adapters instead of an off-the-shelf unifying library

I considered libraries like `kiteconnect`, `fyers-apiv3`, `upstox-python-sdk` (the official per-broker SDKs) and unifying wrappers like OpenAlgo. The decision:

- **Per-broker official SDKs** lag behind broker API changes by weeks and bring heavyweight transitive deps (e.g. `kiteconnect` pulls `pyOpenSSL`, `cryptography`).
- **OpenAlgo-style unifying frameworks** are well-engineered but assume a much larger surface (master-contract DBs, websocket proxies, ZMQ, multi-tenant auth flows). For a focused engine, the dependency budget is wrong.
- **Plain `httpx` + per-broker HTTP client** is ~80 lines per broker, has zero hidden behavior, and is trivially debuggable. The auth flows (Kite checksum, Fyers app_id_hash, Upstox OAuth, Groww server-side checksum, Angel TOTP+JWT) each fit in 20 lines.

I distilled each broker's auth flow and quote endpoint by reading OpenAlgo's `auth_api.py` and `data.py` modules — those served as the **reference implementation** for the protocol details (hash construction, header shapes, response field names) without inheriting their framework dependencies.

### Per-broker auth flow summary (all 5 are real, not stubs)

| Broker  | Flow shape                  | Token returned       |
|---------|-----------------------------|----------------------|
| Zerodha | OAuth redirect → `request_token` | `access_token` (sha256 checksum)   |
| Fyers   | OAuth redirect → `auth_code`     | `access_token` (sha256 of `key:secret`) |
| Upstox  | OAuth redirect → `code`          | `access_token` (standard OAuth)    |
| Groww   | Server-side (no redirect)        | `token` (sha256 of `secret+ts`)    |
| Angel   | clientcode + PIN + TOTP          | `jwtToken`                         |

The `BrokerAdapter` interface absorbs these differences cleanly — Angel reuses the `api_secret` slot for `clientcode` and the `request_token` slot for `PIN:TOTP`; Groww ignores `request_token` entirely. The frontend renders the right form per broker by reading `/broker/auth-flows`.

## Execution semantics

- Caller sends explicit `BUY`/`SELL`/`REBALANCE` instructions (no delta calc — per spec).
- Engine **sorts SELLs before BUYs** so notional capital frees up first.
- For each instruction: try a **real broker quote** to source the fill price; on any failure (broker doesn't have data subscription, network error, etc.), fall back to a **deterministic mock price** derived from `sha256(symbol)`. Order is still marked FILLED with `error_message="filled_with_mock_price"` to make the fallback visible.
- Holdings table updated atomically per fill (weighted-avg cost on BUY, qty decrement on SELL, no shorting).
- On batch terminal state, `notify_batch_complete` fires:
  - Console log (always on)
  - WebSocket broadcast to all open tabs for the user
  - Frontend has a **polling fallback** that hits `GET /batches/{id}` every 1.5s if the WS connection fails to open within 3s

## Tech choices

| Concern              | Choice                          | Why                                                                |
|----------------------|---------------------------------|---------------------------------------------------------------------|
| Web framework        | FastAPI                         | Required by spec; native async + WS + Pydantic                      |
| Async work           | `BackgroundTasks` (in-process)  | Single-user demo — Celery/Redis are overkill                        |
| State                | SQLite + WAL                    | Durable, transactional, zero-ops; WAL handles concurrent reads      |
| Frontend             | Single HTML + Alpine.js + Tailwind CDN | No build step; ships in one file; matches assignment time budget |
| Broker integration   | Per-broker `httpx` clients      | Zero hidden behavior; ~80 lines/broker; easy to audit               |

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST   | `/auth/signup`, `/auth/login`, `/auth/logout` | account + JWT cookie |
| GET    | `/auth/me` | current user |
| POST   | `/settings/broker-credentials` | save api_key+secret per broker |
| GET    | `/settings/broker-status` | per-broker connection status |
| GET    | `/broker/auth-flows` | per-broker auth UX hints (used by frontend) |
| GET    | `/broker/{name}/login-url` | start OAuth (where applicable) |
| POST   | `/broker/{name}/callback` | finish auth (request_token, code, PIN:TOTP, or empty for Groww) |
| GET    | `/broker/{name}/holdings`, `/broker/{name}/quote/{symbol}` | broker reads |
| POST   | `/execute` | run an execution batch (BackgroundTask) |
| GET    | `/batches/{id}` | poll a batch's status |
| GET    | `/mock-holdings` | engine's local view of holdings |
| WS     | `/ws/notifications` | live `batch_complete` events |

## Running locally without Docker

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Project layout

```
app/
  main.py                  FastAPI app entrypoint
  config.py                env-driven settings
  db.py                    SQLite + WAL pragma setup
  models.py                SQLAlchemy ORM
  schemas.py               Pydantic request/response
  auth.py                  bcrypt + JWT
  routes/
    auth_routes.py         /auth/*
    settings_routes.py     /settings/*
    broker_routes.py       /broker/*
    execute_routes.py      /execute, /batches/{id}, /mock-holdings
    ws_routes.py           /ws/notifications
  brokers/
    base.py                BrokerAdapter ABC
    factory.py             registry + AUTH_FLOWS
    kite_client.py + zerodha_adapter.py
    fyers_client.py + fyers_adapter.py
    upstox_client.py + upstox_adapter.py
    groww_client.py + groww_adapter.py
    angel_client.py + angel_adapter.py
  engine/
    notifier.py            ConnectionManager + console + WS broadcast
    executor.py            sort SELL→BUY, mock fills, holdings update
frontend/
  index.html               single-page app (Tailwind CDN + Alpine + Oxygen Mono)
Dockerfile, docker-compose.yml, requirements.txt, README.md
```
