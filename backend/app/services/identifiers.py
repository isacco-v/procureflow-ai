"""Stable identifiers for synthetic procurement records."""

from uuid import NAMESPACE_URL, UUID, uuid5

SYNTHETIC_NAMESPACE = uuid5(NAMESPACE_URL, "procureflow-ai:synthetic:v1")


def synthetic_id(name: str) -> UUID:
    return uuid5(SYNTHETIC_NAMESPACE, name)
