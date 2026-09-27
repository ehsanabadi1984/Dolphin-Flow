from datetime import date, datetime

from django.test import SimpleTestCase

from workflow.date_field_services import DateFieldService


class DateFieldServiceTests(SimpleTestCase):

    def test_gregorian_date_is_canonical_passthrough(self):
        self.assertEqual(
            DateFieldService.to_canonical_date(
                "2026-09-27",
                DateFieldService.GREGORIAN,
            ),
            "2026-09-27",
        )

    def test_jalali_date_converts_to_gregorian(self):
        self.assertEqual(
            DateFieldService.to_canonical_date(
                "1405/07/05",
                DateFieldService.JALALI,
            ),
            "2026-09-27",
        )

    def test_persian_digit_jalali_date_converts(self):
        self.assertEqual(
            DateFieldService.to_canonical_date(
                "۱۴۰۵/۰۷/۰۵",
                DateFieldService.JALALI,
            ),
            "2026-09-27",
        )

    def test_gregorian_date_displays_as_jalali(self):
        self.assertEqual(
            DateFieldService.to_display_date(
                "2026-09-27",
                DateFieldService.JALALI,
            ),
            "۱۴۰۵/۰۷/۰۵",
        )

    def test_date_objects_are_supported(self):
        self.assertEqual(
            DateFieldService.to_display_date(
                date(2026, 9, 27),
                DateFieldService.JALALI,
            ),
            "۱۴۰۵/۰۷/۰۵",
        )

    def test_invalid_jalali_date_is_rejected(self):
        with self.assertRaises(ValueError):
            DateFieldService.to_canonical_date(
                "1405/13/01",
                DateFieldService.JALALI,
            )

    def test_invalid_jalali_shape_is_rejected(self):
        with self.assertRaises(ValueError):
            DateFieldService.to_canonical_date(
                "1405-07",
                DateFieldService.JALALI,
            )

    def test_gregorian_datetime_is_canonical(self):
        self.assertEqual(
            DateFieldService.to_canonical_datetime(
                "2026-09-27T14:30:00",
                DateFieldService.GREGORIAN,
            ),
            "2026-09-27T14:30:00",
        )

    def test_jalali_datetime_converts_to_gregorian(self):
        self.assertEqual(
            DateFieldService.to_canonical_datetime(
                "1405/07/05 14:30:00",
                DateFieldService.JALALI,
            ),
            "2026-09-27T14:30:00",
        )

    def test_gregorian_datetime_displays_as_jalali(self):
        self.assertEqual(
            DateFieldService.to_display_datetime(
                "2026-09-27T14:30:00",
                DateFieldService.JALALI,
            ),
            "۱۴۰۵/۰۷/۰۵ 14:30:00",
        )

    def test_empty_values_remain_empty(self):
        self.assertEqual(
            DateFieldService.to_canonical_date("", DateFieldService.JALALI),
            "",
        )
        self.assertEqual(
            DateFieldService.to_canonical_datetime("", DateFieldService.JALALI),
            "",
        )
