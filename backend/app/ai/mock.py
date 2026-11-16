from decimal import Decimal

from app.ai.provider import CompletionRequest, CompletionResponse


class MockAIProvider:
    """Deterministic provider that does not read credentials or open a socket.

    Token and cost figures are zero because no model was invoked. They are
    not an estimate of a production call.
    """

    name = "mock"

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        return CompletionResponse(
            provider="mock",
            model="mock",
            content=(f"Mock provider received purpose '{request.purpose}'. No model was called."),
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=Decimal("0"),
        )
