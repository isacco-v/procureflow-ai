"""Decision interface for an investigation.

``decide`` returns a validated action. It does not return hidden reasoning.
``AI_MODE=mock`` selects the deterministic test double. The OpenAI adapter is
constructed only when the live gate is open.
"""

from typing import Protocol

from app.ai.gating import live_investigation_allowed
from app.ai.investigation_mock import MockInvestigationModel
from app.ai.openai_investigation import OpenAIInvestigationModel
from app.ai.provider import RealProviderDisabledError
from app.core.config import Settings
from app.domain.investigation import AgentDecision, DecisionObservation

__all__ = [
    "InvestigationModel",
    "build_investigation_model",
    "live_investigation_allowed",
]


class InvestigationModel(Protocol):
    name: str
    model_name: str
    reasoning_kind: str

    def decide(self, observation: DecisionObservation) -> AgentDecision: ...


def build_investigation_model(settings: Settings) -> InvestigationModel:
    """Select the decision implementation.

    Mock mode never constructs a client. OpenAI mode constructs one only when
    ``investigation_live_enabled`` is true and a server-side API key is set.
    """

    if settings.ai_mode == "mock":
        return MockInvestigationModel()
    if not live_investigation_allowed(settings):
        raise RealProviderDisabledError(
            "Live investigation is disabled. A model request requires "
            "AI_MODE=openai, INVESTIGATION_LIVE_ENABLED=true, and a server-side "
            "OPENAI_API_KEY. No client is created and no request is sent."
        )
    return OpenAIInvestigationModel(settings)
