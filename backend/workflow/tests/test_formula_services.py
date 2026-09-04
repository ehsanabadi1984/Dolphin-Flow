from decimal import Decimal

from django.test import SimpleTestCase

from workflow.formula_services import FormulaError, FormulaService


class FormulaServiceTests(SimpleTestCase):
    def test_operator_precedence(self):
        tokens = [
            {"type": "number", "value": "2"},
            {"type": "operator", "value": "+"},
            {"type": "number", "value": "3"},
            {"type": "operator", "value": "*"},
            {"type": "number", "value": "4"},
        ]

        result = FormulaService.evaluate_tokens(
            tokens=tokens,
            field_resolver=lambda field_id: Decimal("0"),
        )

        self.assertEqual(result, Decimal("14"))

    def test_parentheses_override_precedence(self):
        tokens = [
            {"type": "paren", "value": "("},
            {"type": "number", "value": "2"},
            {"type": "operator", "value": "+"},
            {"type": "number", "value": "3"},
            {"type": "paren", "value": ")"},
            {"type": "operator", "value": "*"},
            {"type": "number", "value": "4"},
        ]

        result = FormulaService.evaluate_tokens(
            tokens=tokens,
            field_resolver=lambda field_id: Decimal("0"),
        )

        self.assertEqual(result, Decimal("20"))

    def test_field_reference(self):
        tokens = [
            {"type": "field", "field_id": 10},
            {"type": "operator", "value": "*"},
            {"type": "field", "field_id": 20},
        ]

        values = {10: Decimal("3"), 20: Decimal("7")}
        result = FormulaService.evaluate_tokens(
            tokens=tokens,
            field_resolver=lambda field_id: values[field_id],
        )

        self.assertEqual(result, Decimal("21"))

    def test_empty_values_can_be_normalized_to_zero(self):
        self.assertEqual(FormulaService._to_decimal(""), Decimal("0"))
        self.assertEqual(FormulaService._to_decimal(None), Decimal("0"))

    def test_division_by_zero_is_rejected(self):
        tokens = [
            {"type": "number", "value": "10"},
            {"type": "operator", "value": "/"},
            {"type": "number", "value": "0"},
        ]

        with self.assertRaises(FormulaError):
            FormulaService.evaluate_tokens(
                tokens=tokens,
                field_resolver=lambda field_id: Decimal("0"),
            )

    def test_result_rounding(self):
        result = FormulaService.format_result(Decimal("10.125"), 2)
        self.assertEqual(result, "10.13")
