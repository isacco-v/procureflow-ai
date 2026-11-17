"""Preparation for a controlled live experiment.

Running this module reads the synthetic catalog and prints the procedure.
It does not construct an OpenAI client and it does not send a request.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.documents.synthetic import PDF_DIR, load_catalog

_CASE_B_FILES = (
    "works_order-po-b-100.pdf",
    "goods_received-dn-b-100.pdf",
    "tax_invoice-inv-b-100.pdf",
)

FUTURE_COMMANDS = """
Do not run the live commands until a person has authorized the spend.
This preparation does not set those variables and does not call OpenAI.

Application budgets are estimated safeguards, not guaranteed provider billing caps.
Extraction default: 0.05 USD. Investigation default: 0.10 USD. Model: gpt-5.4-mini.
A response can cost more than the reservation. There is no automatic paid retry.

1. Stay on the default until the gates below are set in the server environment
   and the API process is restarted. Do not put the key in frontend/.env or in git.

   AI_MODE=openai
   OPENAI_MODEL=gpt-5.4-mini
   OPENAI_API_KEY=<server-side key>
   DOCUMENT_EXTRACTOR=openai
   EXTRACTION_LIVE_ENABLED=true
   INVESTIGATION_LIVE_ENABLED=false

2. Confirm the isolation migration is applied, without resetting data:

   cd backend
   uv run alembic upgrade head

3. Extraction, one synthetic purchase order, one request. From backend/:

   curl -sS -D - -o /tmp/procureflow-po-b.json \\
     -F "file=@app/documents/fixtures/pdfs/works_order-po-b-100.pdf;type=application/pdf" \\
     http://127.0.0.1:8000/api/v1/documents

   Fill one live report from that JSON. Do not accept the document into a
   seeded case. A repeat upload of the same bytes returns the stored live row
   and does not send another request.

4. Investigation, seeded CASE-B-QUANTITY. Set INVESTIGATION_LIVE_ENABLED=true
   and restart. Leave the extraction flag false unless a new extraction is intended.

   curl -sS -X POST http://127.0.0.1:8000/api/v1/dev/seed
   CASE=$(curl -sS http://127.0.0.1:8000/api/v1/cases | python -c \\
     "import json,sys; rows=json.load(sys.stdin)['cases']; \\
      print(next(row['id'] for row in rows if row['reference']=='CASE-B-QUANTITY'))")
   RUN=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/cases/$CASE/reconciliation)
   RUN_ID=$(printf '%s' "$RUN" | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
   curl -sS -D - -X POST \\
     http://127.0.0.1:8000/api/v1/cases/$CASE/reconciliation/$RUN_ID/investigations

   A stored mock investigation on that run is left in place. The live row is separate.

5. PF-LIVE-INVESTIGATE-CASE-B-V2 is a separate attempt. The procedure is in
   docs/LIVE_EXPERIMENT.md. Do not run it from this command. A plain POST
   returns the stored investigation and does not start another paid run.

6. Afterward set both live flags back to false and restart. Do not deploy the
   process while either flag is true.
""".strip()


@dataclass(frozen=True, slots=True)
class ExperimentProcedure:
    extraction_test_id: str
    investigation_test_id: str
    end_to_end_test_id: str
    investigation_retest_id: str
    model: str
    extraction_budget_usd: str
    investigation_budget_usd: str
    purchase_order_file: str
    commands: str


def build_procedure() -> ExperimentProcedure:
    return ExperimentProcedure(
        extraction_test_id="PF-LIVE-EXTRACT-PO-B",
        investigation_test_id="PF-LIVE-INVESTIGATE-CASE-B",
        end_to_end_test_id="PF-LIVE-E2E-CASE-B",
        investigation_retest_id="PF-LIVE-INVESTIGATE-CASE-B-V2",
        model="gpt-5.4-mini",
        extraction_budget_usd="0.05",
        investigation_budget_usd="0.10",
        purchase_order_file="works_order-po-b-100.pdf",
        commands=FUTURE_COMMANDS,
    )


def verify_case_b_fixtures() -> list[str]:
    """Check the three CASE-B PDFs against the catalog. No model call."""

    catalog = load_catalog()
    documents = catalog.get("documents")
    if not isinstance(documents, list):
        return ["Ground truth documents must be a list."]
    remaining = set(_CASE_B_FILES)
    problems: list[str] = []
    for entry in documents:
        if not isinstance(entry, dict):
            problems.append("Ground truth document must be an object.")
            continue
        file_name = entry.get("file_name")
        if file_name not in remaining:
            continue
        remaining.remove(file_name)
        if entry.get("scenario_reference") != "CASE-B-QUANTITY":
            problems.append(f"{file_name} is not a CASE-B-QUANTITY catalog row.")
        digest = entry.get("content_sha256")
        payload = (PDF_DIR / str(file_name)).read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != digest:
            problems.append(f"Fixture hash does not match the catalog for {file_name}.")
    problems.extend(f"Missing catalog entry for {name}." for name in sorted(remaining))
    return problems


def render_procedure(procedure: ExperimentProcedure, problems: list[str]) -> str:
    lines = [
        "ProcureFlow live experiment preparation.",
        "No OpenAI request is sent by this command.",
        f"Extraction test: {procedure.extraction_test_id}",
        f"Investigation test: {procedure.investigation_test_id}",
        f"Later end-to-end test: {procedure.end_to_end_test_id}",
        f"Separate investigation retest: {procedure.investigation_retest_id}",
        f"Model: {procedure.model}",
        f"Extraction budget safeguard USD: {procedure.extraction_budget_usd}",
        f"Investigation budget safeguard USD: {procedure.investigation_budget_usd}",
        f"Purchase order file: {procedure.purchase_order_file}",
        "Pass, fail, evidence, and report fields are in docs/LIVE_EXPERIMENT.md.",
        "",
        procedure.commands,
        "",
    ]
    if problems:
        lines.append("Fixture check failed:")
        lines.extend(f"- {item}" for item in problems)
    else:
        lines.append("CASE-B fixture hashes match the catalog.")
    return "\n".join(lines) + "\n"
