from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable

from django.core.exceptions import ValidationError

from .models import FormDefinition, FormField, FormRepeatableGroup


class FormulaError(ValidationError):
    """Raised when a configured formula cannot be parsed or evaluated."""


class FormulaService:
    """
    Safe arithmetic engine for dynamic FormField formulas.

    Formula definitions are stored as structured JSON tokens in the
    existing FormField.choices JSONField. No Python or JavaScript code
    is executed from a user-supplied formula.
    """

    VERSION = 1
    FIELD_TYPE = "FORMULA"
    MAX_TOKENS = 100
    MAX_DECIMAL_PLACES = 6

    OPERATORS = {
        "+": {"precedence": 1, "associativity": "left"},
        "-": {"precedence": 1, "associativity": "left"},
        "*": {"precedence": 2, "associativity": "left"},
        "/": {"precedence": 2, "associativity": "left"},
        "%": {"precedence": 2, "associativity": "left"},
    }

    @classmethod
    def is_formula(cls, field) -> bool:
        return bool(field and field.field_type == cls.FIELD_TYPE)

    @classmethod
    def get_config(cls, field) -> dict:
        if not cls.is_formula(field):
            return {}

        raw = field.choices
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                return {}

        if not isinstance(raw, dict):
            return {}

        if raw.get("version") != cls.VERSION:
            return {}

        tokens = raw.get("tokens")
        if not isinstance(tokens, list):
            return {}

        return {
            "version": cls.VERSION,
            "tokens": tokens,
            "decimal_places": int(raw.get("decimal_places", 2) or 0),
        }

    @classmethod
    def referenced_field_ids(cls, config: dict) -> set[int]:
        ids = set()
        for token in config.get("tokens", []):
            if token.get("type") == "field":
                try:
                    ids.add(int(token["field_id"]))
                except (KeyError, TypeError, ValueError):
                    continue
        return ids

    @classmethod
    def validate_tokens(
        cls,
        *,
        field,
        tokens,
        available_fields=None,
    ) -> None:
        if not isinstance(tokens, list) or not tokens:
            raise FormulaError("فرمول نمی‌تواند خالی باشد.")

        if len(tokens) > cls.MAX_TOKENS:
            raise FormulaError(
                f"فرمول نمی‌تواند بیشتر از {cls.MAX_TOKENS} جزء داشته باشد."
            )

        available = {
            int(item.pk): item
            for item in (available_fields or [])
            if getattr(item, "pk", None) is not None
        }

        expect_operand = True
        paren_depth = 0

        for token in tokens:
            if not isinstance(token, dict):
                raise FormulaError("ساختار یکی از اجزای فرمول نامعتبر است.")

            token_type = token.get("type")

            if expect_operand:
                if token_type == "number":
                    cls._parse_number(token.get("value"))
                    expect_operand = False

                elif token_type == "field":
                    field_id = cls._token_field_id(token)
                    if field_id not in available:
                        raise FormulaError("یکی از فیلدهای مورد استفاده در فرمول معتبر نیست.")

                    referenced = available[field_id]
                    if referenced.field_type not in {
                        FormField.FieldType.NUMBER,
                        cls.FIELD_TYPE,
                    }:
                        raise FormulaError(
                            f"فیلد «{referenced.label}» باید عددی یا محاسباتی باشد."
                        )

                    if field.repeatable_group_id:
                        if referenced.repeatable_group_id != field.repeatable_group_id:
                            raise FormulaError(
                                "فرمول یک ردیف جدول فقط می‌تواند به فیلدهای همان جدول ارجاع دهد."
                            )
                    else:
                        if referenced.repeatable_group_id is not None:
                            raise FormulaError(
                                "فرمول یک فیلد عادی نمی‌تواند مستقیماً به فیلد داخل جدول ارجاع دهد."
                            )

                    if referenced.pk == field.pk:
                        raise FormulaError("یک فیلد محاسباتی نمی‌تواند به خودش ارجاع دهد.")

                    expect_operand = False

                elif token_type == "paren" and token.get("value") == "(":
                    paren_depth += 1
                    expect_operand = True

                else:
                    raise FormulaError("فرمول باید با یک عدد، فیلد یا پرانتز باز شروع شود.")

            else:
                if token_type == "operator" and token.get("value") in cls.OPERATORS:
                    expect_operand = True

                elif token_type == "paren" and token.get("value") == ")":
                    paren_depth -= 1
                    if paren_depth < 0:
                        raise FormulaError("تعداد پرانتزهای فرمول نامتعادل است.")

                else:
                    raise FormulaError("ساختار عملگرهای فرمول نامعتبر است.")

        if expect_operand:
            raise FormulaError("فرمول نمی‌تواند با عملگر یا پرانتز باز پایان یابد.")

        if paren_depth:
            raise FormulaError("تعداد پرانتزهای فرمول نامتعادل است.")

    @classmethod
    def _token_field_id(cls, token: dict) -> int:
        try:
            return int(token["field_id"])
        except (KeyError, TypeError, ValueError):
            raise FormulaError("شناسه یکی از فیلدهای فرمول نامعتبر است.")

    @classmethod
    def _parse_number(cls, value) -> Decimal:
        if value in (None, ""):
            raise FormulaError("عدد موجود در فرمول نامعتبر است.")
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, AttributeError):
            raise FormulaError(f"مقدار «{value}» یک عدد معتبر نیست.")

    @classmethod
    def _to_decimal(cls, value) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        if isinstance(value, bool):
            return Decimal("1") if value else Decimal("0")
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, AttributeError):
            raise FormulaError(f"مقدار «{value}» قابل محاسبه نیست.")

    @classmethod
    def _to_rpn(cls, tokens):
        output = []
        operators = []

        for token in tokens:
            token_type = token["type"]
            if token_type in {"number", "field"}:
                output.append(token)
                continue

            if token_type == "operator":
                current = token["value"]
                current_meta = cls.OPERATORS[current]
                while operators and operators[-1]["type"] == "operator":
                    top = operators[-1]["value"]
                    top_meta = cls.OPERATORS[top]
                    should_pop = (
                        top_meta["precedence"] > current_meta["precedence"]
                        or (
                            top_meta["precedence"] == current_meta["precedence"]
                            and current_meta["associativity"] == "left"
                        )
                    )
                    if not should_pop:
                        break
                    output.append(operators.pop())
                operators.append(token)
                continue

            if token_type == "paren":
                if token["value"] == "(":
                    operators.append(token)
                else:
                    while operators and operators[-1].get("value") != "(":
                        output.append(operators.pop())
                    if not operators:
                        raise FormulaError("تعداد پرانتزهای فرمول نامتعادل است.")
                    operators.pop()
                continue

            raise FormulaError("نوع توکن فرمول پشتیبانی نمی‌شود.")

        while operators:
            if operators[-1].get("value") == "(":
                raise FormulaError("تعداد پرانتزهای فرمول نامتعادل است.")
            output.append(operators.pop())

        return output

    @classmethod
    def evaluate_tokens(
        cls,
        *,
        tokens,
        field_resolver: Callable[[int], Decimal],
    ) -> Decimal:
        rpn = cls._to_rpn(tokens)
        stack: list[Decimal] = []

        for token in rpn:
            token_type = token["type"]

            if token_type == "number":
                stack.append(cls._parse_number(token["value"]))
                continue

            if token_type == "field":
                stack.append(field_resolver(cls._token_field_id(token)))
                continue

            if token_type != "operator" or len(stack) < 2:
                raise FormulaError("فرمول از نظر ساختاری قابل محاسبه نیست.")

            right = stack.pop()
            left = stack.pop()
            operator = token["value"]

            if operator == "+":
                result = left + right
            elif operator == "-":
                result = left - right
            elif operator == "*":
                result = left * right
            elif operator == "/":
                if right == 0:
                    raise FormulaError("تقسیم بر صفر در فرمول مجاز نیست.")
                result = left / right
            elif operator == "%":
                if right == 0:
                    raise FormulaError("باقیمانده بر صفر در فرمول مجاز نیست.")
                result = left % right
            else:
                raise FormulaError("عملگر فرمول پشتیبانی نمی‌شود.")

            stack.append(result)

        if len(stack) != 1:
            raise FormulaError("فرمول نتیجه یکتایی تولید نکرد.")

        return stack[0]

    @classmethod
    def format_result(cls, value: Decimal, decimal_places: int) -> str:
        places = max(0, min(int(decimal_places or 0), cls.MAX_DECIMAL_PLACES))
        quantum = Decimal("1") if places == 0 else Decimal("1") / (Decimal("10") ** places)
        rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
        return format(rounded, f".{places}f")

    @classmethod
    def _formula_fields(cls, form: FormDefinition):
        return list(
            FormField.objects.filter(
                section__form=form,
                field_type=cls.FIELD_TYPE,
                is_active=True,
            ).select_related(
                "section",
                "repeatable_group",
            )
        )

    @classmethod
    def validate_form_formulas(cls, form: FormDefinition) -> None:
        all_fields = list(
            FormField.objects.filter(
                section__form=form,
                is_active=True,
            ).select_related("repeatable_group")
        )
        by_id = {field.pk: field for field in all_fields}

        formulas = [field for field in all_fields if cls.is_formula(field)]
        for field in formulas:
            config = cls.get_config(field)
            if not config:
                raise FormulaError(f"فرمول فیلد «{field.label}» تنظیم نشده است.")
            cls.validate_tokens(
                field=field,
                tokens=config["tokens"],
                available_fields=all_fields,
            )
            for field_id in cls.referenced_field_ids(config):
                if field_id not in by_id:
                    raise FormulaError(f"ارجاع فیلد «{field.label}» معتبر نیست.")

        formula_ids = {field.pk for field in formulas}
        dependencies = {
            field.pk: {
                dependency
                for dependency in cls.referenced_field_ids(cls.get_config(field))
                if dependency in formula_ids
            }
            for field in formulas
        }

        visiting = set()
        visited = set()

        def visit(node_id):
            if node_id in visiting:
                raise FormulaError("بین فیلدهای محاسباتی وابستگی دوری وجود دارد.")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in dependencies.get(node_id, set()):
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for formula_id in formula_ids:
            visit(formula_id)

    @classmethod
    def calculate_context_data(cls, *, form, data: dict) -> dict:
        cls.validate_form_formulas(form)
        result = dict(data or {})

        all_fields = list(
            FormField.objects.filter(
                section__form=form,
                is_active=True,
            ).select_related("repeatable_group")
        )
        by_id = {field.pk: field for field in all_fields}

        normal_formulas = [
            field
            for field in all_fields
            if cls.is_formula(field) and field.repeatable_group_id is None
        ]
        formula_cache: dict[int, Decimal] = {}
        calculating = set()

        def resolve_normal(field_id: int) -> Decimal:
            field = by_id.get(field_id)
            if field is None:
                raise FormulaError("ارجاع فیلد فرمول معتبر نیست.")

            if cls.is_formula(field):
                if field.pk in formula_cache:
                    return formula_cache[field.pk]
                if field.pk in calculating:
                    raise FormulaError("بین فیلدهای محاسباتی وابستگی دوری وجود دارد.")
                calculating.add(field.pk)
                config = cls.get_config(field)
                value = cls.evaluate_tokens(
                    tokens=config["tokens"],
                    field_resolver=resolve_normal,
                )
                calculating.remove(field.pk)
                formula_cache[field.pk] = value
                return value

            return cls._to_decimal(result.get(field.code))

        for field in normal_formulas:
            config = cls.get_config(field)
            value = resolve_normal(field.pk)
            result[field.code] = cls.format_result(
                value,
                config.get("decimal_places", 2),
            )

        normal_groups = {}
        for group in FormRepeatableGroup.objects.filter(
            section__form=form,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            is_active=True,
        ):
            rows = result.get(group.code, [])
            if not isinstance(rows, list):
                rows = []

            group_formula_fields = [
                field
                for field in all_fields
                if cls.is_formula(field)
                and field.repeatable_group_id == group.pk
            ]

            if not group_formula_fields:
                continue

            group_result = []
            group_field_ids = {
                field.pk: field
                for field in all_fields
                if field.repeatable_group_id == group.pk
            }

            for raw_row in rows:
                row = dict(raw_row) if isinstance(raw_row, dict) else {}
                row_cache: dict[int, Decimal] = {}
                row_calculating = set()

                def resolve_row(field_id: int) -> Decimal:
                    field = group_field_ids.get(field_id)
                    if field is None:
                        raise FormulaError("ارجاع فیلد جدول معتبر نیست.")
                    if cls.is_formula(field):
                        if field.pk in row_cache:
                            return row_cache[field.pk]
                        if field.pk in row_calculating:
                            raise FormulaError("بین فیلدهای محاسباتی جدول وابستگی دوری وجود دارد.")
                        row_calculating.add(field.pk)
                        cfg = cls.get_config(field)
                        val = cls.evaluate_tokens(
                            tokens=cfg["tokens"],
                            field_resolver=resolve_row,
                        )
                        row_calculating.remove(field.pk)
                        row_cache[field.pk] = val
                        return val
                    return cls._to_decimal(row.get(field.code))

                for field in group_formula_fields:
                    cfg = cls.get_config(field)
                    row[field.code] = cls.format_result(
                        resolve_row(field.pk),
                        cfg.get("decimal_places", 2),
                    )

                group_result.append(row)

            result[group.code] = group_result
            normal_groups[group.code] = group_result

        return result
