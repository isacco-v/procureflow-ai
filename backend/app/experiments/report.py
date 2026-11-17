"""Text form for one live experiment. Mock results are refused."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiveExperimentReport:
    test_id: str
    model: str
    configuration: str
    case_input: str
    expected: str
    actual: str
    schema_validation: str
    evidence: str
    tools: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: str
    duration_seconds: str
    errors: str
    evaluation: str
    execution: str = "live_llm"
    primary_evidence: str = "not scored"
    tool_relevance: str = "not scored"
    citation_correctness: str = "not scored"
    factual_correctness: str = "not scored"
    recommendation_appropriateness: str = "not scored"
    explicit_uncertainty: str = "not scored"
    execution_cost: str = "not scored"
    completion_status: str = "not scored"


def render_live_report(report: LiveExperimentReport) -> str:
    """Render one live result. A mock execution cannot use this format."""

    if report.execution != "live_llm":
        raise ValueError("Live reports cannot record a mock result.")
    lines = [
        "Live LLM experiment report.",
        "This is not a mock-test result.",
        "Estimated USD is an application price-table safeguard, not a provider "
        "invoice and not a guaranteed billing cap.",
        f"Test identifier: {report.test_id}",
        f"Model and configuration: {report.model}; {report.configuration}",
        f"Input document or case: {report.case_input}",
        f"Expected result: {report.expected}",
        f"Actual result: {report.actual}",
        f"Schema validation: {report.schema_validation}",
        f"Retrieved evidence: {report.evidence}",
        f"Agent tools invoked: {report.tools}",
        f"Tokens consumed: input {report.input_tokens}, output {report.output_tokens}",
        f"Estimated USD cost: {report.estimated_cost_usd}",
        f"Primary evidence completeness: {report.primary_evidence}",
        f"Tool selection relevance: {report.tool_relevance}",
        f"Citation correctness: {report.citation_correctness}",
        f"Factual correctness: {report.factual_correctness}",
        f"Recommendation appropriateness: {report.recommendation_appropriateness}",
        f"Explicit uncertainty: {report.explicit_uncertainty}",
        f"Execution cost: {report.execution_cost}",
        f"Completion status: {report.completion_status}",
        f"Duration: {report.duration_seconds}",
        f"Errors: {report.errors}",
        f"Overall evaluation: {report.evaluation}",
    ]
    return "\n".join(lines) + "\n"
