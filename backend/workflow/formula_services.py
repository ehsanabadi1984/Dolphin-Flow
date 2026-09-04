from __future__ import annotations

import json
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_UP,
)
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

    VERSION = 2
    SUPPORTED_VERSIONS = {1, 2}
    FIELD_TYPE = "FORMULA"
    MAX_TOKENS = 100
    MAX_DECIMAL_PLACES = 6
    MAX_FUNCTION_ARGUMENTS = 20

    OPERATORS = {
        "+": {"precedence": 1, "associativity": "left"},
        "-": {"precedence": 1, "associativity": "left"},
        "*": {"precedence": 2, "associativity": "left"},
        "/": {"precedence": 2, "associativity": "left"},
        "%": {"precedence": 2, "associativity": "left"},
    }

    FUNCTIONS = {
        "SUM": {"min_args": 1, "max_args": MAX_FUNCTION_ARGUMENTS},
        "ABS": {"min_args": 1, "max_args": 1},
        "MIN": {"min_args": 1, "max_args": MAX_FUNCTION_ARGUMENTS},
        "MAX": {"min_args": 1, "max_args": MAX_FUNCTION_ARGUMENTS},
        "AVG": {"min_args": 1, "max_args": MAX_FUNCTION_ARGUMENTS},
        "ROUND": {"min_args": 1, "max_args": 2},
        "FLOOR": {"min_args": 1, "max_args": 1},
        "CEIL": {"min_args": 1, "max_args": 1},
    }

    FUNCTION_LABELS = {
        "SUM": "جمع",
        "ABS": "قدر مطلق",
        "MIN": "کمینه",
        "MAX": "بیشینه",
        "AVG": "میانگین",
        "ROUND": "گرد کردن",
        "FLOOR": "کف",
        "CEIL": "سقف",
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

        if raw.get("version") not in cls.SUPPORTED_VERSIONS:
            return {}

        tokens = raw.get("tokens")
        if not isinstance(tokens, list):
            return {}

        try:
            decimal_places = int(raw.get("decimal_places", 2) or 0)
        except (TypeError, ValueError):
            decimal_places = 2

        return {
            "version": int(raw.get("version")),
            "tokens": tokens,
            "decimal_places": decimal_places,
        }

    @classmethod
    def referenced_field_ids(cls, config: dict) -> set[int]:
        ids: set[int] = set()

        def visit(tokens):
            for token in tokens or []:
                if not isinstance(token, dict):
                    continue
                if token.get("type") == "field":
                    try:
                        ids.add(int(token["field_id"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                elif token.get("type") == "function":
                    nested = token.get("tokens")
                    if isinstance(nested, list):
                        visit(nested)

        visit(config.get("tokens", []))
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

        ast = cls._parse_tokens(tokens)
        cls._validate_ast(field=field, node=ast, available=available)

    @classmethod
    def _parse_tokens(cls, tokens):
        class Parser:
            def __init__(self, owner, items):
                self.owner = owner
                self.items = items
                self.pos = 0

            def current(self):
                if self.pos >= len(self.items):
                    return None
                return self.items[self.pos]

            def advance(self):
                token = self.current()
                self.pos += 1
                return token

            def match(self, token_type, value=None):
                token = self.current()
                if not isinstance(token, dict) or token.get("type") != token_type:
                    return False
                if value is not None and token.get("value") != value:
                    return False
                return True

            def parse(self):
                node = self.parse_expression()
                if self.current() is not None:
                    raise FormulaError("ساختار فرمول نامعتبر است.")
                return node

            def parse_expression(self):
                node = self.parse_term()
                while self.match("operator", "+") or self.match("operator", "-"):
                    operator = self.advance()["value"]
                    right = self.parse_term()
                    node = ("binary", operator, node, right)
                return node

            def parse_term(self):
                node = self.parse_factor()
                while (
                    self.match("operator", "*")
                    or self.match("operator", "/")
                    or self.match("operator", "%")
                ):
                    operator = self.advance()["value"]
                    right = self.parse_factor()
                    node = ("binary", operator, node, right)
                return node

            def parse_factor(self):
                token = self.current()
                if not isinstance(token, dict):
                    raise FormulaError("فرمول باید با عدد، فیلد، تابع یا پرانتز شروع شود.")

                token_type = token.get("type")
                if token_type == "number":
                    self.advance()
                    value = self.owner._parse_number(token.get("value"))
                    return ("number", value)

                if token_type == "field":
                    self.advance()
                    return ("field", self.owner._token_field_id(token))

                if token_type == "paren" and token.get("value") == "(":
                    self.advance()
                    node = self.parse_expression()
                    if not self.match("paren", ")"):
                        raise FormulaError("تعداد پرانتزهای فرمول نامتعادل است.")
                    self.advance()
                    return node

                if token_type == "function":
                    self.advance()
                    name = str(token.get("value", "")).upper()
                    if name not in self.owner.FUNCTIONS:
                        raise FormulaError(f"تابع «{name}» پشتیبانی نمی‌شود.")
                    if not self.match("paren", "("):
                        raise FormulaError(f"تابع «{name}» باید با پرانتز باز همراه باشد.")
                    self.advance()

                    args = []
                    if not self.match("paren", ")"):
                        while True:
                            args.append(self.parse_expression())
                            if len(args) > self.owner.MAX_FUNCTION_ARGUMENTS:
                                raise FormulaError(
                                    f"تعداد ورودی‌های تابع «{name}» بیش از حد مجاز است."
                                )
                            if self.match("comma"):
                                self.advance()
                                if self.match("paren", ")"):
                                    raise FormulaError("بعد از ویرگول باید یک مقدار قرار گیرد.")
                                continue
                            break

                    if not self.match("paren", ")"):
                        raise FormulaError(
                            f"پرانتزهای تابع «{name}» کامل نشده است."
                        )
                    self.advance()
                    return ("function", name, args)

                if token_type in {"operator", "comma"}:
                    raise FormulaError("جای یکی از اجزای فرمول نامعتبر است.")

                if token_type == "paren" and token.get("value") == ")":
                    raise FormulaError("تعداد پرانتزهای فرمول نامتعادل است.")

                raise FormulaError("نوع توکن فرمول پشتیبانی نمی‌شود.")

        return Parser(cls, tokens).parse()

    @classmethod
    def _validate_ast(cls, *, field, node, available):
        node_type = node[0]

        if node_type == "number":
            return

        if node_type == "field":
            field_id = node[1]
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
            elif referenced.repeatable_group_id is not None:
                raise FormulaError(
                    "فرمول یک فیلد عادی نمی‌تواند مستقیماً به فیلد داخل جدول ارجاع دهد."
                )

            if referenced.pk == field.pk:
                raise FormulaError("یک فیلد محاسباتی نمی‌تواند به خودش ارجاع دهد.")
            return

        if node_type == "binary":
            cls._validate_ast(field=field, node=node[2], available=available)
            cls._validate_ast(field=field, node=node[3], available=available)
            return

        if node_type == "function":
            name = node[1]
            args = node[2]
            meta = cls.FUNCTIONS.get(name)
            if not meta:
                raise FormulaError(f"تابع «{name}» پشتیبانی نمی‌شود.")
            if not meta["min_args"] <= len(args) <= meta["max_args"]:
                raise FormulaError(
                    f"تابع «{name}» باید بین {meta['min_args']} تا {meta['max_args']} ورودی داشته باشد."
                )
            for arg in args:
                cls._validate_ast(field=field, node=arg, available=available)
            return

        raise FormulaError("ساختار فرمول نامعتبر است.")

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
    def evaluate_tokens(
        cls,
        *,
        tokens,
        field_resolver: Callable[[int], Decimal],
    ) -> Decimal:
        ast = cls._parse_tokens(tokens)
        return cls._evaluate_ast(ast, field_resolver)

    @classmethod
    def _evaluate_ast(cls, node, field_resolver):
        node_type = node[0]
        if node_type == "number":
            return node[1]

        if node_type == "field":
            return cls._to_decimal(field_resolver(node[1]))

        if node_type == "binary":
            operator = node[1]
            left = cls._evaluate_ast(node[2], field_resolver)
            right = cls._evaluate_ast(node[3], field_resolver)
            if operator == "+":
                return left + right
            if operator == "-":
                return left - right
            if operator == "*":
                return left * right
            if operator == "/":
                if right == 0:
                    raise FormulaError("تقسیم بر صفر در فرمول مجاز نیست.")
                return left / right
            if operator == "%":
                if right == 0:
                    raise FormulaError("باقیمانده بر صفر در فرمول مجاز نیست.")
                return left % right
            raise FormulaError("عملگر فرمول پشتیبانی نمی‌شود.")

        if node_type == "function":
            name = node[1]
            args = [cls._evaluate_ast(arg, field_resolver) for arg in node[2]]
            return cls._evaluate_function(name, args)

        raise FormulaError("ساختار فرمول نامعتبر است.")

    @classmethod
    def _evaluate_function(cls, name: str, args: list[Decimal]) -> Decimal:
        if name == "SUM":
            return sum(args, Decimal("0"))
        if name == "ABS":
            return abs(args[0])
        if name == "MIN":
            return min(args)
        if name == "MAX":
            return max(args)
        if name == "AVG":
            return sum(args, Decimal("0")) / Decimal(len(args))
        if name == "ROUND":
            places = 0
            if len(args) == 2:
                places = cls._function_decimal_places(args[1])
            quantum = Decimal("1") if places == 0 else Decimal("1") / (Decimal("10") ** places)
            return args[0].quantize(quantum, rounding=ROUND_HALF_UP)
        if name == "FLOOR":
            return args[0].to_integral_value(rounding=ROUND_FLOOR)
        if name == "CEIL":
            return args[0].to_integral_value(rounding=ROUND_CEILING)
        raise FormulaError(f"تابع «{name}» پشتیبانی نمی‌شود.")

    @classmethod
    def _function_decimal_places(cls, value: Decimal) -> int:
        if value != value.to_integral_value():
            raise FormulaError("تعداد اعشار تابع ROUND باید عدد صحیح باشد.")
        places = int(value)
        if places < 0 or places > cls.MAX_DECIMAL_PLACES:
            raise FormulaError(
                f"تعداد اعشار تابع ROUND باید بین ۰ و {cls.MAX_DECIMAL_PLACES} باشد."
            )
        return places

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
                try:
                    config = cls.get_config(field)
                    value = cls.evaluate_tokens(
                        tokens=config["tokens"],
                        field_resolver=resolve_normal,
                    )
                finally:
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
                            raise FormulaError(
                                "بین فیلدهای محاسباتی جدول وابستگی دوری وجود دارد."
                            )
                        row_calculating.add(field.pk)
                        try:
                            cfg = cls.get_config(field)
                            val = cls.evaluate_tokens(
                                tokens=cfg["tokens"],
                                field_resolver=resolve_row,
                            )
                        finally:
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

        return result
