# ProcureFlow AI

AI-assisted procurement reconciliation for construction purchasing. The target product compares purchase orders, delivery notes, and supplier invoices, then investigates exceptions with a bounded agent and a human decision.

This repository has a runnable API, a deterministic three-way matcher, a lexical procurement-policy corpus, PDF intake, and an admin shell that can inspect synthetic cases, uploaded documents, and their investigations. The investigation workflow uses LangGraph. In the default configuration its tool choices come from a deterministic test double, not from a language model. Document extraction defaults to a separate deterministic test double. OpenAI adapters for investigation and extraction are implemented and left disabled. The process does not call a paid model. OCR is not implemented.

- Product intent: [PROJECT_VISION.md](PROJECT_VISION.md)
- Technical design: [ARCHITECTURE.md](ARCHITECTURE.md)

## What runs today

- `GET /health` returns the service name, environment, and `ai_mode`. It does not contact the database or a model.
- `AI_MODE=mock` is the default. The mock provider is deterministic and makes no network call.
- `AI_MODE=openai` does not by itself call a model. A live investigation also needs `INVESTIGATION_LIVE_ENABLED=true` and a server-side `OPENAI_API_KEY`. All three are off in the default configuration. The completion helper still refuses `openai` and never builds a client.
- PostgreSQL stores suppliers, procurement cases, source documents, purchase orders, delivery notes, invoices, reconciliation runs, policy sections, and investigations. Alembic revisions are `20261116_0001` (empty baseline), `20261116_0002` (domain tables), `20261117_0003` (policy and investigation tables), `20261117_0004` (document intake), `20261117_0005` (separate mock and live rows), and `20261117_0006` (investigation attempts). Existing investigation rows are not rewritten.
- `POST /api/v1/dev/seed` loads five synthetic cases when `APP_ENV` is `local`, `test`, or `development`. Running it again does not duplicate them.
- `GET /api/v1/cases` and `GET /api/v1/cases/{case_id}` return those cases. Quantities and money are decimal strings.
- `POST /api/v1/cases/{case_id}/reconciliation` runs the matcher and stores the report. The same stored documents return the existing run.
- `GET /api/v1/cases/{case_id}/reconciliation` returns the latest findings.
- `POST /api/v1/cases/{case_id}/reconciliation/{run_id}/investigations` investigates an `EXCEPTION` or `NEEDS_REVIEW` run. A second request for the same AI mode returns the latest attempt and does not start another one. A new attempt requires `X-Investigation-Attempt: new` and an `Idempotency-Key`. The same key returns that attempt. A mock investigation is not returned when the process is in live mode, and earlier rows are left in place. `MATCHED` runs are refused. The request does not accept a prompt. `evidence_validated` reports whether the sufficiency check accepted the outcome.
- `GET /api/v1/cases/{case_id}/reconciliation/{run_id}/investigation` and `GET /api/v1/cases/{case_id}/investigations/{investigation_id}/events` return the stored result and the tool history.
- The investigation tools are read-only. They cannot approve an invoice or change a reconciliation. While `AI_MODE=mock`, the decision step is a scripted test double. The response says so, and token and cost figures are zero.
- Six versioned synthetic policies are retrieved with PostgreSQL full-text search. That retrieval is lexical. Semantic retrieval is not implemented.
- The Cases screen lists seeded cases and cases created from accepted uploads, shows their lines and reconciliation report, and can start an investigation for an exception. A mock run is labeled **Mock investigation**. It is not labeled as live model reasoning.
- `POST /api/v1/documents` accepts one PDF. The file name is stored for display and is not used to classify the document. The same SHA-256 and the same extractor return the existing extraction. A mock extraction does not satisfy a request for live extraction, and the mock row is kept. Limits, the PDF signature, and a readable PDF are checked before the bytes are kept.
- `GET /api/v1/documents` and `GET /api/v1/documents/{document_id}` return processing status, page text, the mock or live extractor label, validation warnings, and source snippets.
- `POST /api/v1/documents/{document_id}/accept` writes a non-seed procurement case from a reviewed extraction and runs the matcher. It does not overwrite an existing supplier document with the same number. A second accept returns the same case.
- Uploaded cases use `origin=upload` and `synthetic=false`. Seeded cases stay `origin=synthetic_seed`. Image-only PDFs are stored as needing review. OCR and vision are not implemented, and the API says so.
- `DOCUMENT_EXTRACTOR=mock` is the default. A live extraction also needs `AI_MODE=openai`, `EXTRACTION_LIVE_ENABLED=true`, and a server-side `OPENAI_API_KEY`. That budget is separate from the investigation budget. Leave the live flag false.
- `uv run python -m app.documents.evaluate` scores the mock extractor against the synthetic PDF catalog. The report says it is not a language-model measurement.

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

## Mock and live investigation

The default run is a mock investigation. `MockInvestigationModel` chooses tools from the stored finding codes. It does not call a language model. The screen and the API say so.

The live path is `OpenAIInvestigationModel`. It uses the official OpenAI Python SDK and the Responses API. The configured model is `gpt-5.4-mini` unless `OPENAI_MODEL` is changed. The model receives the read-only tool schemas and chooses which ones to call. LangGraph executes those calls, sends the tool results back, and asks the model again. The model finishes by calling `record_investigation_outcome`. That call is not a database tool. The workflow checks every policy code and evidence label against data the tools actually returned. It then checks primary line evidence for the finding type. A missing purchase-order, delivery-note, or invoice line rejects the outcome and returns the missing categories to the model, which still chooses the next tools. A citation or label that was not retrieved is rejected. If the limits run out before the lines are retrieved, the result is inconclusive and names the gap. A weak or refused result is inconclusive. Human review stays required, and nothing in the run can approve a payment. The scripted mock is still a test double. It is not the live model's tool plan.

Document text and policy text are sent as untrusted data. They do not replace the system instructions or the tool list. Tool arguments are validated again on the server. The model cannot run a query, read the filesystem, or open its own network connection.

Live execution is impossible unless all three of these are true in the API process:

- `AI_MODE=openai`
- `INVESTIGATION_LIVE_ENABLED=true`
- `OPENAI_API_KEY` is set in the server environment and is not blank

A request body cannot set any of them. A key alone does nothing while the live flag is false. This repository leaves the flag false. Do not turn it on for a public demo.

The application budget for one investigation defaults to `$0.10`. The extraction budget defaults to `$0.05`. Application budgets are estimated safeguards, not guaranteed provider billing caps. Before each model request the adapter reserves input tokens from the prompt size and output tokens at `INVESTIGATION_MAX_OUTPUT_TOKENS`. If the reservation is larger than the remaining budget, the request is not sent. A response can still cost more than the reservation if the provider counts tokens differently. When that happens the recommendation is discarded and the run is marked `budget_exceeded`, but the provider may already have billed the request. The client uses `max_retries=0`, so the application does not send that request again. The default rates for `gpt-5.4-mini` are `$0.75` per million input tokens and `$4.50` per million output tokens. Change `OPENAI_INPUT_USD_PER_MILLION` and `OPENAI_OUTPUT_USD_PER_MILLION` to reprice the configured model. An unlisted model name is not given a guessed rate.

Other limits, all counted inside one investigation:

| Limit | Default | What happens |
| --- | --- | --- |
| Model requests | 6 | The next request is not sent |
| Decision iterations | 8 | The run stops before another decision |
| Tool calls | 12 | Includes the workflow's first findings load |
| Output tokens | 1200 | Sent as `max_output_tokens` |
| Request timeout | 10 seconds | Capped by the time still left in the run |
| Wall clock | 15 seconds | The run stops before the next step |
| Estimated cost | $0.10 | See the reservation rules above |

The live client uses `max_retries=0` and `store=false`. Conversation state for the next tool round is the prior response output, including reasoning items and their encrypted content, plus one `function_call_output` per `call_id`. That list lives in memory for the request only. Hidden reasoning text is not written to the investigation record or the logs. The Cases screen shows a live run as **Live LLM investigation**, with the model id, status, tool events, evidence, recommendation, token counts, and the estimated USD cost.

To enable a live call later, set the gates in the server environment and restart the API. Keep the frontend free of secrets. The controlled procedure, pass and fail rules, and report format are in [docs/LIVE_EXPERIMENT.md](docs/LIVE_EXPERIMENT.md). This task did not enable live mode and did not send a request to OpenAI.

## Configuration

Backend values live in the root `.env`. Frontend values live in `frontend/.env`.

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Reported by `/health` |
| `LOG_LEVEL` | Root logger level |
| `DATABASE_URL` | SQLAlchemy URL. Unused by `/health` |
| `CORS_ORIGINS` | Comma-separated browser origins |
| `AI_MODE` | `mock` or `openai`. `mock` is the default and makes no model call |
| `OPENAI_MODEL` | Model id for a live investigation. Default `gpt-5.4-mini` |
| `OPENAI_API_KEY` | Server-side only. Ignored unless live mode is fully enabled. Do not commit it |
| `OPENAI_REQUEST_TIMEOUT_SECONDS` | Per-request timeout for the Responses API. Default 10 |
| `OPENAI_INPUT_USD_PER_MILLION` | Price-table input rate. Default `0.75` |
| `OPENAI_OUTPUT_USD_PER_MILLION` | Price-table output rate. Default `4.50` |
| `INVESTIGATION_MAX_ITERATIONS` | Decision steps before the run stops. Default 8 |
| `INVESTIGATION_MAX_TOOL_CALLS` | Tool executions, including the initial findings load. Default 12 |
| `INVESTIGATION_MAX_LLM_REQUESTS` | Model requests before the next one is skipped. Default 6 |
| `INVESTIGATION_MAX_OUTPUT_TOKENS` | `max_output_tokens` for each model request. Default 1200 |
| `INVESTIGATION_TIMEOUT_SECONDS` | Wall-clock budget for one investigation. Default 15 |
| `INVESTIGATION_MAX_ESTIMATED_COST_USD` | Estimated budget for one investigation. Default `0.10`. Not an invoice |
| `INVESTIGATION_LIVE_ENABLED` | Must be `true`, with `AI_MODE=openai` and a server key, before a live investigation call. Default `false` |
| `DOCUMENT_EXTRACTOR` | `mock` or `openai`. Default `mock`. The mock reads labeled page text and does not call a model |
| `DOCUMENT_STORAGE_DIR` | Local directory for uploaded PDFs. Default `var/documents` at the repository root. Not inside the application package |
| `DOCUMENT_MAX_BYTES` | Upload size limit. Default 10485760 |
| `DOCUMENT_MAX_PAGES` | Page limit. Default 20 |
| `EXTRACTION_LIVE_ENABLED` | Must be `true`, with `DOCUMENT_EXTRACTOR=openai`, `AI_MODE=openai`, and a server key, before a live extraction call. Default `false` |
| `EXTRACTION_MAX_OUTPUT_TOKENS` | `max_output_tokens` for one extraction request. Default 2000 |
| `EXTRACTION_MAX_ESTIMATED_COST_USD` | Estimated budget for one extraction. Default `0.05`. Separate from the investigation budget. Not an invoice |
| `EXTRACTION_REQUEST_TIMEOUT_SECONDS` | Per-request timeout for a live extraction. Default 20 |
| `VITE_API_BASE_URL` | API origin baked into the frontend |

`VITE_` variables are embedded in the browser bundle. Do not put secrets in `frontend/.env`.

## Layout

```
backend/app/api        HTTP routes
backend/app/schemas    API models
backend/app/domain     Matching engine, scenarios, investigation contracts, policies
backend/app/documents  PDF parsing, mock and gated OpenAI extractors, validation, synthetic fixtures, evaluation
backend/app/services   Case queries, reconciliation, document intake, lexical retrieval, investigation
backend/app/core       Settings and logging
backend/app/db         Engine, session, SQLAlchemy models
backend/app/ai         Provider contract, mock completion, investigation test double, gated OpenAI adapter
frontend/src           Admin shell, overview, documents, and procurement cases
```

The matcher in `backend/app/domain/matching` does not import FastAPI, SQLAlchemy, or the model provider. It compares lines that share a product code, sums delivery notes, and uses `Decimal`. Different units or currencies are reported and are not converted. Descriptions are not treated as identity. The investigation reads the matcher's stored findings. It does not recalculate them.

## Frontend attribution

The interface is based on [shadcn-admin](https://github.com/satnaing/shadcn-admin) by Sat Naing, MIT License, snapshot `2.2.1` at commit `e16c87f213a5ba5e45964e9b67c792105ec74d26`. The license is [frontend/LICENSE](frontend/LICENSE). Sample pages from that template (dashboard analytics, tasks, apps, chats, users, authentication demos, and Clerk) were removed. UI primitives and the application shell remain.

## Scope boundary

Implemented and planned work are separated in the two documents above. Do not describe this repository as a production system. No cloud project has been created, and no paid API is called.
