# Interview demonstration

This is the script for a senior engineering review of ProcureFlow AI. Two results are easy to confuse. Keep them apart.

| What you are showing | What it is |
| --- | --- |
| Seeded `CASE-B-QUANTITY` in the UI | Stored lines, deterministic reconciliation, mock investigation |
| `uv run python -m app.demo` | The same business case, starting from the three PDF files, on database `procureflow_demo` |
| `docs/experiments/PF-LIVE-INVESTIGATE-CASE-B-V4.txt` | One historical live model run, already finished |

`AI_MODE=mock` is the default. The demonstration does not call OpenAI. Do not start a V5 investigation. Do not deploy the application. Do not accept `PO-B-100` into the seeded database: that request returns 409 and leaves the seed in place.

Before the conversation, start PostgreSQL, apply migrations, seed the cases, and start the API and the frontend as the README describes. Confirm `GET http://127.0.0.1:8000/health` reports `ai_mode` `mock`. Run `uv run python -m app.demo` once so you know the upload path passes. You do not need the demo database on screen for the three-minute walkthrough.

## Three-minute walkthrough

Stay on the seeded database.

1. **Overview, about 20 seconds.** Open the application. The health card reads status `ok` and AI mode `mock`. Say that the page is a liveness check, that the browser has no model key, and that a recorded live run exists in the experiment report and is not executing now.

2. **Find the case, about 20 seconds.** Open Procurement cases. The rows are ordered by reference. `CASE-B-QUANTITY` is titled "Quantity discrepancy". The summary under it says 100 bags were ordered, 80 were recorded as delivered, and 100 were invoiced. Open it. The badge says synthetic seed.

3. **Show the documents, about 30 seconds.** The purchase order `PO-B-100` has 100 BAG of `CEM-II-25` at 4.50 EUR. Delivery note `DN-B-100` has 80 BAG. Invoice `INV-B-100` has 100 BAG at the same unit price. Say that these are stored lines. The matcher will not infer that two descriptions are the same product. Lines match on the product code.

4. **Reconcile, about 40 seconds.** Choose Run reconciliation. If the run already exists, the screen says the existing run was returned unchanged. Status is Exception. Two findings matter: "Ordered, not delivered" and "Invoiced without delivery". Each states a quantity gap of 20 BAG for `CEM-II-25`. Say that this number is Decimal arithmetic in Python. The model is not asked to subtract 80 from 100.

5. **Investigate, about 50 seconds.** Read the latest stored mock result. Do not choose Start another attempt. The banner says mock investigation and that opening it did not call a language model. The badges say completed, attempt 2, evidence validated, and human review required. The recommendation is "Request supplier clarification". It states ordered 100, delivered 80, invoiced 100, difference 20, and cites `POL-QTY-001` together with the other sections the policy tool returned. The evidence list names the purchase-order line, the delivery-note line, and the invoice line for `CEM-II-25`. The tool timeline shows those three document reads and the policy search. Token counts and estimated cost are zero. Payment authority is false, and the summary says no invoice was approved and no payment was initiated. An older mock row, `fca702e0-3e92-490e-a377-df2ee1e95eac`, still recommends a quantity credit and has no stored evidence flag. The page does not show that row. Starting another attempt would add a third mock. Leave both rows in place.

6. **Name the historical run, about 20 seconds.** Say that a separate live attempt, V4, was recorded against this same seeded reconciliation. The evidence gate rejected the first credit because the source lines had not been opened. The model then retrieved them, and the second credit was stored. The report has the token counts and the 0.016704 USD estimate. The screen in mock mode shows the latest mock row, not that live row. Offer to open the report if they want the trace.

If they ask to upload the three PDFs on this database, upload is allowed and the mock extractor will read the page text. Acceptance of those document numbers is refused. Say that aloud, then use the isolated command if they want the accept step.

## Five-minute technical explanation

Use this after the walkthrough, or instead of repeating the clicks.

ProcureFlow is a modular monolith. The reviewer works in the React shell. The shell calls a versioned JSON API. One FastAPI process owns validation, the match, the investigation, and the database transaction. A worker does not exist. The investigation finishes inside the request because the default decision step is local and every tool is a database read.

The domain split is the point of the design. Document text is untrusted data. The mock extractor turns the synthetic page labels into typed fields, and a person accepts them before they become a purchase order, a delivery note, or an invoice. The matcher is a pure function: normalized decimals in, a report out. It aligns lines only when they share a product code. Similar descriptions become `UNCERTAIN_PRODUCT_MAPPING`, not a silent merge. Quantity gaps use an absolute tolerance that defaults to zero, so 100 and 80 are a discrepancy of 20. Different units are not converted. Different currencies are not given an exchange rate.

The investigation is the agentic part. LangGraph holds the loop. The decision interface chooses a tool or a structured outcome. Ordinary code executes the tool, checks the budget, and validates the output. The six tools are read-only and bound to the case. A request for another case returns `case_access_denied` and does not read it.

Evidence sufficiency is a second validator, after the schema. The first live quantity credit can be well formed and still be premature. V4 is that case. The outcome matched the schema and asked for a credit, but the purchase-order, delivery-note, and invoice lines had not been retrieved. The gate rejected it, listed the three gaps, and returned control to the decision step. The model chose the three document tools. The next credit cited `POL-QTY-001` and carried `future_delivery` / `unconfirmed`, so the remaining 20 BAG were not treated as cancelled. `evidence_validated` is true only for that accepted outcome. Attempts 1, 2, and 3 stay stored as failures: missing lines, a schema stop, and a timeout.

The mock test double is not a replay of V4. The latest seeded mock, `c9de896a-569f-42e2-9c2a-199ebced4684`, recommends `request_supplier_clarification`, retrieves the three source lines, cites `POL-QTY-001`, and records zero tokens with the evidence flag set. The older mock row, `fca702e0-3e92-490e-a377-df2ee1e95eac`, remains stored. It recommends `request_quantity_credit` and has no stored evidence flag. It was not rewritten. The live model recommended `request_quantity_credit` once the lines were open, and that V4 attempt is evidence-validated. Mock mode shows the latest mock row, not V4. All of these results require a person and refuse payment. The product is allowed to show that the current script and the recorded model do not choose the same action.

Cost control is three gates plus an estimate. A live client is constructed only when the mode, the specific live flag, and a server key are all set. The HTTP body cannot set them. Before a live request the adapter reserves an estimated cost. The default investigation ceiling is 0.10 USD and the extraction ceiling is 0.05 USD. Those are application estimates, not a provider billing cap. The client uses `max_retries=0`. The recorded V4 estimate was 0.016704 USD for 14,022 input tokens and 1,375 output tokens across four requests.

## Architectural trade-offs

| Choice | What it buys | What it leaves out |
| --- | --- | --- |
| Modular monolith | One transaction around a case, a match, and an investigation | Independent scaling. There is no measurement that asks for a split |
| Pure matcher beside the agent | The 20 BAG gap is the same on every run, with no model in the test | The matcher cannot decide that two descriptions are the same product |
| LangGraph only for investigation | The branchy part is which tool to call next | A second framework. The default selector is still a test double |
| Lexical policy search in PostgreSQL | Citations sit next to the case, with no embedding service | Semantic retrieval. A shared word can retrieve a section the result does not cite |
| Mock as the default, live behind three gates | The repository clones and demos at no cost | A public live demo. That would need authentication, a rate limit, and a budget |
| shadcn-admin shell | An accessible layout without building one | A fork of the template. Sample product pages were removed |

## Decisions worth discussing

- **Authority stays in Python.** Extraction and investigation may propose structure and an explanation. They do not calculate the reconciliation. The tests for the five scenarios do not call a model.

- **Acceptance is explicit.** Parsing and extraction do not write a financial record. `POST /api/v1/documents/{id}/accept` does. A duplicate supplier document number does not overwrite the seed. That is why the PDF walkthrough needs `procureflow_demo`.

- **Schema failure and evidence failure are different stops.** A payload that does not match the outcome schema is `invalid_output`. A schema-valid credit that lacks the source lines is `evidence_rejected`, and the same decision interface may continue. V2 stopped before the gate because the provider output did not match the schema. V4 reached the gate, was rejected, retrieved the lines, and completed.

- **A credit has a structured precondition.** `future_delivery` / `unconfirmed` is the only published way to say the balance may still arrive. The gate does not scan the summary for that idea. The published schema has no status that treats the balance as cancelled.

- **Attempts are immutable.** A mock row and several live rows can belong to one reconciliation. A new live attempt does not replace the failed ones. `GET` the investigation for the process AI mode returns only that mode's latest row. That is why mock mode does not display V4.

- **The tools cannot spend money.** The model, live or mock, cannot approve, pay, or change a reconciliation. `review_required` is always true. `payment_authority` is always false.

## What was implemented and measured

Implemented and used by the demo:

- PDF intake, PyMuPDF text extraction, and the mock extractor on the synthetic layouts.
- Explicit acceptance into an `origin=upload` case, without overwriting a seeded document number.
- Deterministic three-way matching for stored lines, including the 20 BAG quantity gap.
- A LangGraph investigation with read-only tools, lexical citations, budgets, and the evidence gate.
- A scripted decision step that is the default and costs nothing.
- An OpenAI Responses adapter that is implemented and left disabled.

Measured live, once each, and then left as files:

- Extraction `PF-LIVE-EXTRACT-PO-B`.
- Investigation attempts V1, V2, and V3, which failed and remain stored.
- Investigation V4, which passed `score_live_quantity_investigation`. Model `gpt-5.4-mini`. Input 14,022 tokens, output 1,375 tokens, estimate 0.016704 USD, HTTP 15.249 seconds, four completed responses. The evidence gate rejected the first credit and accepted the second.

Not measured:

- A live model score for the mock extractor. `uv run python -m app.documents.evaluate` says it is not a language-model measurement.
- The live end-to-end path on an empty database.
- OCR, semantic retrieval, a recorded human approval, and any production workload.

## Known limitations and later work

- A person cannot yet record approve, reject, or reinvestigate as an audit decision. The investigation can only hand the case back for review.
- Image-only PDFs are stored as needing review. OCR and vision are not implemented, and the API says so.
- Policy retrieval is lexical. `SemanticPolicyRetriever` raises `NotImplementedError`. The pgvector extension is not created.
- The matcher does not compare tax, stated totals, or duplicate invoices. It does not propose that two descriptions are the same product.
- Budgets are estimates. A reservation can be lower than the provider invoice. `max_retries=0` stops the application from sending the request again. It does not undo a charge the provider already made.
- There is no authentication and no rate limit. That is acceptable while every paid gate is closed. It is not acceptable on a public host.
- No cloud project has been created. Render, Supabase, and GitHub Pages are options in the architecture document, not services that were provisioned.

## If something looks wrong

| What you see | What it means |
| --- | --- |
| Health AI mode is `openai` | Stop. The demo is not in the default configuration. Do not investigate. |
| Accepting a Scenario B PDF returns 409 | The seeded number is protected. Use `python -m app.demo` for the upload path. |
| An older upload of `works_order-po-b-100.pdf` says "Not extracted" | Mock mode does not display the historical live extraction. The parsed page text is still on the page. The isolated demo stores its own mock extraction. |
| The seeded case shows supplier clarification, evidence validated, and zero dollars | That is the latest mock, `c9de896a-569f-42e2-9c2a-199ebced4684`. The older credit row is still stored and is not the row the page loads. V4's live credit and its token counts are in the experiment file. |
| The seeded case shows a quantity credit and evidence not validated | The page is showing the older mock, `fca702e0-3e92-490e-a377-df2ee1e95eac`, instead of the later attempt. Refresh against the mock API. Do not start another attempt. |
| Run reconciliation says the existing run was returned | The same lines produce the same report. That is the idempotency check, not a failed click. |
