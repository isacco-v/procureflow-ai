"""Flag instruction-like phrases in extracted document text.

The phrases stay data. Callers must not execute them or let them replace
field values that were read from labeled lines.
"""

import re

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    ),
    ("disregard_system", re.compile(r"disregard\s+(the\s+)?(system|developer)\b", re.I)),
    ("role_override", re.compile(r"you\s+are\s+now\b", re.I)),
    ("reveal_secret", re.compile(r"reveal\s+(the\s+)?(api\s+key|secret|system\s+prompt)", re.I)),
    ("approve_payment", re.compile(r"approve\s+payment", re.I)),
    ("system_tag", re.compile(r"<\s*/?\s*system\s*>", re.I)),
)


def find_prompt_injection(text: str) -> list[str]:
    """Return stable flag codes for instruction-like phrases. At most one per pattern."""

    flags: list[str] = []
    for code, pattern in _PATTERNS:
        if pattern.search(text):
            flags.append(code)
    return flags
