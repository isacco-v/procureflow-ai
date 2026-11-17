"""Check a recommendation against the evidence that tools actually returned."""

import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.domain.investigation import RecommendationDraft

_FORBIDDEN_SUMMARY = re.compile(
    r"invoice is approved|approved for payment|payment (?:has been|is) initiated",
    re.IGNORECASE,
)


class ValidationRejection(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def hydrate_recommendation(
    draft: RecommendationDraft | dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        parsed = (
            draft
            if isinstance(draft, RecommendationDraft)
            else RecommendationDraft.model_validate(draft)
        )
    except ValidationError as exc:
        raise ValidationRejection("The recommendation did not match the schema.") from exc

    if _FORBIDDEN_SUMMARY.search(parsed.summary):
        raise ValidationRejection("The recommendation claimed a financial approval.")

    sections = _sections(tool_results)
    labels = _labels(tool_results)
    citations = []
    for code in parsed.citation_section_codes:
        section = sections.get(code)
        if section is None:
            raise ValidationRejection(f"Citation {code} was not retrieved.")
        try:
            section_id = UUID(str(section["section_id"]))
        except (ValueError, KeyError) as exc:
            raise ValidationRejection("A retrieved policy section had no id.") from exc
        citations.append(
            {
                "policy_section_id": str(section_id),
                "policy_code": str(section.get("document_code") or code),
                "section_code": code,
                "version": str(section.get("version") or ""),
                "heading": str(section.get("heading") or ""),
                "excerpt": str(section.get("excerpt") or ""),
            }
        )

    for label in parsed.evidence_labels:
        if label not in labels:
            raise ValidationRejection(f"Evidence label {label} was not retrieved.")
    findings = []
    for finding in parsed.finding_summaries:
        for label in finding.evidence_labels:
            if label not in labels:
                raise ValidationRejection(f"Evidence label {label} was not retrieved.")
        findings.append(
            {
                "code": finding.code,
                "summary": finding.summary,
                "evidence_labels": list(finding.evidence_labels),
            }
        )

    return {
        "action": parsed.action.value,
        "summary": parsed.summary,
        "review_required": True,
        "findings": findings,
        "citations": citations,
        "unresolved": list(parsed.unresolved),
        "observed_facts": list(parsed.observed_facts),
        "possible_explanations": list(parsed.possible_explanations),
        "missing_evidence": list(parsed.missing_evidence),
        "next_actions": list(parsed.next_actions),
    }


def _sections(tool_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for result in tool_results:
        if result.get("tool_name") != "search_procurement_policy" or not result.get("ok"):
            continue
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        raw = data.get("sections")
        if not isinstance(raw, list):
            continue
        for section in raw:
            if isinstance(section, dict) and isinstance(section.get("section_code"), str):
                found.setdefault(section["section_code"], section)
    return found


def _labels(tool_results: list[dict[str, Any]]) -> set[str]:
    labels: set[str] = set()
    for result in tool_results:
        if not result.get("ok"):
            continue
        raw = result.get("evidence_labels")
        if isinstance(raw, list):
            labels.update(label for label in raw if isinstance(label, str))
    return labels
