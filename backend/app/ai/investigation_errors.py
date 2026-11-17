"""Stop an investigation model without hiding the reason or the usage."""

from decimal import Decimal

from app.domain.investigation import InvestigationStatus


class InvestigationModelStop(Exception):
    """A model step ended before a recommendation could be accepted.

    Token fields are the usage of the request that already happened. They are
    zero when no request was sent. The detail is a fixed sentence and must not
    carry response text, document text, or an API key.
    """

    def __init__(
        self,
        status: InvestigationStatus,
        error_code: str,
        detail: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: Decimal | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.error_code = error_code
        self.detail = detail
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.estimated_cost_usd = Decimal("0") if estimated_cost_usd is None else estimated_cost_usd
