"""Decimal parsing and canonical text for quantities and money.

Floats are rejected. Equal values such as ``100`` and ``100.0000`` share one text form.
"""

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema


def parse_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Quantities and money must be decimal strings, not floats.")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal value.") from exc
    else:
        raise ValueError("Invalid decimal value.")
    if not parsed.is_finite():
        raise ValueError("Decimal value must be finite.")
    return parsed


def format_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-", "-0"}:
        return "0"
    return rendered


StrictDecimal = Annotated[Decimal, BeforeValidator(parse_decimal)]

ApiDecimal = Annotated[
    Decimal,
    BeforeValidator(parse_decimal),
    PlainSerializer(format_decimal, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$"}),
]
