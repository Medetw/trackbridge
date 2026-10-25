import re

_NON_DIGITS = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    """Normalize to E.164 (`+77011234567`). Kazakh local formats (`8 701 ...`, `701 ...`) are mapped to +7."""
    digits = _NON_DIGITS.sub("", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10 and digits.startswith("7"):
        digits = "7" + digits
    if not 10 <= len(digits) <= 15:
        raise ValueError(f"'{raw}' is not a valid phone number")
    return "+" + digits
