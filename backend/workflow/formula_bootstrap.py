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

    from .repeatable_row_read_services import RepeatableRowReadService

    reconstructed = RepeatableRowReadService.reconstruct_instance(instance=instance)

    def serialize_group(group):
        rows = []
        for item in group.get("items", []):
            row_data = {field["code"]: field["value"] for field in item.get("fields", [])}
            row_data["_id"] = str(item["row_id"])
            row_data["row_id"] = str(item["row_id"])
            row_data["parent_row_id"] = str(item["parent_row_id"]) if item.get("parent_row_id") is not None else None
            row_data["child_groups"] = [serialize_group(child_group) for child_group in item.get("child_groups", [])]
            rows.append(row_data)
        return {"code": group["code"], "items": rows}

    for group in reconstructed.get("groups", []):
        serialized_group = serialize_group(group)
        data[group["code"]] = serialized_group["items"]

    if submitted_data is None:
        return data

    from .models import FormDefinition
    form = FormDefinition.objects.filter(workflow=instance.workflow, is_active=True).first()
    if form is None:
        return data

    editable_top_level_codes = set()
    for section in form.sections.filter(is_active=True):
        for field in section.fields.filter(is_active=True, repeatable_group__isnull=True):
            if field.field_type == "FORMULA":
                continue
            if field.code in submitted_data:
                editable_top_level_codes.add(field.code)

    for code in editable_top_level_codes:
        data[code] = submitted_data.get(code, "")

    def merge_submitted_group_rows(group, canonical_rows, path_prefix=""):
        import copy

        child_groups = list(group.child_groups.filter(is_active=True).order_by("order", "id"))
        field_codes = set(FormField.objects.filter(repeatable_group=group, is_active=True).values_list("code", flat=True))
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
                values = submitted_data.getlist(key) if hasattr(submitted_data, "getlist") else [submitted_data.get(key, "")]
                row["row_id"] = values[0] if values else ""
                continue
            child = next((child_group for child_group in child_groups if rest.startswith(f"{child_group.code}_")), None)
            if child is not None:
                row["children"].setdefault(child.code, True)
                continue
            if rest not in field_codes:
                continue
            values = submitted_data.getlist(key) if hasattr(submitted_data, "getlist") else [submitted_data.get(key, "")]
            row["fields"][rest] = values if len(values) > 1 else (values[0] if values else "")

        if not parsed:
            return canonical_rows

        canonical_by_id = {str(item.get("row_id") or item.get("_id")): item for item in canonical_rows if item.get("row_id") or item.get("_id")}
        merged_rows = []
        for row_index in sorted(parsed):
            submitted_row = parsed[row_index]
            row_id = str(submitted_row.get("row_id") or "")
            canonical = canonical_by_id.get(row_id)
            if canonical is None and row_index < len(canonical_rows):
                candidate = canonical_rows[row_index]
                if not row_id or row_id == str(candidate.get("row_id") or candidate.get("_id") or ""):
                    canonical = candidate
            merged = copy.deepcopy(canonical) if canonical is not None else {"row_id": row_id or None, "_id": row_id or "", "parent_row_id": None, "child_groups": []}
            merged.update(submitted_row["fields"])
            existing_children = {child.get("code"): child for child in merged.get("child_groups", [])}
            merged_children = []
            for child_group in child_groups:
                if child_group.code not in submitted_row["children"]:
                    child = existing_children.get(child_group.code)
                    if child is not None:
                        merged_children.append(child)
                    continue
                child_canonical = existing_children.get(child_group.code, {}).get("items", [])
                child_merged = merge_submitted_group_rows(child_group, child_canonical, path_prefix=f"{path_prefix}{group.code}_{row_index}_")
                merged_children.append({"code": child_group.code, "items": child_merged})
            merged["child_groups"] = merged_children
            merged_rows.append(merged)
        return merged_rows

    root_groups = (
        FormRepeatableGroup.objects
        .filter(section__form=form, parent_group__isnull=True, is_active=True)
        .order_by("section__order", "order", "id")
    )
    for group in root_groups:
        if any(str(key).startswith(f"{group.code}_") for key in submitted_data.keys()):
            data[group.code] = merge_submitted_group_rows(group, data.get(group.code, []))

    return data


# Remaining bootstrap code is unchanged.
