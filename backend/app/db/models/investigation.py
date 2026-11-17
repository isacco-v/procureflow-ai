"""Investigation runs, audit events, and the policy corpus."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.procurement import utcnow
from app.domain.investigation import InvestigationStatus, ReasoningKind, RecommendedAction

_MONEY = Numeric(12, 6)


def _status_check() -> CheckConstraint:
    allowed = ", ".join(f"'{status.value}'" for status in InvestigationStatus)
    return CheckConstraint(f"status IN ({allowed})", name="ck_investigations_status")


def _action_check() -> CheckConstraint:
    allowed = ", ".join(f"'{action.value}'" for action in RecommendedAction)
    return CheckConstraint(
        f"recommended_action IS NULL OR recommended_action IN ({allowed})",
        name="ck_investigations_action",
    )


def _reasoning_check() -> CheckConstraint:
    allowed = ", ".join(f"'{kind.value}'" for kind in ReasoningKind)
    return CheckConstraint(
        f"reasoning_kind IN ({allowed})",
        name="ck_investigations_reasoning_kind",
    )


class PolicyDocument(Base):
    __tablename__ = "policy_documents"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    synthetic: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    sections: Mapped[list[PolicySection]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class PolicySection(Base):
    __tablename__ = "policy_sections"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    heading: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', heading || ' ' || body)",
            persisted=True,
        ),
        nullable=False,
    )

    document: Mapped[PolicyDocument] = relationship(back_populates="sections")

    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_policy_sections_document_ordinal"),
        CheckConstraint("ordinal > 0", name="ck_policy_sections_ordinal"),
        Index("ix_policy_sections_document_id", "document_id"),
        Index("ix_policy_sections_search_vector", "search_vector", postgresql_using="gin"),
    )


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    reconciliation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    evidence_validated: Mapped[bool | None] = mapped_column(nullable=True)
    ai_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    recommended_action: Mapped[str | None] = mapped_column(String(64))
    review_required: Mapped[bool] = mapped_column(nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    structured_findings: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    unresolved_issues: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    observed_facts: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    possible_explanations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    missing_evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    next_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(nullable=False)
    output_tokens: Mapped[int] = mapped_column(nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    iteration_count: Mapped[int] = mapped_column(nullable=False)
    tool_call_count: Mapped[int] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    events: Mapped[list[InvestigationEvent]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="InvestigationEvent.ordinal",
    )
    evidence: Mapped[list[InvestigationEvidence]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="InvestigationEvidence.ordinal",
    )
    citations: Mapped[list[InvestigationCitation]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="InvestigationCitation.ordinal",
    )

    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id",
            "ai_mode",
            "attempt",
            name="uq_investigations_run_mode_attempt",
        ),
        UniqueConstraint(
            "reconciliation_run_id",
            "ai_mode",
            "idempotency_key",
            name="uq_investigations_run_mode_idempotency",
        ),
        _status_check(),
        _action_check(),
        _reasoning_check(),
        CheckConstraint("ai_mode IN ('mock', 'openai')", name="ck_investigations_ai_mode"),
        CheckConstraint("input_tokens >= 0", name="ck_investigations_input_tokens"),
        CheckConstraint("output_tokens >= 0", name="ck_investigations_output_tokens"),
        CheckConstraint("estimated_cost_usd >= 0", name="ck_investigations_estimated_cost"),
        CheckConstraint("attempt >= 1", name="ck_investigations_attempt"),
        CheckConstraint("iteration_count >= 0", name="ck_investigations_iteration_count"),
        CheckConstraint("tool_call_count >= 0", name="ck_investigations_tool_call_count"),
        CheckConstraint("review_required", name="ck_investigations_review_required"),
        Index("ix_investigations_case_id", "case_id"),
    )


class InvestigationEvent(Base):
    __tablename__ = "investigation_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    investigation: Mapped[Investigation] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "ordinal",
            name="uq_investigation_events_investigation_ordinal",
        ),
        CheckConstraint("ordinal > 0", name="ck_investigation_events_ordinal"),
        Index("ix_investigation_events_investigation_id", "investigation_id"),
    )


class InvestigationEvidence(Base):
    __tablename__ = "investigation_evidence"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[UUID | None] = mapped_column(Uuid)
    label: Mapped[str] = mapped_column(String(200), nullable=False)

    investigation: Mapped[Investigation] = relationship(back_populates="evidence")

    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "ordinal",
            name="uq_investigation_evidence_investigation_ordinal",
        ),
        CheckConstraint("ordinal > 0", name="ck_investigation_evidence_ordinal"),
        Index("ix_investigation_evidence_investigation_id", "investigation_id"),
    )


class InvestigationCitation(Base):
    __tablename__ = "investigation_citations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_section_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_sections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)
    policy_code: Mapped[str] = mapped_column(String(64), nullable=False)
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    heading: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)

    investigation: Mapped[Investigation] = relationship(back_populates="citations")
    policy_section: Mapped[PolicySection] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "ordinal",
            name="uq_investigation_citations_investigation_ordinal",
        ),
        CheckConstraint("ordinal > 0", name="ck_investigation_citations_ordinal"),
        Index("ix_investigation_citations_investigation_id", "investigation_id"),
        Index("ix_investigation_citations_policy_section_id", "policy_section_id"),
    )
