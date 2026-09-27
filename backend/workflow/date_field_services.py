"""Presentation/canonical conversion for DATE and DATETIME form fields.

This service deliberately knows nothing about forms, persistence, permissions,
or HTTP. It only converts between Gregorian canonical values and Jalali
presentation values.
"""

from datetime import date, datetime

import jdatetime
from django.utils import timezone


class DateFieldService:
    """Convert form date values between Gregorian and Jalali calendars."""

    GREGORIAN = "GREGORIAN"
    JALALI = "JALALI"

    _PERSIAN_DIGITS = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )

    @classmethod
    def to_canonical_date(cls, value, calendar=GREGORIAN):
        """Return a canonical Gregorian YYYY-MM-DD string."""
        if value in (None, ""):
            return value

        if isinstance(value, datetime):
            raise ValueError("Expected a date, not a datetime.")

        if isinstance(value, date):
            return value.isoformat()

        text = cls._normalize_digits(str(value).strip())

        if calendar == cls.GREGORIAN:
            return date.fromisoformat(text).isoformat()

        if calendar == cls.JALALI:
            year, month, day = cls._parse_calendar_date(text)
            jalali = jdatetime.date(year, month, day)
            return jalali.togregorian().isoformat()

        raise ValueError(f"Unsupported calendar: {calendar!r}")

    @classmethod
    def to_display_date(cls, value, calendar=GREGORIAN):
        """Return a calendar-formatted date for operator presentation."""
        if value in (None, ""):
            return value

        if isinstance(value, datetime):
            raise ValueError("Expected a date, not a datetime.")

        if isinstance(value, date):
            gregorian = value
        else:
            gregorian = date.fromisoformat(
                cls._normalize_digits(str(value).strip())
            )

        if calendar == cls.GREGORIAN:
            return gregorian.isoformat()

        if calendar == cls.JALALI:
            jalali = jdatetime.date.fromgregorian(date=gregorian)
            return cls._persian_digits(
                f"{jalali.year:04d}/{jalali.month:02d}/{jalali.day:02d}"
            )

        raise ValueError(f"Unsupported calendar: {calendar!r}")

    @classmethod
    def to_canonical_datetime(cls, value, calendar=GREGORIAN):
        """Return a canonical Gregorian ISO datetime string."""
        if value in (None, ""):
            return value

        if isinstance(value, str):
            value = cls._parse_datetime(value, calendar=calendar)

        if not isinstance(value, datetime):
            raise ValueError("Expected a datetime.")

        if calendar == cls.GREGORIAN:
            return value.isoformat()

        if calendar != cls.JALALI:
            raise ValueError(f"Unsupported calendar: {calendar!r}")

        gregorian_date = cls.to_canonical_date(
            value.date(),
            calendar=cls.JALALI,
        )
        converted = date.fromisoformat(gregorian_date)
        result = datetime.combine(
            converted,
            value.timetz(),
        )
        return result.isoformat()

    @classmethod
    def to_display_datetime(cls, value, calendar=GREGORIAN):
        """Return a calendar-formatted datetime for operator presentation."""
        if value in (None, ""):
            return value

        if isinstance(value, str):
            # Display values originate from canonical Gregorian persistence.
            # The requested calendar controls only the presentation output.
            value = cls._parse_datetime(
                value,
                calendar=cls.GREGORIAN,
            )

        if not isinstance(value, datetime):
            raise ValueError("Expected a datetime.")

        if timezone.is_aware(value):
            value = timezone.localtime(value)

        if calendar == cls.GREGORIAN:
            return value.isoformat(sep=" ")

        if calendar != cls.JALALI:
            raise ValueError(f"Unsupported calendar: {calendar!r}")

        jalali = jdatetime.date.fromgregorian(date=value.date())
        date_part = cls._persian_digits(
            f"{jalali.year:04d}/{jalali.month:02d}/{jalali.day:02d}"
        )
        return f"{date_part} {value.strftime('%H:%M:%S')}"

    @classmethod
    def _parse_datetime(cls, value, *, calendar):
        text = cls._normalize_digits(str(value).strip())

        if calendar == cls.GREGORIAN:
            return datetime.fromisoformat(text)

        if calendar != cls.JALALI:
            raise ValueError(f"Unsupported calendar: {calendar!r}")

        if "T" in text:
            date_text, time_text = text.split("T", 1)
        elif " " in text:
            date_text, time_text = text.split(" ", 1)
        else:
            raise ValueError("Invalid datetime.")

        gregorian_date = cls.to_canonical_date(
            date_text,
            calendar=cls.JALALI,
        )
        return datetime.fromisoformat(
            f"{gregorian_date}T{time_text}"
        )

    @classmethod
    def _parse_calendar_date(cls, value):
        parts = value.replace("-", "/").split("/")
        if len(parts) != 3:
            raise ValueError("Invalid calendar date.")

        try:
            return tuple(int(part) for part in parts)
        except ValueError as exc:
            raise ValueError("Invalid calendar date.") from exc

    @classmethod
    def _normalize_digits(cls, value):
        return value.translate(cls._PERSIAN_DIGITS)

    @classmethod
    def _persian_digits(cls, value):
        return value.translate(
            str.maketrans(
                "0123456789",
                "۰۱۲۳۴۵۶۷۸۹",
            )
        )
