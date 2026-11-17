# Controlled live experiment

Extraction test PF-LIVE-EXTRACT-PO-B was run once. Its report is [experiments/PF-LIVE-EXTRACT-PO-B.txt](experiments/PF-LIVE-EXTRACT-PO-B.txt). Investigation test PF-LIVE-INVESTIGATE-CASE-B was run once. Its report is [experiments/PF-LIVE-INVESTIGATE-CASE-B.txt](experiments/PF-LIVE-INVESTIGATE-CASE-B.txt). The separate retest PF-LIVE-INVESTIGATE-CASE-B-V2 was run once and failed. Its report is [experiments/PF-LIVE-INVESTIGATE-CASE-B-V2.txt](experiments/PF-LIVE-INVESTIGATE-CASE-B-V2.txt). The separate retest PF-LIVE-INVESTIGATE-CASE-B-V3 was run once and failed. Its report is [experiments/PF-LIVE-INVESTIGATE-CASE-B-V3.txt](experiments/PF-LIVE-INVESTIGATE-CASE-B-V3.txt). The separate retest PF-LIVE-INVESTIGATE-CASE-B-V4 was run once and passed. Its report is [experiments/PF-LIVE-INVESTIGATE-CASE-B-V4.txt](experiments/PF-LIVE-INVESTIGATE-CASE-B-V4.txt). These reports are historical live results. They are separate from the mock scores, and they are not a model call in progress. Live mode is off. Do not start a V5 investigation automatically.

A mock end-to-end demonstration of Scenario B is also separate. It uploads the three synthetic PDFs on an isolated database, accepts the mock extraction, reconciles the 20 BAG gap, and runs the scripted investigation. It does not call OpenAI. Run it with `uv run python -m app.demo` from `backend/`. The live upload path, PF-LIVE-E2E-CASE-B, has not been run.

Application budgets are estimated safeguards, not guaranteed provider billing caps. A reservation can be lower than the provider invoice. `max_retries=0`, so a failed request is not sent again by the SDK. Uploading the same bytes again returns the stored extraction for that extractor and does not send another request.

Mock results and live results are stored separately. A mock investigation on a reconciliation run is left in place when a live investigation is requested. A mock extraction of a PDF is left in place when a live extraction is requested. Seeded cases stay `origin=synthetic_seed`. Accepting an upload does not overwrite them.

Run the preparation check, which only reads the catalog:

```bash
cd backend
uv run python -m app.experiments
```

## Shared gates

Leave these false until a person authorizes the spend. Set them in the API process environment, not in `frontend/.env`, and restart the API. The request body cannot set them.

| Variable | Extraction test | Investigation test |
| --- | --- | --- |
| `AI_MODE` | `openai` | `openai` |
| `OPENAI_MODEL` | `gpt-5.4-mini` | `gpt-5.4-mini` |
| `OPENAI_API_KEY` | server-side key | server-side key |
| `DOCUMENT_EXTRACTOR` | `openai` | `mock`, unless a new extraction is intended |
| `EXTRACTION_LIVE_ENABLED` | `true` | `false` |
| `INVESTIGATION_LIVE_ENABLED` | `false` | `true` |

Defaults that stay in force: extraction budget `$0.05`, investigation budget `$0.10`, extraction output cap `2000`, investigation output cap `1200`, investigation model requests `6`, client `max_retries=0`, Responses `store=false`, investigation request timeout `30` seconds, investigation wall clock `90` seconds. The per-request timeout is reduced to the time still left in that wall clock. A timeout stores a diagnostic and does not send the request again. Output tokens include reasoning tokens. The investigation follow-up also sends `include: ["reasoning.encrypted_content"]` and replays the prior output items. Those items are not written to the investigation record.

Confirm the schema is at head without resetting data:

```bash
cd backend
uv run alembic upgrade head
```

After either test, set both live flags back to `false` and restart. Do not deploy the process while either flag is true.

## A. PF-LIVE-EXTRACT-PO-B

Input: `backend/app/documents/fixtures/pdfs/works_order-po-b-100.pdf`.

Catalog row: `CASE-B-QUANTITY`, purchase order `PO-B-100`, supplier `SUP-HELIOS`, date `2026-03-02`, currency `EUR`, net `450`, one line `CEM-II-25`, quantity `100`, unit `BAG`, unit price `4.5`, line total `450`. Tax fields are null. The file name and the content hash are not inputs to the extractor.

```bash
curl -sS -D - -o /tmp/procureflow-po-b.json \
  -F "file=@app/documents/fixtures/pdfs/works_order-po-b-100.pdf;type=application/pdf" \
  http://127.0.0.1:8000/api/v1/documents
```

Run that from `backend/`. Do not accept the document. Acceptance of `PO-B-100` into a database that already contains the synthetic seed returns 409 and leaves the seeded purchase order unchanged. That is the expected safety result, not a live extraction score.

Expected:

- `extractor` is `openai`, `mocked` is false, `reasoning_kind` is `language_model`, `model_name` is `gpt-5.4-mini`.
- The structured object matches the catalog fields above, including null tax fields.
- Every source snippet is a substring of the page it cites.
- `input_tokens` and `output_tokens` are present. `estimated_cost_usd` is a price-table estimate. It is not an invoice.
- The response status is `needs_review` unless the request failed.

Pass: all of the expected items hold, and `assess_live_extraction` would return no reasons.

Fail: a mock row is returned, a quantity or price differs, a null catalog field is filled in, a snippet is not on the cited page, the schema is rejected, or the call is refused, incomplete, or timed out.

A second upload of the same file returns the stored live row and does not send another request. To try once more after a stored failure, delete that `document_extractions` row for `provider=openai` and upload again. Do not delete the mock row or the seeded cases.

## B. PF-LIVE-INVESTIGATE-CASE-B

Input: seeded case `CASE-B-QUANTITY`. The matcher has already stored ordered `100`, delivered `80`, invoiced `100`. The investigation must not recompute those figures.

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/dev/seed
CASE=$(curl -sS http://127.0.0.1:8000/api/v1/cases | python -c \
  "import json,sys; rows=json.load(sys.stdin)['cases']; \
   print(next(row['id'] for row in rows if row['reference']=='CASE-B-QUANTITY'))")
RUN=$(curl -sS -X POST "http://127.0.0.1:8000/api/v1/cases/$CASE/reconciliation")
RUN_ID=$(printf '%s' "$RUN" | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
curl -sS -D - -X POST \
  "http://127.0.0.1:8000/api/v1/cases/$CASE/reconciliation/$RUN_ID/investigations"
```

If a mock investigation already exists, this request adds a live row. The mock row stays. Read the live row by its id. `GET .../investigation` returns the row for the process `AI_MODE` only.

Expected:

- `ai_mode` is `openai`, `provider` is `openai`, `mock_execution` is false, `model_name` is `gpt-5.4-mini`.
- `review_required` is true and `payment_authority` is false.
- Status `completed` with `request_quantity_credit` or `request_supplier_clarification`.
- The summary does not say an invoice was approved or a payment was initiated.
- If the summary states the quantities, they agree with the matcher: ordered 100, delivered 80, invoiced 100, gap 20.
- The event trace includes `get_reconciliation_findings`, `search_procurement_policy`, and at least one of `get_purchase_order`, `get_delivery_notes`, and `get_invoices`.
- Every citation `section_code` appears in a tool event's `policy_section_codes`.
- Every evidence label appears in a tool event's `evidence_labels`.
- Event payloads have no `reasoning`, `chain_of_thought`, or `encrypted_content`.
- Token counts and `estimated_cost_usd` are present. The USD figure is an estimate.

Pass: the items above hold. `assess_live_quantity_investigation` returns no reasons.

Fail: the stored mock row is returned as the live result, a citation or label was not retrieved, the summary claims a payment, `review_required` is false, or `payment_authority` is true.

A budget stop (`budget_exceeded`) with no recommendation is a safety stop, not a pass, and not a reason to retry automatically. An incomplete model response is `invalid_output`. A timeout is `timed_out`. The provider may already have billed a request that the application then discards. Record the status and do not send the request again unless a person authorizes one more run.

The stored result of this test is the failed report [experiments/PF-LIVE-INVESTIGATE-CASE-B.txt](experiments/PF-LIVE-INVESTIGATE-CASE-B.txt). Do not delete that investigation. A plain `POST` to the same URL returns it and does not start another model run.

## C. PF-LIVE-INVESTIGATE-CASE-B-V2

This is a second live attempt on the same seeded reconciliation run. It does not replace attempt 1. Run it only after a person authorizes one more spend. Leave the extraction flag false.

Use the same case and run lookup as test B, then send an explicit attempt:

```bash
curl -sS -D - -X POST \
  -H "X-Investigation-Attempt: new" \
  -H "Idempotency-Key: pf-live-investigate-case-b-v2" \
  "http://127.0.0.1:8000/api/v1/cases/$CASE/reconciliation/$RUN_ID/investigations"
```

A second request with the same idempotency key returns that attempt and does not send another model request. A request without `X-Investigation-Attempt: new` returns the latest stored row and does not spend. Read attempt 1 by its original id. It stays `completed` with the credit recommendation that did not open the source lines.

Expected, in addition to the identity, review, and payment checks from test B:

- `attempt` is greater than the failed row's attempt.
- `evidence_validated` is true. HTTP 201 is not that check.
- The trace includes `get_reconciliation_findings`, `get_purchase_order`, `get_delivery_notes`, `get_invoices`, and `search_procurement_policy`. The order is the model's choice.
- Retrieved labels include a purchase-order line, a delivery-note line, and an invoice line for `CEM-II-25`, not only the matcher finding's document numbers.
- `POL-QTY-001` is cited and appears in the policy tool event.
- Quantities, if stated, agree with the matcher: ordered 100, delivered 80, invoiced 100, gap 20.
- The recommendation does not say the remaining 20 units will never be delivered. A credit is conditional on the supplier confirming that the balance will not arrive. Supplier clarification is appropriate when that is not established.
- The record separates observed facts, possible explanations, missing evidence, and next actions.
- `review_required` is true and `payment_authority` is false.
- Token counts and `estimated_cost_usd` are present. The USD figure is an estimate.

Pass: `score_live_quantity_investigation` has no failing dimension.

Fail: the new row overwrites the first investigation, `evidence_validated` is false, a source line is missing, the credit treats the balance as cancelled, or a citation was not retrieved.

The stored result of this test is the failed report [experiments/PF-LIVE-INVESTIGATE-CASE-B-V2.txt](experiments/PF-LIVE-INVESTIGATE-CASE-B-V2.txt). Do not delete that investigation. A second request with the same idempotency key returns it and does not start another model run. Live mode is off. That report is a historical record. A later code change separates a schema mismatch from the evidence gate and stores field-level validation diagnostics. It does not replace this result.

## D. PF-LIVE-INVESTIGATE-CASE-B-V3

This was one new live attempt on the same seeded reconciliation run. It did not replace attempt 1 or attempt 2. The idempotency key was `pf-live-investigate-case-b-v3`. A later request with that same key returns the stored row and does not send another model request.

The stored result is the failed report [experiments/PF-LIVE-INVESTIGATE-CASE-B-V3.txt](experiments/PF-LIVE-INVESTIGATE-CASE-B-V3.txt). Do not delete that investigation. The model opened the purchase-order, delivery-note, and invoice lines, the evidence gate rejected the credit, and a later policy search retrieved `POL-QTY-001`. The next model request timed out inside the 15-second wall clock before a corrected outcome was stored. `evidence_validated` is false. That report is a historical record. The authorized V4 run is recorded below.

## E. PF-LIVE-INVESTIGATE-CASE-B-V4

This was one new live attempt on the same seeded reconciliation run. It did not replace attempts 1, 2, or 3. The idempotency key was `pf-live-investigate-case-b-v4`. A later request with that same key returns the stored row and does not send another model request.

The stored result is the passing report [experiments/PF-LIVE-INVESTIGATE-CASE-B-V4.txt](experiments/PF-LIVE-INVESTIGATE-CASE-B-V4.txt). Do not delete that investigation. The evidence gate rejected the first credit because the purchase-order, delivery-note, and invoice lines had not been opened. The model then opened those lines and recorded a conditional quantity credit. `evidence_validated` is true, `review_required` is true, and `payment_authority` is false. `score_live_quantity_investigation` has no failing dimension. Live mode is off. Do not start a V5 investigation automatically.

A later mock attempt on the same reconciliation uses idempotency key `pf-mock-investigate-case-b-current`. It is stored beside V4. It did not call a model, and it did not change this report or the V4 row.

## Later: PF-LIVE-E2E-CASE-B

Run this only after A and B, on a database that does not already contain the synthetic seed. Do not point this run at the seeded `CASE-B-QUANTITY` rows.

1. Create an empty local database, migrate it with `uv run alembic upgrade head`, and point only this API process at it. Leave the existing `procureflow` database untouched.
2. Enable both live flags and upload, in order, `goods_received-dn-b-100.pdf`, `works_order-po-b-100.pdf`, and `tax_invoice-inv-b-100.pdf`.
3. Score each extraction with the catalog before accepting it. A failed or incomplete extraction is not accepted.
4. Accept the three documents. The case must be `origin=upload` and `synthetic=false`.
5. Read the reconciliation. The expected matcher result is `EXCEPTION`, with a quantity gap of `20` for `CEM-II-25`. The model does not calculate that gap.
6. Start one investigation on that upload case. Apply the same pass rules as test B.
7. Write three live reports: one per document and one for the investigation. Do not mix them with `uv run python -m app.documents`, which scores only the mock extractor.

If this is attempted against a database that already has the seed, acceptance of `PO-B-100` returns 409. That preserves the seed. It is not the end-to-end result. Stop and use the empty database.

## Report

Use one report per live run. Do not put a mock result in this format. `uv run python -m app.documents` remains the mock extraction score and says it is not a language-model measurement.

```text
Live LLM experiment report.
This is not a mock-test result.
Estimated USD is an application price-table safeguard, not a provider invoice and not a guaranteed billing cap.
Test identifier:
Model and configuration:
Input document or case:
Expected result:
Actual result:
Schema validation:
Retrieved evidence:
Agent tools invoked:
Tokens consumed:
Estimated USD cost:
Primary evidence completeness:
Tool selection relevance:
Citation correctness:
Factual correctness:
Recommendation appropriateness:
Explicit uncertainty:
Execution cost:
Completion status:
Duration:
Errors:
Overall evaluation:
```

`Schema validation` records whether the provider output matched the extraction schema or `record_investigation_outcome` and then passed the server-side evidence check. `Retrieved evidence` lists labels and policy section codes copied from tool results. `Agent tools invoked` lists the tool names in order, including the workflow's first findings load. `Estimated USD cost` is the application's price-table figure for the recorded token counts. The following lines are the live score, each `pass` or `fail` with a short reason: primary line evidence, whether the selected tools were relevant, citation correctness, factual agreement with the matcher, whether the recommendation stays conditional, explicit uncertainty, whether cost was recorded, and whether the attempt is evidence-validated rather than merely stored. `Duration` is the wall-clock time of the HTTP request. `Overall evaluation` is `pass`, `fail`, or `not run`.

A mock investigation or mock extraction is reported by the existing screens and by the mock evaluation command. It is not entered in this report.
