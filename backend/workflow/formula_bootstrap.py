from __future__ import annotations

from django.core.signals import request_started
from django.dispatch import receiver
from django.db import transaction


_BOOTSTRAPPED = False


def _add_formula_model_choice():
    from .models import FormField

    model_field = FormField._meta.get_field("field_type")
    choices = list(model_field.choices or [])
    if not any(value == "FORMULA" for value, _ in choices):
        choices.append(("FORMULA", "فرمول"))
        model_field.choices = choices


def _build_context_data(*, instance, submitted_data):
    from .models import FormData, FormField, FormRepeatableGroup
    from .form_services import DynamicFormService

    stored = (
        FormData.objects
        .filter(instance=instance)
        .values_list("data", flat=True)
        .first()
    ) or {}
    data = dict(stored)

    if submitted_data is None:
        return data

    form = instance.workflow.form_definition.filter(is_active=True).first()
    if form is None:
        return data

    editable_top_level_codes = set()
    for section in form.sections.filter(is_active=True):
        for field in section.fields.filter(
            is_active=True,
            repeatable_group__isnull=True,
        ):
            if field.field_type == "FORMULA":
                continue
            if field.code in submitted_data:
                editable_top_level_codes.add(field.code)

    for code in editable_top_level_codes:
        data[code] = submitted_data.get(code, "")

    for group in form.sections.filter(is_active=True).values_list(
        "repeatable_groups__code",
        "repeatable_groups__group_type",
    ):
        group_code, group_type = group
        if not group_code or group_type != FormRepeatableGroup.GroupType.NORMAL:
            continue
        prefix = f"{group_code}_"
        if any(str(key).startswith(prefix) for key in submitted_data.keys()):
            data[group_code] = DynamicFormService._parse_repeatable_data(
                submitted_data=submitted_data,
                group_code=group_code,
            )

    return data


def _inject_formula_context(*, context, calculated_data):
    from .formula_services import FormulaService

    for section in context.get("sections", []):
        for item in section.get("fields", []):
            field = item.get("field")
            if not field or not FormulaService.is_formula(field):
                continue
            value = calculated_data.get(field.code, "")
            item["value"] = value
            item["display_value"] = value
            item["can_edit"] = False
            item["permission_can_edit"] = False

        for group in section.get("repeatable_groups", []):
            group_obj = group.get("group")
            if not group_obj:
                continue

            formula_codes = {
                field_info["field"].code
                for field_info in group.get("fields", [])
                if field_info.get("field")
                and FormulaService.is_formula(field_info["field"])
            }
            if formula_codes:
                for field_info in group.get("fields", []):
                    field = field_info.get("field")
                    if FormulaService.is_formula(field):
                        field_info["can_edit"] = False
                        field_info["permission_can_edit"] = False

                rows = calculated_data.get(group_obj.code, [])
                if not isinstance(rows, list):
                    rows = []

                for row_index, item in enumerate(group.get("items", [])):
                    row_data = rows[row_index] if row_index < len(rows) else {}
                    if not isinstance(row_data, dict):
                        row_data = {}
                    for item_field in item.get("fields", []):
                        field = item_field.get("field")
                        if not FormulaService.is_formula(field):
                            continue
                        value = row_data.get(field.code, "")
                        item_field["value"] = value
                        item_field["display_value"] = value
                        item_field["can_edit"] = False
                        item_field["permission_can_edit"] = False

    context["has_editable_fields"] = any(
        item.get("permission_can_edit", False)
        for section in context.get("sections", [])
        for item in section.get("fields", [])
    ) or any(
        any(
            item_field.get("permission_can_edit", False)
            for item_field in item.get("fields", [])
        )
        for section in context.get("sections", [])
        for group in section.get("repeatable_groups", [])
        for item in group.get("items", [])
    )


def bootstrap_formula_system():
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    _add_formula_model_choice()

    from .formula_admin import FormulaFieldAdminForm
    from .form_services import DynamicFormService
    from .models import FormData, FormField, FormRepeatableGroup
    from .formula_services import FormulaService

    try:
        from . import admin as workflow_admin

        admin_cls = workflow_admin.FormFieldAdmin
        admin_cls.form = FormulaFieldAdminForm

        media_cls = getattr(admin_cls, "Media", None)
        if media_cls is None:
            media_cls = type("Media", (), {})
            admin_cls.Media = media_cls

        current_js = tuple(getattr(media_cls, "js", ()) or ())
        if "workflow/js/formula_admin.js" not in current_js:
            media_cls.js = current_js + ("workflow/js/formula_admin.js",)

        current_css = dict(getattr(media_cls, "css", {}) or {})
        current_all = tuple(current_css.get("all", ()) or ())
        if "workflow/css/formula-admin.css" not in current_all:
            current_css["all"] = current_all + ("workflow/css/formula-admin.css",)
        media_cls.css = current_css

        fieldsets = list(admin_cls.fieldsets or ())
        if not any(
            "formula_builder" in tuple(options.get("fields", ()))
            for _, options in fieldsets
        ):
            fieldsets.append(
                (
                    "تنظیمات فرمول",
                    {
                        "fields": (
                            "formula_builder",
                            "formula_decimal_places",
                        ),
                    },
                )
            )
            admin_cls.fieldsets = tuple(fieldsets)
    except AttributeError:
        # Admin registration is not available yet; the model choice and
        # runtime integration remain usable and a later bootstrap call can
        # finish the admin wiring.
        pass

    if not getattr(DynamicFormService, "_formula_get_patched", False):
        original_get = DynamicFormService.get_form_for_step

        def get_form_with_formulas(
            *,
            instance,
            user,
            edit_mode,
            submitted_data=None,
        ):
            context = original_get(
                instance=instance,
                user=user,
                edit_mode=edit_mode,
                submitted_data=submitted_data,
            )
            form = context.get("form")
            if form is None:
                return context

            formula_fields = list(
                FormField.objects.filter(
                    section__form=form,
                    field_type=FormulaService.FIELD_TYPE,
                    is_active=True,
                )
            )
            if not formula_fields:
                return context

            data = _build_context_data(
                instance=instance,
                submitted_data=submitted_data,
            )
            calculated = FormulaService.calculate_context_data(
                form=form,
                data=data,
            )
            _inject_formula_context(
                context=context,
                calculated_data=calculated,
            )
            return context

        DynamicFormService.get_form_for_step = staticmethod(
            get_form_with_formulas
        )
        DynamicFormService._formula_get_patched = True

    if not getattr(DynamicFormService, "_formula_save_patched", False):
        original_save = DynamicFormService.save_form_for_step

        def save_form_with_formulas(
            *,
            instance,
            user,
            submitted_data,
        ):
            form = instance.workflow.form_definition.filter(is_active=True).first()
            formula_fields = []
            if form is not None:
                formula_fields = list(
                    FormField.objects.filter(
                        section__form=form,
                        field_type=FormulaService.FIELD_TYPE,
                        is_active=True,
                    ).select_related("repeatable_group")
                )

            if formula_fields:
                editable = submitted_data.copy()

                for field in formula_fields:
                    if field.repeatable_group_id is None:
                        editable.pop(field.code, None)
                        continue

                    prefix = f"{field.repeatable_group.code}_"
                    suffix = f"_{field.code}"
                    for key in list(editable.keys()):
                        if str(key).startswith(prefix) and str(key).endswith(suffix):
                            del editable[key]

                submitted_data = editable

            with transaction.atomic():
                result = original_save(
                    instance=instance,
                    user=user,
                    submitted_data=submitted_data,
                )

                if form is None or not formula_fields:
                    return result

                form_data = (
                    FormData.objects
                    .select_for_update()
                    .get(instance=instance)
                )
                calculated = FormulaService.calculate_context_data(
                    form=form,
                    data=form_data.data or {},
                )
                form_data.data = calculated
                form_data.save()

                return result

        DynamicFormService.save_form_for_step = staticmethod(
            save_form_with_formulas
        )
        DynamicFormService._formula_save_patched = True

    _BOOTSTRAPPED = True


@receiver(request_started, weak=False, dispatch_uid="workflow.formula_bootstrap")
def _on_request_started(sender, **kwargs):
    bootstrap_formula_system()
