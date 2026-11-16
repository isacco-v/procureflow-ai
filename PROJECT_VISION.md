# ProcureFlow AI — Project Vision

**Status:** target product vision, written 2026-11-16.  
**Repository state:** initial foundation only. This document describes the system we intend to build. It is not a description of behavior that already exists, and it is not evidence of production use, reliability, or measured performance.

ProcureFlow AI is a personal, open-source portfolio project. It is designed to be defended in a senior engineering review: each capability should exist because a procurement team needs it, and each important behavior should be testable.

## Executive summary

ProcureFlow AI is an AI-powered procurement intelligence and reconciliation platform for construction purchasing. Teams upload purchase orders, delivery notes, and supplier invoices. The system extracts structured fields, reconciles the three documents, and investigates exceptions with a bounded agent. A person reviews the evidence before any financial decision.

The engineering point of the project is the split between interpretation and authority:

- Language models interpret messy descriptions, ambiguous references, and policy text.
- Deterministic code decides quantities, money, tolerances, and whether a discrepancy exists.
- A person approves or rejects anything that would affect payment.

A model is never the calculator for quantities, totals, taxes, or financial reconciliation.

## Business problem

Construction procurement is document-heavy. A purchase order records what was bought. Delivery notes record what arrived, often across more than one shipment. The supplier invoice records what the supplier expects to be paid. Before payment, someone must check that these three stories agree.

That check is called three-way matching. It fails in ordinary ways:

- Descriptions differ even when the material is the same. A purchase order may say "Portland Cement CEM II 25kg", a delivery note "Cement bags 25 kg", and an invoice "CEM II/A-LL 25KG".
- Quantities differ because of partial delivery, breakage, or a supplier billing the ordered quantity instead of the delivered quantity.
- Prices, units, taxes, or extra charges do not match the order.
- References are missing, so a person cannot see which documents belong together.
- The same invoice, or the same delivery, is submitted twice.

Doing this by hand is slow and inconsistent. Doing it by sending entire documents to a model and trusting the model's arithmetic is not acceptable: the result is hard to test, hard to audit, and wrong in ways that look fluent.

## Target users

The first user is a construction procurement reviewer: the person who prepares a case for approval and has to explain a discrepancy. They are not assumed to be an accountant or an engineer.

Secondary users, later, are the procurement lead who sets tolerances and policies, and an auditor who needs to see why a case was approved or sent back.

The project does not currently implement accounts, roles, or an approval workflow. Those are part of the target product.

## Product value proposition

The product should reduce the time spent comparing documents without hiding the reasoning. For a clean case, the reviewer sees a deterministic match and the source fields. For a broken case, the reviewer sees the discrepancy, the evidence the agent collected, the policy passages that were actually retrieved, and what is still uncertain.

The value is a reviewable recommendation, not an automatic payment.

## Primary use cases

1. **Open a procurement case** and attach the purchase order, one or more delivery notes, and one or more invoices.
2. **Read a structured extraction** of each document, including missing and contradictory fields, with a pointer back to the source text where the system has one.
3. **Run three-way matching** and see quantity, price, product, reference, duplicate, and total discrepancies as explicit results.
4. **Investigate an exception.** The agent may retrieve the case, the match result, related documents, supplier history, and procurement policy. It returns a structured recommendation and the evidence it used.
5. **Review and record a decision.** The reviewer approves, rejects, or asks for another investigation. The decision is stored as an audit event. The system does not pay the supplier.
6. **Demonstrate the product** with fixed synthetic cases so a reviewer can repeat the same outcome without a paid model call.

## End-to-end user journey

This is the target journey. Synthetic cases and deterministic matching are implemented. Upload, extraction, investigation, and a recorded human decision are not. The overview still reads `GET /health`.

1. The reviewer creates or opens a procurement case and uploads PDFs.
2. The system checks file type, size, and basic integrity, stores metadata, and marks the document as received.
3. An extraction pipeline returns typed fields and evidence references. Missing values stay missing.
4. Normalization maps those fields onto purchase-order, delivery-note, and invoice records. Ambiguous product matches are flagged, not silently accepted.
5. The matching engine compares the records and writes discrepancies.
6. If discrepancies exist, an investigation agent gathers evidence and writes a recommendation. If the evidence is weak, the recommendation says so and asks for a person.
7. The reviewer inspects documents, extracted fields, match results, agent findings, and policy citations, then records a decision.
8. A future integration may send that decision to an external procurement system. The demonstration uses a simulated integration.

## Main functional capabilities

| Capability | Why it exists | Status |
| --- | --- | --- |
| Case and document intake | Reviewers work by case, not by loose files | Partial: synthetic cases and source-document rows. Upload is not implemented |
| Typed extraction with evidence | Reviewers must see what was read and what was not | Planned |
| Normalization | Documents do not share a layout or a vocabulary | Planned |
| Deterministic three-way match | Financial differences must be reproducible | Implemented for stored lines |
| Exception investigation | Some differences need context a rule cannot see | Planned |
| Policy retrieval with citations | A recommendation should point at the rule it used | Planned |
| Human review and audit | Payment-related decisions need a person and a trace | Planned |
| Simulated ERP handoff | Shows the boundary without a live ERP | Planned |
| Health check, configuration, mock model provider | Makes the foundation runnable and safe to demo | Implemented |

## Non-functional requirements

These apply to the target system. Where this repository does not meet them yet, the architecture document says so.

- **Correctness of money and quantity.** Decimal arithmetic, explicit tolerances, and tests that do not involve a model.
- **Traceability.** Document status, match results, tool calls, and review decisions are stored as records a reviewer can open later.
- **Idempotency.** Processing the same document again does not create a second financial result.
- **Bounded model use.** Tool calls, steps, tokens, and estimated cost have limits. Crossing a limit stops the run.
- **Failure behavior.** Tool errors, timeouts, and invalid model output become visible states, not a guessed answer.
- **Security.** Secrets stay in the environment. Uploaded documents are untrusted. The browser never receives a model API key.
- **Operability.** Structured logs, request identifiers, and a health check. Metrics and tracing are planned, not present.
- **Cost.** The default mode performs no paid call. A public demo must not let anonymous traffic spend the model budget.
- **Honesty.** Documentation distinguishes the foundation from the target. No performance number is published without a measurement.

## AI engineering competencies, and why each one is here

Each item below is justified by the procurement workflow. None of them is a reason to add a framework before the corresponding behavior exists.

| Competency | Business reason |
| --- | --- |
| Model calls behind a provider interface | The demo must run with no spend, and a later real provider must be swappable without rewriting the workflow |
| Structured extraction | Reviewers need fields, not a paragraph about the PDF |
| Retrieval over procurement policy | An exception explanation should follow the company's rule, and the rule should be citable |
| Agentic investigation with tools | The relevant evidence depends on the exception. A fixed script cannot know which document or policy to open |
| Deterministic matching beside the model | Quantity and money errors must be the same on every run |
| Evaluation on fixed scenarios | A change to a prompt or a matcher should be checkable against known cases |
| Human approval | The cost of a wrong payment is higher than the cost of a review |
| Usage and cost records | The experimentation budget is small and has to be visible before it is spent |

## Demonstration scenarios

The dataset is synthetic. Five structured scenarios live in `backend/app/domain/scenarios.py` and can be seeded into PostgreSQL. They do not yet have PDF files.

### Scenario A — successful reconciliation

Ordered, delivered, and invoiced quantities and prices agree, including line totals and the grand total.

Expected result: no material discrepancy. No payment is sent automatically; the case is simply clean.

### Scenario B — quantity discrepancy

The purchase order is for 100 units. Delivery notes confirm 80. The invoice charges for 100.

Expected result:

- The matcher reports a deterministic quantity discrepancy.
- An investigation collects the three documents and the match result.
- The recommendation asks for review or clarification.
- Nothing in the system approves payment.

### Scenario C — semantic ambiguity

The same or a possibly same material appears under different descriptions, as in the cement example above.

Expected result:

- The system may propose a candidate match.
- The candidate is not treated as fact.
- Investigation uses the available context.
- If the evidence is not enough, the case is escalated.

Later scenarios, not required for the first vertical slice: duplicate invoices, several deliveries against one order, unit conversion, and a policy exception such as an agreed price variance.

## MVP scope

The minimum product that demonstrates the idea is one vertical slice:

- A procurement case with structured purchase-order, delivery-note, and invoice lines. PDFs can follow once the match contract is tested; the first matcher tests should not need a model.
- A pure matching function with configurable tolerances and Scenarios A and B.
- Persistence for the case, the match, and an audit event.
- A review screen that shows the discrepancy and does not offer a pay action.
- Mock model responses only.

Extraction, retrieval, and the investigation agent are the next slices. They are not required to prove that the matcher is deterministic.

## Planned advanced capabilities

- PDF intake, with a later path for scans and OCR.
- Structured extraction that records page and source text.
- Semantic candidate matching that stays distinct from accepted matches.
- Policy retrieval with PostgreSQL and pgvector, plus lexical lookup for identifiers and amounts.
- A LangGraph investigation with read-only tools, step and cost limits, and human escalation.
- Background processing for long jobs, with explicit job states and retries.
- A simulated outbound integration.
- Deployment of the static frontend and a separately hosted API. Render and Supabase are options to evaluate, not services that have been provisioned.
- GitHub Pages for the static frontend, if the API base URL can be configured at build time without embedding secrets.

## Explicit non-goals

- Autonomous payment, posting to an ERP, or any irreversible financial action.
- Using a model as the source of truth for arithmetic.
- A calibrated probability on every sentence. Uncertainty is recorded when the evidence is missing or conflicting. A model score is not presented as a measured probability.
- Multi-tenant SaaS, billing, or a marketplace of suppliers.
- Microservices, or a second language, without a concrete operational reason.
- A production claim. This is a portfolio project.
- Unlimited public access to a paid model.

## Development roadmap

### 1. Initial foundation — current iteration

Repository layout, API process, configuration, PostgreSQL wiring and a baseline migration, a mock model provider, a minimal admin shell, tests for the health contract, and these documents.

Exit criteria: the API answers `/health` without a database, tests pass without a network call, and `AI_MODE=openai` cannot place a call because no client is installed.

### 2. Functional vertical slice — matcher and cases are in place

Domain model, migrations, deterministic matcher, scenarios A–E as structured fixtures, and a cases screen bound to the API. Still no paid model and no PDF extraction.

Exit criteria met for the matcher: the tests fail if a quantity or price discrepancy is missed or invented, and the same input yields the same report. A person still cannot record an approval. That remains later work.

### 3. Advanced agentic capabilities

Extraction, normalization, retrieval, and a bounded investigation agent. Real model calls stay behind the provider switch and a budget. Scenario C becomes an evaluation case.

Exit criteria: an investigation records the tools it called and the policy passages it used. A budget or tool-limit breach ends the run with an explicit status. The agent has no tool that approves payment.

### 4. Public demonstration and deployment

Synthetic documents, a default mock or replay mode, a hosted API with managed PostgreSQL, and a static frontend. Anonymous users cannot trigger unbounded spend. The experimentation budget for real calls is about $5 and requires an explicit decision before `AI_MODE=openai` is enabled anywhere.

Exit criteria: a stranger can watch Scenarios A–C without a personal API key, and the deployment documentation matches the services that were actually created.

## Success criteria and evaluation goals

These are targets for later iterations. They are not measurements.

- Scenario A produces no material discrepancy on the fixture.
- Scenario B always reports the 20-unit gap and never a payment approval.
- Scenario C either cites evidence for an accepted equivalence or escalates. It does not silently merge the lines.
- Matcher tests run with no model and no network.
- A corrupted or partial extraction produces an explicit validation result rather than a filled-in value.
- Re-processing one document does not duplicate its financial effect.
- An investigation that exceeds its tool or cost limit stops and records the limit.
- The review log can answer who moved a case to its current state, and when.
- A public deployment's default configuration performs zero paid model calls.

## Known risks and limitations

- **Semantic overconfidence.** Similar descriptions are not proof of the same product. The design treats semantic matches as candidates. The risk remains if a later change promotes them automatically.
- **Extraction error.** A wrong quantity in the structured record becomes a wrong match. Evidence references and human review are the mitigation, not a higher model temperature.
- **Policy retrieval error.** A retrieved chunk can be irrelevant or contradicted by another chunk. The agent must be able to return uncertainty.
- **Prompt injection.** Document text is untrusted and may contain instructions. Tools must validate arguments and must not follow instructions found in a PDF.
- **Cost.** A public endpoint in live mode would spend money. The default is mock, and live mode is not implemented.
- **Scope.** A full ERP integration, OCR for arbitrary scans, and multi-company permissions are easy to overbuild. They stay planned until the match and review loop works.
- **Portfolio context.** There are no production users and no incident history. Operational claims have to wait for evidence.

## How to read this document later

When a feature is implemented, update the status column and the roadmap exit criteria with what the tests actually cover. Do not mark a capability implemented because a placeholder screen or an unused interface exists.
