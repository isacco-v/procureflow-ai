# ProcureFlow AI

AI-assisted procurement reconciliation for construction purchasing. The target product compares purchase orders, delivery notes, and supplier invoices, then investigates exceptions with a bounded agent and a human decision.

This repository has a runnable API, a deterministic three-way matcher, and an admin shell that can inspect synthetic procurement cases. It does not upload documents, extract fields, investigate exceptions, or call a model.

- Product intent: [PROJECT_VISION.md](PROJECT_VISION.md)
- Technical design: [ARCHITECTURE.md](ARCHITECTURE.md)

## What runs today

- `GET /health` returns the service name, environment, and `ai_mode`. It does not contact the database or a model.
- `AI_MODE=mock` is the default. The mock provider is deterministic and makes no network call.
- `AI_MODE=openai` is rejected. The OpenAI SDK is not installed.
- PostgreSQL stores suppliers, procurement cases, source documents, purchase orders, delivery notes, invoices, and reconciliation runs. Alembic revisions are `20261116_0001` (empty baseline) and `20261116_0002` (domain tables).
- `POST /api/v1/dev/seed` loads five synthetic cases when `APP_ENV` is `local`, `test`, or `development`. Running it again does not duplicate them.
- `GET /api/v1/cases` and `GET /api/v1/cases/{case_id}` return those cases. Quantities and money are decimal strings.
- `POST /api/v1/cases/{case_id}/reconciliation` runs the matcher and stores the report. The same stored documents return the existing run.
- `GET /api/v1/cases/{case_id}/reconciliation` returns the latest findings.
- The Cases screen lists the synthetic cases, shows their lines, and displays the reconciliation report. It does not pretend to extract a PDF or explain an exception with a model.

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 22 and pnpm 10
- Docker, only when you want PostgreSQL
- git

The health endpoint and the matcher unit tests do not need Docker. API tests and `alembic upgrade` do. If PostgreSQL is not running, the API integration tests skip.

## Local setup

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
```

Backend, from `backend/`:

```bash
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend, from `frontend/`:

```bash
pnpm install
pnpm dev
```

The UI expects the API at `http://127.0.0.1:8000`. Change `VITE_API_BASE_URL` in `frontend/.env` if that is wrong. Restart Vite after changing it. The default uses `127.0.0.1` so the browser does not depend on `localhost` resolving to IPv6.

PostgreSQL, from the repository root, once Docker is installed:

```bash
docker compose up -d postgres
cd backend
uv run alembic upgrade head
```

The database user, password, and name in Compose are local defaults (`procureflow`). They match `DATABASE_URL` in `.env.example`. Do not reuse them on a shared server.

Load the synthetic cases once the API is running:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/dev/seed
```

The Cases screen can load the same data when the list is empty. The seed is refused when `APP_ENV` is anything other than `local`, `test`, or `development`.

## Checks

Backend:

```bash
cd backend
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

Frontend production build:

```bash
cd frontend
pnpm build
```

GitHub Actions runs the same backend checks and the frontend build.

## Configuration

Backend values live in the root `.env`. Frontend values live in `frontend/.env`.

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Reported by `/health` |
| `LOG_LEVEL` | Root logger level |
| `DATABASE_URL` | SQLAlchemy URL. Unused by `/health` |
| `CORS_ORIGINS` | Comma-separated browser origins |
| `AI_MODE` | `mock` or `openai` |
| `OPENAI_MODEL` | Reserved for a later provider |
| `OPENAI_API_KEY` | Optional. Not read by the mock provider. Do not commit it |
| `VITE_API_BASE_URL` | API origin baked into the frontend |

`VITE_` variables are embedded in the browser bundle. Do not put secrets in `frontend/.env`.

## Layout

```
backend/app/api        HTTP routes
backend/app/schemas    API models
backend/app/domain     Matching engine and synthetic scenarios
backend/app/services   Case queries, reconciliation persistence, seed
backend/app/core       Settings and logging
backend/app/db         Engine, session, SQLAlchemy models
backend/app/ai         Provider contract and mock
frontend/src           Admin shell, overview, and procurement cases
```

The matcher in `backend/app/domain/matching` does not import FastAPI, SQLAlchemy, or the model provider. It compares lines that share a product code, sums delivery notes, and uses `Decimal`. Different units or currencies are reported and are not converted. Descriptions are not treated as identity.

## Frontend attribution

The interface is based on [shadcn-admin](https://github.com/satnaing/shadcn-admin) by Sat Naing, MIT License, snapshot `2.2.1` at commit `e16c87f213a5ba5e45964e9b67c792105ec74d26`. The license is [frontend/LICENSE](frontend/LICENSE). Sample pages from that template (dashboard analytics, tasks, apps, chats, users, authentication demos, and Clerk) were removed. UI primitives and the application shell remain.

## Scope boundary

Implemented and planned work are separated in the two documents above. Do not describe this repository as a production system. No cloud project has been created, and no paid API is called.
