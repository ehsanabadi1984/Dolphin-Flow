from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from workflow.formula_services import FormulaError, FormulaService
from workflow.models import FormField


class FormulaServiceTests(SimpleTestCase):
    def test_operator_precedence(self):
        tokens = [
            {"type": "number", "value": "2"},
            {"type": "operator", "value": "+"},
            {"type": "number", "value": "3"},
            {"type": "operator", "value": "*"},
            {"type": "number", "value": "4"},
        ]
        result = FormulaService.evaluate_tokens(tokens=tokens, field_resolver=lambda field_id: Decimal("0"))
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
        result = FormulaService.evaluate_tokens(tokens=tokens, field_resolver=lambda field_id: Decimal("0"))
        self.assertEqual(result, Decimal("20"))

    def test_field_reference(self):
        tokens = [
            {"type": "field", "field_id": 10},
            {"type": "operator", "value": "*"},
            {"type": "field", "field_id": 20},
        ]
        values = {10: Decimal("3"), 20: Decimal("7")}
        result = FormulaService.evaluate_tokens(tokens=tokens, field_resolver=lambda field_id: values[field_id])
        self.assertEqual(result, Decimal("21"))

    def test_sum_function(self):
        tokens = [
            {"type": "function", "value": "SUM"},
            {"type": "paren", "value": "("},
            {"type": "number", "value": "10"},
            {"type": "comma", "value": ","},
            {"type": "number", "value": "2.5"},
            {"type": "comma", "value": ","},
            {"type": "number", "value": "7.5"},
            {"type": "paren", "value": ")"},
        ]
        result = FormulaService.evaluate_tokens(tokens=tokens, field_resolver=lambda field_id: Decimal("0"))
        self.assertEqual(result, Decimal("20"))

    def test_abs_function(self):
        tokens = [
            {"type": "function", "value": "ABS"},
            {"type": "paren", "value": "("},
            {"type": "number", "value": "-12.5"},
            {"type": "paren", "value": ")"},
        ]
        result = FormulaService.evaluate_tokens(tokens=tokens, field_resolver=lambda field_id: Decimal("0"))
        self.assertEqual(result, Decimal("12.5"))

    def test_min_max_and_average_functions(self):
        base = [
            {"type": "number", "value": "10"},
            {"type": "comma", "value": ","},
            {"type": "number", "value": "4"},
            {"type": "comma", "value": ","},
            {"type": "number", "value": "7"},
        ]
        for name, expected in (("MIN", Decimal("4")), ("MAX", Decimal("10")), ("AVG", Decimal("7"))):
            tokens = [{"type": "function", "value": name}, {"type": "paren", "value": "("}, *base, {"type": "paren", "value": ")"}]
            result = FormulaService.evaluate_tokens(tokens=tokens, field_resolver=lambda field_id: Decimal("0"))
            self.assertEqual(result, expected)

    def test_round_floor_and_ceil_functions(self):
        resolver = lambda field_id: Decimal("0")
        round_tokens = [
            {"type": "function", "value": "ROUND"}, {"type": "paren", "value": "("},
            {"type": "number", "value": "10.125"}, {"type": "comma", "value": ","},
            {"type": "number", "value": "2"}, {"type": "paren", "value": ")"},
        ]
        floor_tokens = [{"type": "function", "value": "FLOOR"}, {"type": "paren", "value": "("}, {"type": "number", "value": "10.9"}, {"type": "paren", "value": ")"}]
        ceil_tokens = [{"type": "function", "value": "CEIL"}, {"type": "paren", "value": "("}, {"type": "number", "value": "10.1"}, {"type": "paren", "value": ")"}]
        self.assertEqual(FormulaService.evaluate_tokens(tokens=round_tokens, field_resolver=resolver), Decimal("10.13"))
        self.assertEqual(FormulaService.evaluate_tokens(tokens=floor_tokens, field_resolver=resolver), Decimal("10"))
        self.assertEqual(FormulaService.evaluate_tokens(tokens=ceil_tokens, field_resolver=resolver), Decimal("11"))

    def test_cross_section_top_level_field_reference_is_allowed(self):
        formula_field = SimpleNamespace(pk=2, field_type=FormulaService.FIELD_TYPE, repeatable_group_id=None, label="قیمت نهایی")
        number_in_other_section = SimpleNamespace(pk=1, field_type=FormField.FieldType.NUMBER, repeatable_group_id=None, label="تعداد")
        FormulaService.validate_tokens(
            field=formula_field,
            tokens=[{"type": "field", "field_id": 1}],
            available_fields=[number_in_other_section],
        )

    def test_group_field_is_allowed_only_as_aggregate_input_for_top_level_formula(self):
        formula_field = SimpleNamespace(pk=3, field_type=FormulaService.FIELD_TYPE, repeatable_group_id=None, label="جمع کل")
        group_number = SimpleNamespace(pk=1, field_type=FormField.FieldType.NUMBER, repeatable_group_id=100, label="مبلغ")

        tokens = [
            {"type": "function", "value": "SUM"},
            {"type": "paren", "value": "("},
            {"type": "field", "field_id": 1},
            {"type": "paren", "value": ")"},
        ]
        FormulaService.validate_tokens(field=formula_field, tokens=tokens, available_fields=[group_number])

        with self.assertRaises(FormulaError):
            FormulaService.validate_tokens(
                field=formula_field,
                tokens=[{"type": "field", "field_id": 1}],
                available_fields=[group_number],
            )

    def test_aggregate_function_can_resolve_group_field(self):
        tokens = [
            {"type": "function", "value": "SUM"},
            {"type": "paren", "value": "("},
            {"type": "field", "field_id": 10},
            {"type": "paren", "value": ")"},
        ]
        result = FormulaService.evaluate_tokens(
            tokens=tokens,
            field_resolver=lambda field_id: Decimal("0"),
            aggregate_field_resolver=lambda field_id, function_name: Decimal("42"),
        )
        self.assertEqual(result, Decimal("42"))

    def test_row_formula_cannot_reference_other_group(self):
        formula_field = SimpleNamespace(pk=3, field_type=FormulaService.FIELD_TYPE, repeatable_group_id=100, label="جمع ردیف")
        number_in_other_group = SimpleNamespace(pk=1, field_type=FormField.FieldType.NUMBER, repeatable_group_id=200, label="مبلغ")
        with self.assertRaises(FormulaError):
            FormulaService.validate_tokens(
                field=formula_field,
                tokens=[{"type": "field", "field_id": 1}],
                available_fields=[number_in_other_group],
            )

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
            FormulaService.evaluate_tokens(tokens=tokens, field_resolver=lambda field_id: Decimal("0"))

    def test_result_rounding(self):
        result = FormulaService.format_result(Decimal("10.125"), 2)
        self.assertEqual(result, "10.13")
