"""Estimated USD cost from a configurable per-model price table.

The mock investigation does not call this. A figure produced here is an
application safeguard. It is a price-table estimate, not a provider invoice
and not a guaranteed spending cap.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import Settings

_MILLION = Decimal(1_000_000)
_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class TokenPrice:
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal


@dataclass(frozen=True, slots=True)
class RequestReservation:
    """Conservative token and cost reservation for one request that has not been sent."""

    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal


def pricing_table(settings: Settings) -> dict[str, TokenPrice]:
    """Return the models this process is willing to price.

    The table has one row, the configured model, so an unlisted model cannot
    be billed at a guessed rate.
    """

    return {
        settings.openai_model: TokenPrice(
            input_usd_per_million=settings.openai_input_usd_per_million,
            output_usd_per_million=settings.openai_output_usd_per_million,
        )
    }


def estimate_openai_cost_usd(
    input_tokens: int,
    output_tokens: int,
    settings: Settings,
    *,
    model: str | None = None,
) -> Decimal:
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts cannot be negative.")
    name = settings.openai_model if model is None else model
    try:
        rate = pricing_table(settings)[name]
    except KeyError as exc:
        raise ValueError("No price is configured for the requested model.") from exc
    input_cost = (Decimal(input_tokens) / _MILLION) * rate.input_usd_per_million
    output_cost = (Decimal(output_tokens) / _MILLION) * rate.output_usd_per_million
    return (input_cost + output_cost).quantize(_QUANTUM)


def reserve_request_cost_usd(
    *,
    prompt_characters: int,
    max_output_tokens: int,
    settings: Settings,
) -> RequestReservation:
    """Over-estimate the next request so a shortfall stops the run first.

    Input tokens are estimated at two characters per token, plus a fixed
    margin. Output tokens are reserved at the configured maximum. Provider
    ``output_tokens`` already include reasoning tokens, so this reservation
    is not added to a separate reasoning count. The result is an application
    safeguard, not a guaranteed provider billing cap.
    """

    if prompt_characters < 0 or max_output_tokens < 0:
        raise ValueError("Reservation inputs cannot be negative.")
    estimated_input = max(1, prompt_characters // 2 + 256)
    cost = estimate_openai_cost_usd(estimated_input, max_output_tokens, settings)
    return RequestReservation(
        input_tokens=estimated_input,
        output_tokens=max_output_tokens,
        estimated_cost_usd=cost,
    )
