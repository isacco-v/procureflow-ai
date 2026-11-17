"""Lexical retrieval over the procurement policy corpus.

This is PostgreSQL full-text search. It is not semantic retrieval and it does
not use embeddings. ``SemanticPolicyRetriever`` is the extension point for a
later pgvector phase; it is not selected.
"""

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PolicyDocument, PolicySection

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_MAX_LIMIT = 6


@dataclass(frozen=True)
class PolicyHit:
    section_id: UUID
    document_code: str
    section_code: str
    version: str
    heading: str
    excerpt: str
    content_trust: str = "untrusted"

    def as_dict(self) -> dict[str, str]:
        return {
            "section_id": str(self.section_id),
            "document_code": self.document_code,
            "section_code": self.section_code,
            "version": self.version,
            "heading": self.heading,
            "excerpt": self.excerpt,
            "content_trust": self.content_trust,
        }


class PolicyRetriever(Protocol):
    kind: str

    def search(self, session: Session, query: str, *, limit: int) -> list[PolicyHit]: ...


class LexicalPolicyRetriever:
    """Rank policy sections with ``to_tsvector`` / ``ts_rank``.

    Query tokens are OR-ed so a section can match any of the words. That is
    lexical overlap, not a semantic match.
    """

    kind = "lexical"

    def search(self, session: Session, query: str, *, limit: int) -> list[PolicyHit]:
        tokens = [token.lower() for token in _TOKEN.findall(query) if len(token) > 2]
        if not tokens:
            return []
        bounded = min(max(limit, 1), _MAX_LIMIT)
        tsquery = None
        for token in tokens:
            part = func.plainto_tsquery("english", token)
            tsquery = part if tsquery is None else tsquery.op("||")(part)
        rank = func.ts_rank(PolicySection.search_vector, tsquery)
        rows = session.execute(
            select(PolicySection, PolicyDocument, rank)
            .join(PolicyDocument, PolicySection.document_id == PolicyDocument.id)
            .where(PolicySection.search_vector.op("@@")(tsquery))
            .order_by(rank.desc(), PolicySection.code.asc())
            .limit(bounded)
        ).all()
        return [
            PolicyHit(
                section_id=section.id,
                document_code=document.code,
                section_code=section.code,
                version=document.version,
                heading=section.heading,
                excerpt=section.body,
            )
            for section, document, _score in rows
        ]


class SemanticPolicyRetriever:
    """Not implemented. pgvector is not enabled."""

    kind = "semantic"

    def search(self, session: Session, query: str, *, limit: int) -> list[PolicyHit]:
        del session, query, limit
        raise NotImplementedError(
            "Semantic retrieval is not implemented. The pgvector extension is not enabled."
        )


def build_policy_retriever() -> PolicyRetriever:
    return LexicalPolicyRetriever()
