from __future__ import annotations

import json

from django import forms
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse

from .formula_services import FormulaService
from .models import FormField, FormRepeatableGroup, FormSection


class FormulaBuilderField(forms.CharField):
    """Hidden JSON field used as the source of truth for the builder."""


class FormulaFieldAdminForm(forms.ModelForm):
    formula_builder = FormulaBuilderField(
        required=False,
        label="فرمول",
        help_text=(
            "اجزای فرمول را با انتخاب فیلدها و توابع بسازید. "
            "فیلد محاسباتی در پنل اپراتور همیشه فقط‌خواندنی است."
        ),
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "formula-builder-source",
                "style": "display:none;",
            }
        ),
    )

    formula_decimal_places = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=FormulaService.MAX_DECIMAL_PLACES,
        initial=2,
        label="تعداد اعشار",
        help_text="نتیجه قبل از ذخیره با این تعداد رقم اعشار گرد می‌شود.",
    )

    class Meta:
        model = FormField
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["choice_label_field"].widget = forms.Select()
        self.fields["choice_value_field"].widget = forms.Select()
        self.fields["choice_filter_field"].widget = forms.Select()

        original_field = self.fields["field_type"]
        choices = list(original_field.choices or [])
        if not any(value == FormulaService.FIELD_TYPE for value, _ in choices):
            choices.append((FormulaService.FIELD_TYPE, "فرمول"))
        original_field.choices = choices

        config = FormulaService.get_config(self.instance)
        if config:
            self.fields["formula_builder"].initial = json.dumps(
                config,
                ensure_ascii=False,
            )
            self.fields["formula_decimal_places"].initial = config.get(
                "decimal_places",
                2,
            )

        self.fields["formula_builder"].widget.attrs["data-options-url"] = reverse(
            "operator_panel:formula_field_options"
        )
        self._refresh_field_options()
        self._refresh_choice_model_fields()

    def _section_id(self):
        if self.instance and self.instance.pk:
            return self.instance.section_id
        raw = self.data.get(self.add_prefix("section")) if self.is_bound else None
        try:
            return int(raw) if raw else None
        except (TypeError, ValueError):
            return None

    def _group_id(self):
        if self.instance and self.instance.pk:
            return self.instance.repeatable_group_id
        raw = self.data.get(self.add_prefix("repeatable_group")) if self.is_bound else None
        try:
            return int(raw) if raw else None
        except (TypeError, ValueError):
            return None

    def _available_formula_fields(self):
        section_id = self._section_id()
        group_id = self._group_id()
        if not section_id:
            return FormField.objects.none()

        section = None
        if self.instance and self.instance.pk and self.instance.section_id == section_id:
            section = self.instance.section
        if section is None:
            section = (
                FormSection.objects
                .select_related("form")
                .filter(pk=section_id)
                .first()
            )
        if section is None:
            return FormField.objects.none()

        queryset = (
            FormField.objects
            .filter(
                section__form=section.form,
                is_active=True,
                field_type__in=[
                    FormField.FieldType.NUMBER,
                    FormulaService.FIELD_TYPE,
                ],
            )
            .select_related("repeatable_group", "section")
            .order_by(
                "section__order",
                "repeatable_group__order",
                "repeatable_group_id",
                "order",
                "id",
            )
        )

        current_id = self.instance.pk if self.instance and self.instance.pk else None
        if current_id:
            queryset = queryset.exclude(pk=current_id)

        if group_id:
            return queryset.filter(repeatable_group_id=group_id)

        return queryset

    def _refresh_field_options(self):
        options = [
            {
                "id": field.pk,
                "code": field.code,
                "label": field.label,
                "section_order": field.section.order,
                "section_id": field.section_id,
                "section_label": field.section.name,
                "group_code": field.repeatable_group.code if field.repeatable_group_id else None,
                "group_label": field.repeatable_group.name if field.repeatable_group_id else None,
                "is_group_field": field.repeatable_group_id is not None,
            }
            for field in self._available_formula_fields()
        ]
        self.fields["formula_builder"].widget.attrs["data-field-options"] = json.dumps(
            options,
            ensure_ascii=False,
        )

    def _choice_model(self):
        choice_model = self.instance.choice_model if self.instance and self.instance.pk else None
        if self.is_bound:
            raw = self.data.get(self.add_prefix("choice_model"))
            if raw:
                try:
                    choice_model = ContentType.objects.get(pk=raw)
                except (ContentType.DoesNotExist, ValueError, TypeError):
                    choice_model = None
        return choice_model

    def _refresh_choice_model_fields(self):
        label_field = self.fields.get("choice_label_field")
        value_field = self.fields.get("choice_value_field")
        filter_field = self.fields.get("choice_filter_field")
        model_class = self._choice_model()
        model_class = model_class.model_class() if model_class else None

        field_choices = []
        filter_choices = []
        if model_class:
            for field in model_class._meta.get_fields():
                if not getattr(field, "concrete", False):
                    continue
                if getattr(field, "auto_created", False):
                    continue
                if not getattr(field, "editable", True):
                    continue

                choice = (field.name, f"{field.name} ({field.verbose_name})")
                field_choices.append(choice)
                if isinstance(field, models.ForeignKey):
                    related_model = field.remote_field.model
                    filter_choices.append(
                        (
                            field.name,
                            f"{field.name} → {related_model._meta.verbose_name}",
                        )
                    )

        if label_field:
            label_field.choices = [("", "---------"), *field_choices]
            label_field.initial = self.instance.choice_label_field if self.instance and self.instance.pk else ""

        if value_field:
            value_field.choices = [("", "---------"), ("id", "id (شناسه)"), *field_choices]
            value_field.initial = self.instance.choice_value_field if self.instance and self.instance.pk else ""

        if filter_field:
            filter_field.choices = [("", "---------"), *filter_choices]
            filter_field.initial = self.instance.choice_filter_field if self.instance and self.instance.pk else ""

    def clean(self):
        cleaned = super().clean()
        field_type = cleaned.get("field_type")

        if field_type != FormulaService.FIELD_TYPE:
            return cleaned

        group = cleaned.get("repeatable_group")
        if group and group.group_type == FormRepeatableGroup.GroupType.DEVICE:
            raise ValidationError(
                {
                    "field_type": "فیلدهای فرمولی داخل گروه دستگاه‌ها پشتیبانی نمی‌شوند."
                }
            )

        cleaned["is_required"] = False
        cleaned["system_key"] = FormField.SystemKey.NONE
        cleaned["choice_source"] = FormField.ChoiceSource.NONE
        cleaned["choice_model"] = None
        cleaned["choice_static_set"] = None
        cleaned["choice_lookup_list"] = None
        cleaned["choice_label_field"] = ""
        cleaned["choice_value_field"] = ""
        cleaned["choice_parent_field"] = None
        cleaned["choice_filter_field"] = ""

        raw = cleaned.get("formula_builder")
        if not raw:
            raise ValidationError({"formula_builder": "فرمول را مشخص کنید."})

        try:
            config = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValidationError({"formula_builder": "ساختار فرمول نامعتبر است."})

        if not isinstance(config, dict):
            raise ValidationError({"formula_builder": "ساختار فرمول نامعتبر است."})

        tokens = config.get("tokens")
        if not isinstance(tokens, list):
            raise ValidationError({"formula_builder": "اجزای فرمول معتبر نیستند."})

        decimals = cleaned.get("formula_decimal_places")
        if decimals is None:
            decimals = 2

        draft = self.instance
        draft.field_type = FormulaService.FIELD_TYPE
        draft.repeatable_group = group

        try:
            FormulaService.validate_tokens(
                field=draft,
                tokens=tokens,
                available_fields=list(self._available_formula_fields()),
            )
        except ValidationError as exc:
            raise ValidationError({"formula_builder": exc.messages})

        cleaned["formula_config"] = {
            "version": FormulaService.VERSION,
            "tokens": tokens,
            "decimal_places": max(
                0,
                min(int(decimals), FormulaService.MAX_DECIMAL_PLACES),
            ),
        }
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)

        if instance.field_type == FormulaService.FIELD_TYPE:
            config = self.cleaned_data.get("formula_config")
            if config:
                instance.choices = config
            instance.is_required = False
            instance.system_key = FormField.SystemKey.NONE
            instance.choice_source = FormField.ChoiceSource.NONE
            instance.choice_model = None
            instance.choice_static_set = None
            instance.choice_lookup_list = None
            instance.choice_label_field = ""
            instance.choice_value_field = ""
            instance.choice_parent_field = None
            instance.choice_filter_field = ""
        else:
            old_config = FormulaService.get_config(self.instance)
            if old_config:
                instance.choices = []

        if commit:
            instance.save()
            self.save_m2m()
        return instance
