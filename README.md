# ProcureFlow AI

ProcureFlow AI helps a construction procurement reviewer check a purchase order, the delivery notes, and the supplier invoice before anyone is paid.

The reviewer uploads PDFs. The system reads the page text, proposes structured fields, and waits for an explicit accept. A deterministic matcher then compares quantities and unit prices. If the documents disagree, a bounded investigation can read the case, the match, the source lines, and the procurement policies. It returns a recommendation with the evidence it actually retrieved. A person still has to decide. Nothing in the system approves an invoice or starts a payment.

This is a portfolio project for a senior engineering review. The default process makes no paid model call.

- Product intent: [PROJECT_VISION.md](PROJECT_VISION.md)
- Technical design: [ARCHITECTURE.md](ARCHITECTURE.md)
- Interview walkthrough: [docs/INTERVIEW_DEMO.md](docs/INTERVIEW_DEMO.md)
- Historical live runs: [docs/LIVE_EXPERIMENT.md](docs/LIVE_EXPERIMENT.md)

## Business problem

Construction purchasing is three documents that should tell the same story. The purchase order says what was bought. Delivery notes say what arrived. The invoice says what the supplier wants to be paid. Someone has to compare them.

The comparison fails in ordinary ways. Descriptions differ for the same material. A supplier bills the ordered quantity after delivering less. Prices, units, or currencies do not match. References are missing. Sending the whole file to a model and trusting its arithmetic is a poor control: the result is hard to test and can be wrong in a fluent way.

ProcureFlow splits the work. Models may interpret text. Tested Python decides quantities, money, and whether a discrepancy exists.

## Architecture

One FastAPI process owns the API, the domain rules, and the database. The React admin shell is a separate static application. PostgreSQL is the system of record.

```mermaid
flowchart LR
  reviewer[Reviewer]
  web[React admin shell]
  api[FastAPI]
  parse[PyMuPDF parse]
  extract[Mock extractor]
  match[Deterministic matcher]
  graph[LangGraph investigation]
  gate[Evidence check]
  tools[Read-only tools]
  db[(PostgreSQL)]
  live[OpenAI adapters]

  reviewer --> web
  web -->|JSON over HTTP| api
  api --> parse
  parse --> extract
  extract --> db
  api --> match
  match --> db
  api --> graph
  graph --> tools
  tools --> db
  graph --> gate
  gate --> db
  graph -.-> live
  extract -.-> live
```

Solid arrows are the default local path. Dashed arrows are the OpenAI adapters. They stay closed unless `AI_MODE=openai`, the matching live flag, and a server-side API key are all set. The browser never receives that key.

## Technologies

| Piece | Responsibility |
| --- | --- |
| React, TypeScript, Vite, Tailwind, shadcn/ui | Admin shell: cases, documents, reconciliation, investigation |
| FastAPI, Pydantic | HTTP contracts and configuration |
| PostgreSQL, SQLAlchemy, Alembic | Cases, documents, match runs, policy sections, investigations |
| PyMuPDF | Page text from text PDFs. OCR is not implemented |
| Mock extractor | Reads labeled fields from the synthetic layouts. Not a language model |
| Pure Python matcher | Decimal quantities and prices. Same input, same report |
| LangGraph | Investigation state machine: decide, call tools, validate, or stop |
| PostgreSQL full-text search | Lexical policy retrieval and stored citations |
| OpenAI Python SDK, Responses API | Gated investigation and extraction adapters. Off by default |

## Deterministic and probabilistic parts

| Component | Kind | What it is allowed to decide |
| --- | --- | --- |
| Matcher | Deterministic | Whether a quantity, price, unit, currency, or reference discrepancy exists |
| Evidence check | Deterministic | Whether a proposed recommendation has the source lines and policy it needs |
| Policy search | Deterministic lexical search | Which stored sections a citation may use |
| Mock extractor and mock investigation | Scripted test doubles | The default demo. Repeatable, zero tokens, zero cost |
| OpenAI extractor and investigation | Probabilistic, gated off | Wording and tool choice, only in an explicitly enabled process |

A model is never the calculator for the match. The investigation reads the matcher's stored findings. It does not compute the gap again.

## Agentic workflow

The investigation is a LangGraph state machine. A fixed first step loads the stored reconciliation. The decision step then chooses read-only tools or a structured outcome. The tools are:

- `get_procurement_case`
- `get_reconciliation_findings`
- `get_purchase_order`
- `get_delivery_notes`
- `get_invoices`
- `search_procurement_policy`

There is no approve, pay, or write tool. In the default configuration the decision step is `MockInvestigationModel`. It branches on the finding codes and on which tools have already returned. That branching is scripted. The screen calls it a mock investigation.

`OpenAIInvestigationModel` is the live decision step. The model chooses the tools. The application executes them and sends the results back. The model finishes by calling `record_investigation_outcome`. That call is not a database tool.

## Evidence sufficiency

Two checks are separate. Schema validation asks whether the outcome matches `record_investigation_outcome`. The evidence gate then asks whether the tools actually returned the records that outcome relies on.

For a quantity finding, the gate requires the purchase-order line, every referenced delivery-note line, the invoice line, and policy `POL-QTY-001` both retrieved and cited. A document number that appears only inside the matcher finding does not count as a retrieved line. If the check fails and budget remains, the workflow returns the missing categories to the same decision step. It does not invent a tool sequence and it does not invent a line.

A quantity credit is accepted only when the outcome includes a structured prerequisite, `future_delivery` / `unconfirmed`. That status means the remaining quantity may still be delivered. The gate does not infer the condition from phrases in the summary. The scripted quantity result asks the supplier to clarify. It does not itself request a credit.

Every stored investigation has `review_required` true and `payment_authority` false. `evidence_validated` is true only when the sufficiency check accepted the outcome. An HTTP success can therefore be distinct from an evidence-validated investigation.

## What runs today

- `GET /health` returns the service name, environment, and `ai_mode`. It does not contact the database or a model.
- `AI_MODE=mock` is the default. A key in the environment does nothing while the live flags are false.
- PostgreSQL stores the procurement records, uploads, policy sections, and investigations. Alembic head is `20261117_0007`.
- `POST /api/v1/dev/seed` loads five synthetic cases in local, test, and development environments. Running it again does not duplicate them.
- Document upload checks the PDF signature, stores the bytes by SHA-256, parses page text, and runs the configured extractor. Acceptance is a separate request. A supplier document number that already exists returns 409 and leaves the existing row unchanged.
- Reconciliation is idempotent for the same lines and engine version.
- An investigation of an `EXCEPTION` or `NEEDS_REVIEW` run is stored. A repeat request for the same AI mode returns the latest attempt. A new attempt requires `X-Investigation-Attempt: new` and an `Idempotency-Key`. Mock and live rows are separate. Earlier rows are not overwritten.
- `uv run python -m app.demo`, from `backend/`, runs the Scenario B upload path on database `procureflow_demo`. It is a mock demonstration. It does not call OpenAI and it does not modify the configured database.

## Historical live result

The passing live investigation is [docs/experiments/PF-LIVE-INVESTIGATE-CASE-B-V4.txt](docs/experiments/PF-LIVE-INVESTIGATE-CASE-B-V4.txt). It is a recorded result from 17 November 2026. It is not a model call in progress, and this repository does not repeat it.

The seeded case `CASE-B-QUANTITY` had already been matched: product `CEM-II-25`, ordered 100 BAG, delivered 80 BAG, invoiced 100 BAG. The matcher codes were `ORDERED_NOT_DELIVERED` and `INVOICED_WITHOUT_DELIVERY`. The gap was 20 BAG.

The model, `gpt-5.4-mini`, first recorded `request_quantity_credit` before it had opened the source lines. The schema accepted that outcome. The evidence gate rejected it because the purchase-order line, the delivery-note line, and the invoice line had not been retrieved. The workflow returned those three gaps. The model then called `get_purchase_order`, `get_delivery_notes`, and `get_invoices`. The second credit was accepted. `evidence_validated` is true. The credit carries `future_delivery` / `unconfirmed`. `review_required` is true and `payment_authority` is false.

Recorded usage for that attempt: 14,022 input tokens, 1,375 output tokens, four model requests, estimated cost 0.016704 USD. The USD figure is the application's price table, not a provider invoice. HTTP duration was 15.249 seconds. Attempts 1, 2, and 3 remain stored as failures. The mock investigation on the same reconciliation remains a separate row with zero tokens.

A live extraction of the purchase-order PDF was also recorded once. See [docs/experiments/PF-LIVE-EXTRACT-PO-B.txt](docs/experiments/PF-LIVE-EXTRACT-PO-B.txt). The live end-to-end path, upload plus live extraction plus live investigation on an empty database, has not been run.

## Run locally

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22, pnpm 10, and Docker when you want PostgreSQL.

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
docker compose up -d postgres
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend, from `frontend/`:

```bash
pnpm install
pnpm dev
```

The UI expects the API at `http://127.0.0.1:8000`. On this machine `localhost` resolves to IPv6 first, and the API listens on IPv4 only. Load the synthetic cases once the API is running:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/dev/seed
```

The Cases screen can load the same data when the list is empty. Leave `AI_MODE=mock`. Do not set `INVESTIGATION_LIVE_ENABLED` or `EXTRACTION_LIVE_ENABLED`.

## Reproduce the demonstration

Two paths, on purpose. They are not interchangeable.

**Seeded case, in the UI.** Open Procurement cases and choose `CASE-B-QUANTITY`. The summary says 100 bags were ordered, 80 were delivered, and 100 were invoiced. Run reconciliation if it has not been stored. The matcher reports a 20 BAG gap. The latest mock investigation recommends supplier clarification, cites `POL-QTY-001`, names the purchase-order, delivery-note, and invoice lines, and stores the evidence flag as validated. Recorded tokens and cost are zero. Human review is required and payment authority is false. An earlier mock row that recommends a quantity credit remains stored and is not rewritten. Do not start another attempt during the demo. This path reads the seeded rows. It does not upload the PDFs, and it does not show the historical live attempt while the API is in mock mode. The isolated command below runs the same test double on `procureflow_demo`.

**Uploaded PDFs, isolated database.** Accepting `PO-B-100`, `DN-B-100`, or `INV-B-100` into the seeded database returns 409 and leaves the seed unchanged. That is the safety result. The complete upload path uses another database:

```bash
cd backend
uv run python -m app.demo
```

The command refuses to run unless `AI_MODE` and `DOCUMENT_EXTRACTOR` are `mock` and both live flags are false. It creates or reuses `procureflow_demo`, migrates it, resets only that database, uploads the three fixture PDFs, parses their page text, accepts the mock extraction, reconciles the 20 BAG gap, and runs the mock investigation. It then checks that the configured database, including any historical investigation rows, is unchanged.

To browse that upload case, start the API with the demonstration database and the demonstration file directory. Do not edit the live flags:

```bash
cd backend
DATABASE_URL=postgresql+psycopg://procureflow:procureflow@127.0.0.1:5432/procureflow_demo \
DOCUMENT_STORAGE_DIR=../var/demo-documents \
AI_MODE=mock \
INVESTIGATION_LIVE_ENABLED=false \
EXTRACTION_LIVE_ENABLED=false \
DOCUMENT_EXTRACTOR=mock \
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Stop that process and start the API again without those overrides to return to the seeded database. The step-by-step interview script is [docs/INTERVIEW_DEMO.md](docs/INTERVIEW_DEMO.md).

## Checks

Backend, from `backend/`:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv run alembic upgrade head
```

Frontend, from `frontend/`:

```bash
pnpm exec tsc -b
pnpm lint
pnpm build
```

GitHub Actions runs the backend checks with PostgreSQL and the frontend build. `GET /health` is the liveness check. It does not open a database connection.

## Configuration

Backend values live in the root `.env`. Frontend values live in `frontend/.env`.

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Reported by `/health` |
| `LOG_LEVEL` | Root logger level |
| `DATABASE_URL` | SQLAlchemy URL. Unused by `/health` |
| `CORS_ORIGINS` | Comma-separated browser origins |
| `AI_MODE` | `mock` or `openai`. `mock` is the default and makes no model call |
| `OPENAI_MODEL` | Model id for a live investigation. The recorded runs used `gpt-5.4-mini` |
| `OPENAI_API_KEY` | Server-side only. Ignored unless a live gate is open. Do not commit it |
| `OPENAI_REQUEST_TIMEOUT_SECONDS` | Per-request timeout. Default 30, also capped by the time left in the investigation |
| `OPENAI_INPUT_USD_PER_MILLION` | Price-table input rate. Default `0.75` |
| `OPENAI_OUTPUT_USD_PER_MILLION` | Price-table output rate. Default `4.50` |
| `INVESTIGATION_MAX_ITERATIONS` | Decision steps. Default 8 |
| `INVESTIGATION_MAX_TOOL_CALLS` | Tool executions, including the initial findings load. Default 12 |
| `INVESTIGATION_MAX_LLM_REQUESTS` | Model requests before the next one is skipped. Default 6 |
| `INVESTIGATION_MAX_OUTPUT_TOKENS` | `max_output_tokens` for each model request. Default 1200 |
| `INVESTIGATION_TIMEOUT_SECONDS` | Wall-clock budget. Default 90 |
| `INVESTIGATION_MAX_ESTIMATED_COST_USD` | Estimated investigation budget. Default `0.10`. Not an invoice |
| `INVESTIGATION_LIVE_ENABLED` | Must be `true`, with `AI_MODE=openai` and a server key, before a live investigation. Default `false` |
| `DOCUMENT_EXTRACTOR` | `mock` or `openai`. Default `mock` |
| `DOCUMENT_STORAGE_DIR` | Local directory for uploaded PDFs. Default `var/documents` |
| `DOCUMENT_MAX_BYTES` | Upload size limit. Default 10485760 |
| `DOCUMENT_MAX_PAGES` | Page limit. Default 20 |
| `EXTRACTION_LIVE_ENABLED` | Must be `true` with the other extraction gates before a live extraction. Default `false` |
| `EXTRACTION_MAX_OUTPUT_TOKENS` | Extraction output cap. Default 2000 |
| `EXTRACTION_MAX_ESTIMATED_COST_USD` | Estimated extraction budget. Default `0.05`. Separate from the investigation budget |
| `EXTRACTION_REQUEST_TIMEOUT_SECONDS` | Live extraction timeout. Default 20 |
| `VITE_API_BASE_URL` | API origin baked into the frontend |

`VITE_` variables are embedded in the browser bundle. Do not put secrets in `frontend/.env`.

Application budgets are estimated safeguards, not guaranteed provider billing caps. The live client uses `max_retries=0`. A request body cannot set the mode, the live flags, or the key.

## Layout

```
backend/app/api        HTTP routes
backend/app/schemas    API models
backend/app/domain     Matcher, scenarios, investigation contracts, policies
backend/app/documents  PDF parsing, mock and gated extractors, fixtures
backend/app/services   Cases, reconciliation, intake, retrieval, investigation
backend/app/ai         Mock providers and the gated OpenAI adapters
backend/app/demo       Isolated mock end-to-end demonstration
frontend/src           Admin shell, overview, documents, and cases
docs/experiments       Historical live reports. Do not rewrite them
```

## Frontend attribution

The interface is based on [shadcn-admin](https://github.com/satnaing/shadcn-admin) by Sat Naing, MIT License, snapshot `2.2.1` at commit `e16c87f213a5ba5e45964e9b67c792105ec74d26`. The license is [frontend/LICENSE](frontend/LICENSE). Sample pages from that template were removed. UI primitives and the application shell remain.

## Limitations

No human approval is stored. OCR and semantic retrieval are not implemented. Lexical search can return a section the recommendation does not cite. The price-table cost is not an invoice. There is no authentication, no rate limit, and no public deployment. The mock extractor score is not a language-model measurement. Do not describe this repository as a production system.
