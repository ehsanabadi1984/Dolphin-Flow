import re
from decimal import Decimal, InvalidOperation

_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_GROUPED_INTEGER_PATTERN = re.compile(r"^\d{1,3}(?:,\d{3})+$")


class NumberFormatService:
    """Normalize numeric input and format numeric values for display only."""

    @staticmethod
    def normalize(value):
        if value is None:
            return ""
        normalized = str(value).strip().translate(_DIGIT_TRANSLATION)
        normalized = normalized.replace("٫", ".").replace("٬", ",")
        if not normalized:
            return ""
        if "," in normalized:
            signless = normalized[1:] if normalized[:1] in {"+", "-"} else normalized
            integer_part, separator, fraction_part = signless.partition(".")
            if not _GROUPED_INTEGER_PATTERN.fullmatch(integer_part):
                raise ValueError("Invalid thousands grouping")
            sign = normalized[:1] if normalized[:1] in {"+", "-"} else ""
            normalized = sign + integer_part.replace(",", "")
            if separator:
                normalized += separator + fraction_part
        if not _NUMBER_PATTERN.fullmatch(normalized):
            raise ValueError("Invalid numeric value")
        return normalized

    @classmethod
    def format_display(cls, value, decimal_places=None):
        if value in (None, ""):
            return ""
        try:
            number = Decimal(cls.normalize(value))
            if not number.is_finite():
                return str(value)
            places = max(0, min(int(decimal_places or 0), 12))
            formatted = f"{number:,.{places}f}"
            if "." in formatted:
                formatted = formatted.rstrip("0").rstrip(".")
            return formatted
        except (InvalidOperation, TypeError, ValueError, ArithmeticError):
            return str(value)
