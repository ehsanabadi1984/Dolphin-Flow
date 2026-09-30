from __future__ import annotations

from django.core.signals import request_started
from django.dispatch import receiver


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

    # Repeatable groups are now persisted in the canonical
    # RepeatableRow/RepeatableRowValue store, not FormData.data.
    # Formula calculation must reconstruct that state before evaluating
    # row formulas and form-level aggregates.
    from .repeatable_row_read_services import RepeatableRowReadService

    reconstructed = RepeatableRowReadService.reconstruct_instance(
        instance=instance,
    )

    def serialize_group(group):
        rows = []
        for item in group.get("items", []):
            row_data = {
                field["code"]: field["value"]
                for field in item.get("fields", [])
            }
            row_data["_id"] = str(item["row_id"])
            row_data["row_id"] = str(item["row_id"])
            row_data["parent_row_id"] = (
                str(item["parent_row_id"])
                if item.get("parent_row_id") is not None
                else None
            )
            row_data["child_groups"] = [
                serialize_group(child_group)
                for child_group in item.get("child_groups", [])
            ]
            rows.append(row_data)

        return {
            "code": group["code"],
            "items": rows,
        }

    for group in reconstructed.get("groups", []):
        serialized_group = serialize_group(group)
        data[group["code"]] = serialized_group["items"]

    if submitted_data is None:
        return data

    from .models import FormDefinition
    form = (
        FormDefinition.objects
        .filter(workflow=instance.workflow, is_active=True)
        .first()
    )
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

    def merge_submitted_group_rows(group, canonical_rows, path_prefix=""):
        """
        Overlay flat POST keys onto the already reconstructed canonical
        repeatable hierarchy.

        The browser names nested inputs as:
            root_0_child_0_field
        and row identities as:
            root_0__id
            root_0_child_0__id

        Canonical rows remain authoritative for structure and stable IDs;
        submitted values only replace editable field values. This keeps
        unsaved live Formula calculations aligned with the same nested
        hierarchy used by persistence.
        """
        import copy

        child_groups = list(
            group.child_groups.filter(is_active=True).order_by("order", "id")
        )
        field_codes = set(
            FormField.objects.filter(
                repeatable_group=group,
                is_active=True,
            ).values_list("code", flat=True)
        )

        group_prefix = f"{path_prefix}{group.code}_"
        parsed = {}

        for key in submitted_data.keys():
            key = str(key)
            if not key.startswith(group_prefix):
                continue

            remainder = key[len(group_prefix):]
            parts = remainder.split("_", 1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue

            row_index = int(parts[0])
            rest = parts[1]
            row = parsed.setdefault(row_index, {"fields": {}, "children": {}})

            if rest == "_id":
                values = (
                    submitted_data.getlist(key)
                    if hasattr(submitted_data, "getlist")
                    else [submitted_data.get(key, "")]
                )
                row["row_id"] = values[0] if values else ""
                continue

            child = next(
                (
                    child_group
                    for child_group in child_groups
                    if rest.startswith(f"{child_group.code}_")
                ),
                None,
            )
            if child is not None:
                row["children"].setdefault(child.code, True)
                continue

            if rest not in field_codes:
                continue

            values = (
                submitted_data.getlist(key)
                if hasattr(submitted_data, "getlist")
                else [submitted_data.get(key, "")]
            )
            row["fields"][rest] = values if len(values) > 1 else (
                values[0] if values else ""
            )

        if not parsed:
            return canonical_rows

        canonical_by_id = {
            str(item.get("row_id") or item.get("_id")): item
            for item in canonical_rows
            if item.get("row_id") or item.get("_id")
        }

        merged_rows = []
        for row_index in sorted(parsed):
            submitted_row = parsed[row_index]
            row_id = str(submitted_row.get("row_id") or "")
            canonical = canonical_by_id.get(row_id)

            if canonical is None and row_index < len(canonical_rows):
                candidate = canonical_rows[row_index]
                if not row_id or row_id == str(
                    candidate.get("row_id") or candidate.get("_id") or ""
                ):
                    canonical = candidate

            merged = copy.deepcopy(canonical) if canonical is not None else {
                "row_id": row_id or None,
                "_id": row_id or "",
                "parent_row_id": None,
                "child_groups": [],
            }

            merged.update(submitted_row["fields"])

            existing_children = {
                child.get("code"): child
                for child in merged.get("child_groups", [])
            }
            merged_children = []

            for child_group in child_groups:
                if child_group.code not in submitted_row["children"]:
                    child = existing_children.get(child_group.code)
                    if child is not None:
                        merged_children.append(child)
                    continue

                child_canonical = (
                    existing_children.get(child_group.code, {}).get("items", [])
                )
                child_merged = merge_submitted_group_rows(
                    child_group,
                    child_canonical,
                    path_prefix=f"{path_prefix}{group.code}_{row_index}_",
                )
                merged_children.append({
                    "code": child_group.code,
                    "items": child_merged,
                })

            merged["child_groups"] = merged_children
            merged_rows.append(merged)

        return merged_rows

    root_groups = (
        FormRepeatableGroup.objects
        .filter(
            section__form=form,
            parent_group__isnull=True,
            is_active=True,
        )
        .order_by("section__order", "order", "id")
    )
    for group in root_groups:
        if any(
            str(key).startswith(f"{group.code}_")
            for key in submitted_data.keys()
        ):
            data[group.code] = merge_submitted_group_rows(
                group,
                data.get(group.code, []),
            )

    return data


def _inject_formula_context(*, context, calculated_data):
    from .formula_services import FormulaService

    def calculated_group_rows(group_code):
        rows = []

        direct_rows = calculated_data.get(group_code)
        if isinstance(direct_rows, list):
            rows.extend(
                row for row in direct_rows
                if isinstance(row, dict)
            )

        def visit_rows(parent_rows):
            if not isinstance(parent_rows, list):
                return
            for row in parent_rows:
                if not isinstance(row, dict):
                    continue
                for child_group in row.get("child_groups", []) or []:
                    visit_group(child_group)

        def visit_group(group_payload):
            if not isinstance(group_payload, dict):
                return
            if group_payload.get("code") == group_code:
                items = group_payload.get("items", [])
                if isinstance(items, list):
                    rows.extend(
                        row for row in items
                        if isinstance(row, dict)
                    )
                return
            visit_rows(group_payload.get("items", []))

        for payload in calculated_data.values():
            if isinstance(payload, list):
                visit_rows(payload)
            elif isinstance(payload, dict) and payload.get("code"):
                visit_group(payload)

        # The direct and recursive representations can overlap when a group
        # is materialized at the top level and also reachable through its
        # parent row. Keep one authoritative row per stable row_id.
        unique = []
        seen_ids = set()
        for row in rows:
            row_id = str(row.get("row_id") or row.get("_id") or "")
            if row_id and row_id in seen_ids:
                continue
            if row_id:
                seen_ids.add(row_id)
            unique.append(row)
        return unique

    def inject_group(group):
        group_obj = group.get("group")
        if not group_obj:
            return

        formula_fields = [
            field_info.get("field")
            for field_info in group.get("fields", [])
            if FormulaService.is_formula(field_info.get("field"))
        ]
        formula_by_code = {
            field.code: field
            for field in formula_fields
            if field is not None
        }

        for field_info in group.get("fields", []):
            field = field_info.get("field")
            if FormulaService.is_formula(field):
                field_info["can_edit"] = False
                field_info["permission_can_edit"] = False

        if formula_by_code:
            rows_by_id = {
                str(row.get("row_id") or row.get("_id")): row
                for row in calculated_group_rows(group_obj.code)
                if row.get("row_id") is not None or row.get("_id") is not None
            }

            for item in group.get("items", []):
                item_id = str(item.get("row_id") or "")
                row_data = rows_by_id.get(item_id, {})
                for item_field in item.get("fields", []):
                    field = item_field.get("field")
                    if field is None or field.code not in formula_by_code:
                        continue

                    value = row_data.get(field.code, "")
                    item_field["value"] = value
                    item_field["display_value"] = value
                    item_field["can_edit"] = False
                    item_field["permission_can_edit"] = False

            flat_table = group.get("flat_table", {})
            for flat_row in flat_table.get("rows", []):
                path_pairs = list(zip(
                    flat_row.get("path", []),
                    flat_row.get("path_row_ids", []),
                ))
                for cell in flat_row.get("column_cells", []):
                    field = cell.get("field")
                    if field is None or field.code not in formula_by_code:
                        continue

                    source_row_id = next(
                        (
                            row_id
                            for group_code, row_id in path_pairs
                            if group_code == group_obj.code
                        ),
                        None,
                    )
                    if source_row_id is None:
                        continue

                    row_data = rows_by_id.get(str(source_row_id), {})
                    value = row_data.get(field.code, "")
                    cell["value"] = value
                    cell["display_value"] = value
                    cell["can_edit"] = False

        for child_group in group.get("child_groups", []):
            inject_group(child_group)

        for item in group.get("items", []):
            for child_group in item.get("child_groups", []):
                inject_group(child_group)

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
            inject_group(group)

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
            edit_mode=False,
            submitted_data=None,
        ):
            context = original_get(
                instance=instance,
                user=user,
                edit_mode=edit_mode,
                submitted_data=submitted_data,
            )
            if context is None:
                return None
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


    _BOOTSTRAPPED = True


@receiver(request_started, weak=False, dispatch_uid="workflow.formula_bootstrap")
def _on_request_started(sender, **kwargs):
    bootstrap_formula_system()
