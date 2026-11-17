"""HTTP contracts for an investigation and its audit events."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.decimals import ApiDecimal
from app.domain.investigation import InvestigationStatus, ReasoningKind, RecommendedAction


class InvestigationFindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    summary: str
    evidence_labels: list[str]


class InvestigationCitationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_code: str
    section_code: str
    version: str
    heading: str
    excerpt: str
    content_trust: Literal["untrusted"] = "untrusted"


class InvestigationEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    record_type: str
    record_id: UUID | None
    label: str


class InvestigationEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinal: int
    event_type: str
    tool_name: str | None
    summary: str
    payload: dict[str, Any]
    created_at: datetime


class InvestigationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    case_id: UUID
    reconciliation_run_id: UUID
    status: InvestigationStatus
    ai_mode: Literal["mock", "openai"]
    provider: str
    model_name: str
    reasoning_kind: ReasoningKind
    mock_execution: bool
    recommended_action: RecommendedAction | None
    review_required: Literal[True]
    payment_authority: Literal[False] = False
    summary: str | None
    findings: list[InvestigationFindingResponse]
    unresolved_issues: list[str]
    citations: list[InvestigationCitationResponse]
    evidence: list[InvestigationEvidenceResponse]
    events: list[InvestigationEventResponse]
    error_code: str | None
    error_detail: str | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: ApiDecimal
    iteration_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    attempt: int = Field(ge=1)
    evidence_validated: bool
    observed_facts: list[str]
    possible_explanations: list[str]
    missing_evidence: list[str]
    next_actions: list[str]
    replayed: bool
    started_at: datetime
    finished_at: datetime


class InvestigationEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation_id: UUID
    events: list[InvestigationEventResponse]
