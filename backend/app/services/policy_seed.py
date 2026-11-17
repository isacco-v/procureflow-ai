"""Insert the synthetic policy corpus without changing rows that already exist."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PolicyDocument, PolicySection
from app.domain.policies import POLICY_CORPUS
from app.services.identifiers import synthetic_id


def ensure_policy_corpus(session: Session) -> int:
    """Add missing policy documents. Existing codes are left unchanged."""

    created = 0
    for ordinal, fixture in enumerate(POLICY_CORPUS, start=1):
        found = session.scalar(select(PolicyDocument.id).where(PolicyDocument.code == fixture.code))
        if found is not None:
            continue
        document = PolicyDocument(
            id=synthetic_id(f"policy:{fixture.code}"),
            code=fixture.code,
            title=fixture.title,
            version=fixture.version,
            effective_on=fixture.effective_on,
            summary=fixture.heading,
            synthetic=True,
        )
        session.add(document)
        session.add(
            PolicySection(
                id=synthetic_id(f"policy-section:{fixture.code}"),
                document_id=document.id,
                code=fixture.code,
                ordinal=ordinal,
                heading=fixture.heading,
                body=fixture.body,
            )
        )
        created += 1
    session.flush()
    return created
