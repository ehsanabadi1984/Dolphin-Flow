from decimal import Decimal

from django.test import SimpleTestCase

from workflow.number_format_services import NumberFormatService


class NumberFormatServiceTests(SimpleTestCase):
    def test_formats_large_integer_with_thousands_separators(self):
        self.assertEqual(NumberFormatService.format_display("11300000"), "11،300،000")

    def test_preserves_small_values_and_decimal_precision(self):
        self.assertEqual(NumberFormatService.format_display("999"), "999")
        self.assertEqual(NumberFormatService.format_display("12500.750", 3), "12،500.75")
        self.assertEqual(NumberFormatService.format_display("12500.75"), "12،500.75")

    def test_formats_negative_decimal_values(self):
        self.assertEqual(NumberFormatService.format_display(Decimal("-1250000.75"), 2), "-1،250،000.75")

    def test_normalizes_persian_and_arabic_digits_and_grouping(self):
        self.assertEqual(NumberFormatService.normalize("۱۱،۳۰۰،۰۰۰"), "11300000")
        self.assertEqual(NumberFormatService.normalize("۱۱,۳۰۰,۰۰۰"), "11300000")
        self.assertEqual(NumberFormatService.normalize("-١،٢٥٠،٠٠٠٫٧٥"), "-1250000.75")

    def test_rejects_malformed_grouping(self):
        with self.assertRaises(ValueError):
            NumberFormatService.normalize("12,50")
