from django.core.exceptions import ValidationError
from .permission_context import PermissionContext
from .operator_form_serializer import OperatorFormSerializer
from .repeatable_row_read_services import RepeatableRowReadService

from .instance_device_services import InstanceDeviceService
from .device_services import DeviceService
from .models import (
    DeviceModel,
    FormData,
    WorkflowInstance,
    FormDefinition,
    LookupItem,
    StaticChoiceItem,
    InstanceDevice,
    DeviceIdentifier,
    FormRepeatableGroup,
    DeviceType,
    FormField,
    RepeatableRow,

    
)

class DynamicFormService:
    """
    Build and persist the dynamic form structure
    for a specific workflow instance and step.
    """

    @staticmethod
    def _parse_repeatable_data(
        *,
        submitted_data,
        group_code,
    ):
        """
        Convert flat POST keys of a repeatable group into
        a list of dictionaries.

        Each row may include a ``_id`` key extracted from
        a hidden input named ``{group}_{index}__id``.
        """
        if submitted_data is None:
            return []

        prefix = f"{group_code}_"
        items = {}

        for key in submitted_data.keys():

            if not key.startswith(prefix):
                continue

            remainder = key[len(prefix):]

            parts = remainder.split("_", 1)

            if len(parts) != 2:
                continue

            index, field_code = parts

            if not index.isdigit():
                continue

            index = int(index)

            items.setdefault(
                index,
                {},
            )

            # Support both QueryDict (getlist) and plain dict
            if hasattr(submitted_data, "getlist"):
                values = submitted_data.getlist(key)
            else:
                raw = submitted_data.get(key, "")
                values = (
                    raw if isinstance(raw, list) else [raw]
                )

            if len(values) > 1:
                items[index][field_code] = values
            else:
                items[index][field_code] = (
                    values[0]
                    if values
                    else ""
                )

        # -----------------------------------------------------
        # Extract stable _id from hidden inputs.
        #
        # POST key pattern: {group}_{index}__id
        # (single underscore before "id" to distinguish from
        #  field codes like ``device_id``)
        # -----------------------------------------------------

        id_prefix = f"{group_code}_"
        id_suffix = "__id"

        for key in submitted_data.keys():

            if (
                key.startswith(id_prefix)
                and key.endswith(id_suffix)
            ):

                middle = key[
                    len(id_prefix):-len(id_suffix)
                ]

                if middle.isdigit():
                    idx = int(middle)

                    if idx in items:
                        row_id = (
                            submitted_data.get(key, "").strip()
                        )

                        if row_id:
                            items[idx]["_id"] = row_id

        return [
            items[index]
            for index in sorted(items)
        ]

     
    @staticmethod
    def _get_display_value(
        *,
        field,
        value,
    ):
        """
        Resolve the human-readable representation of a field value.

        SELECT fields map the stored value to its choice label
        (STATIC, LOOKUP or MODEL choice sources). Unresolved values
        fall back to the raw stored value instead of rendering blank.
        Non-SELECT fields simply display their raw value.
        """

        if value in ("", None):
            return ""

        if isinstance(value, list):
            return [
                DynamicFormService._get_display_value(
                    field=field,
                    value=item,
                )
                for item in value
            ]

        if field.field_type != FormField.FieldType.SELECT:
            return str(value)

        choices = DynamicFormService._get_field_choices(
            field
        )

        value_string = str(value)

        for choice in choices:
            if str(choice["value"]) == value_string:
                return choice["label"]

        return str(value)

    @staticmethod
    def _get_lookup_label(*, field, value):
        """
        Return the human-readable label for a LOOKUP field value.

        Returns an empty string when the label cannot be resolved.
        """
        if not value:
            return ""

        if (
            field.field_type != FormField.FieldType.SELECT
            or field.choice_source != FormField.ChoiceSource.LOOKUP
        ):
            return ""

        if not field.choice_lookup_list_id:
            return ""

        value_str = str(value)

        item = (
            LookupItem.objects
            .filter(
                lookup_list_id=field.choice_lookup_list_id,
                value=value_str,
                is_active=True,
            )
            .first()
        )

        return item.label if item else ""

    @staticmethod
    def _get_field_choices(field):
        """
        Build choices for a SELECT FormField based on its choice source.
        Returns a list of dictionaries:
        {
            "value": "...",
            "label": "...",
        }
        """

        if field.field_type != field.FieldType.SELECT:
            return []

        # --------------------------------------------------
        # STATIC
        # --------------------------------------------------

        if field.choice_source == field.ChoiceSource.STATIC:
            if not field.choice_static_set_id:
                return []

            return [
                {
                    "value": item.value,
                    "label": item.label,
                }
                for item in (
                    StaticChoiceItem.objects
                    .filter(
                        choice_set_id=field.choice_static_set_id,
                        is_active=True,
                    )
                    .order_by("order", "id")
                )
            ]

        # --------------------------------------------------
        # LOOKUP
        # --------------------------------------------------

        if field.choice_source == field.ChoiceSource.LOOKUP:
            if not field.choice_lookup_list_id:
                return []

            return [
                {
                    "value": item.value,
                    "label": item.label,
                }
                for item in (
                    LookupItem.objects
                    .filter(
                        lookup_list_id=field.choice_lookup_list_id,
                        is_active=True,
                    )
                    .order_by("order", "id")
                )
            ]

        # --------------------------------------------------
        # MODEL
        # --------------------------------------------------

        if field.choice_source == field.ChoiceSource.MODEL:

            if not field.choice_model_id:
                return []

            model_class = field.choice_model.model_class()

            if not model_class:
                return []

            queryset = model_class.objects.all()

            choices = []

            for obj in queryset:
                value = getattr(
                    obj,
                    field.choice_value_field,
                    "",
                )

                label = getattr(
                    obj,
                    field.choice_label_field,
                    "",
                )

                choices.append(
                    {
                        "value": str(value),
                        "label": str(label),
                    }
                )

            return choices

        return []

    @staticmethod
    def _dependent_choices(field, parent_value):
        """
        Build the option list for a SELECT FormField whose options
        depend on the currently selected value of its parent field
        (``field.choice_parent_field``).

        * No dependency configured  -> full option list (existing
          behavior, also used for the parent fields themselves).
        * Parent value empty/blank  -> [] (nothing valid to choose
          until the operator selects a parent).
        * LOOKUP -> LOOKUP          -> items of the same LookupList
          whose ``parent.value`` equals the selected parent value.
        * MODEL  -> MODEL           -> rows of the child model whose
          ``choice_filter_field`` row matches the parent row selected
          by ``parent_value`` (joined through the parent field's
          ``choice_value_field``).

        An unexpected or misconfigured dependency degrades to []
        instead of raising, so the form can never 500 because of a
        dependency definition.
        """

        if field.field_type != field.FieldType.SELECT:
            return []

        parent_field = field.choice_parent_field

        if parent_field is None:

            # --------------------------------------------------
            # No dependency configured.
            #
            # A LOOKUP field that acts as a parent of another field
            # only offers root items (items without a parent): the
            # hierarchy levels start at the roots. Flat lists have
            # no parented items, so every item is a root and the
            # list is unchanged.
            # --------------------------------------------------

            if (
                field.choice_source == field.ChoiceSource.LOOKUP
                and field.choice_lookup_list_id
                and field.dependent_choice_fields
                .filter(is_active=True)
                .exists()
            ):
                return [
                    {
                        "value": item.value,
                        "label": item.label,
                    }
                    for item in (
                        LookupItem.objects
                        .filter(
                            lookup_list_id=(
                                field.choice_lookup_list_id
                            ),
                            parent__isnull=True,
                            is_active=True,
                        )
                        .order_by("order", "id")
                    )
                ]

            return DynamicFormService._get_field_choices(field)

        if parent_value in (None, ""):
            return []

        # --------------------------------------------------
        # LOOKUP -> LOOKUP
        #
        # Both fields share one LookupList; the child items
        # carry a ``parent`` Link back into the same list.
        # --------------------------------------------------

        if field.choice_source == field.ChoiceSource.LOOKUP:

            if (
                not field.choice_lookup_list_id
                or not parent_field.choice_lookup_list_id
            ):
                return []

            return [
                {
                    "value": item.value,
                    "label": item.label,
                }
                for item in (
                    LookupItem.objects
                    .filter(
                        lookup_list_id=(
                            field.choice_lookup_list_id
                        ),
                        parent__value=str(parent_value),
                        is_active=True,
                    )
                    .order_by("order", "id")
                )
            ]

        # --------------------------------------------------
        # MODEL -> MODEL
        #
        # Child rows are filtered through choice_filter_field,
        # which is expected to reference the parent model.
        # --------------------------------------------------

        if field.choice_source == field.ChoiceSource.MODEL:

            if (
                not field.choice_model_id
                or not field.choice_filter_field
                or not parent_field.choice_model_id
            ):
                return []

            model_class = field.choice_model.model_class()

            if not model_class:
                return []

            try:
                queryset = model_class.objects.filter(
                    **{
                        f"{field.choice_filter_field}__"
                        f"{parent_field.choice_value_field or 'id'}": (
                            parent_value
                        )
                    }
                )

                rows = list(queryset)

            except Exception:
                # A misconfigured dependency (e.g. the filter field
                # is not a relation to the parent model) must never
                # break the form.
                return []

            choices = []

            for obj in rows:
                value = getattr(
                    obj,
                    field.choice_value_field,
                    "",
                )

                label = getattr(
                    obj,
                    field.choice_label_field,
                    "",
                )

                choices.append(
                    {
                        "value": str(value),
                        "label": str(label),
                    }
                )

            return choices

        return []

    @staticmethod
    def _parent_value_for_field(
        field,
        *,
        form_data=None,
        submitted_data=None,
        raw_item=None,
    ):
        """
        Resolve the current value of ``field.choice_parent_field``.

        Dependency semantics are context-dependent:

        * Parent and child are top-level fields (no repeatable group)
          -> the parent value is the single top-level form value.
        * Parent and child belong to the same repeatable group
          -> the parent value is the value inside the same row
          (``raw_item``).
        * Parent is a top-level field while the child lives in a
          repeatable group -> every row shares the top-level value.
        * Any other combination (parent inside a different group) is
          not representable and returns ``(False, "")`` so callers
          fall back to the full option list and skip validation.

        Returns ``(coherent, parent_value)``.
        """

        parent_field = field.choice_parent_field

        if parent_field is None:
            return False, ""

        child_group_id = field.repeatable_group_id
        parent_group_id = parent_field.repeatable_group_id

        if child_group_id and parent_group_id:

            if child_group_id != parent_group_id:
                # Parent in a different group is not representable.
                return False, ""

            if raw_item is None or not isinstance(raw_item, dict):
                return True, ""

            return True, str(
                raw_item.get(parent_field.code, "") or ""
            )

        if child_group_id and not parent_group_id:
            # Top-level parent shared by every row.
            return True, DynamicFormService._top_level_value(
                parent_field.code,
                form_data=form_data,
                submitted_data=submitted_data,
            )

        if not child_group_id and parent_group_id:
            # A single top-level value cannot depend on one row.
            return False, ""

        return True, DynamicFormService._top_level_value(
            parent_field.code,
            form_data=form_data,
            submitted_data=submitted_data,
        )

    @staticmethod
    def _top_level_value(code, *, form_data=None, submitted_data=None):
        """
        Value of a top-level (non repeatable) field.

        On a validation-failure re-render the submitted POST state is
        authoritative; otherwise the persisted FormData is used.
        """

        if submitted_data is not None and code in submitted_data:
            return str(submitted_data.get(code, "") or "")

        if form_data and code in form_data:
            return str(form_data.get(code, "") or "")

        return ""

    @staticmethod
    def _dependency_error(
        field,
        *,
        parent_value,
        child_value,
    ):
        """
        Validate a submitted child SELECT value against the value of
        its parent field.

        Returns a message string when the combination is invalid and
        None when it is acceptable:

        * blank child            -> acceptable (requiredness is
          validated separately).
        * blank parent + value   -> invalid (nothing to hang the
          child value on).
        * child not among the
          options of the parent  -> invalid.
        """

        if child_value is None:
            child_value = ""

        if isinstance(child_value, str):
            child_value = child_value.strip()

        if child_value in ("", None):
            return None

        parent_field = field.choice_parent_field

        if parent_value in (None, ""):
            return (
                f"ابتدا گزینه فیلد «{parent_field.label}» را "
                "انتخاب کنید."
            )

        allowed = DynamicFormService._dependent_choices(
            field,
            str(parent_value),
        )

        allowed_values = {
            str(choice["value"])
            for choice in allowed
        }

        if str(child_value) not in allowed_values:
            return (
                f"گزینه انتخاب‌شده برای فیلد «{field.label}» "
                "با فیلد والد سازگار نیست."
            )

        return None

    @staticmethod
    def _layout_sort_key(layout_item):
        """
        Deterministic sort key for the mixed top-level section layout.

        Primary: ``layout_order`` ascending; items without an explicit
        layout position (NULL) sort last. Secondary: the existing
        ``order`` value, consistent with each model's ``Meta.ordering``.
        ``order`` is unique per section within each type (see the model
        constraints), so a type rank then disambiguates any field/group
        tie; ``pk`` is only a final safety net.
        """

        if layout_item["type"] == "field":
            model = layout_item["item"]["field"]
            type_rank = 0
        else:
            model = layout_item["item"]["group"]
            type_rank = 1

        layout_order = model.layout_order

        return (
            layout_order is None,
            layout_order if layout_order is not None else 0,
            model.order,
            type_rank,
            model.pk,
        )

    @staticmethod
    def _build_nested_group_context(
        *,
        group,
        reconstructed_group,
        permission_context,
        group_can_edit,
        edit_mode,
        is_submitted,
    ):
        """Build a canonical GroupContext for a nested repeatable group."""

        group_permission = permission_context.group(group)
        group_can_view = group_permission.can_view
        # Nested group permissions are evaluated independently. A
        # parent group's edit permission must not grant or revoke the
        # child's own edit permission.
        effective_group_can_edit = group_permission.can_edit
        group_can_add = group_permission.can_add
        group_can_delete = group_permission.can_delete

        if is_submitted:
            effective_group_can_edit = False
            group_can_add = False
            group_can_delete = False

        if not group_can_view:
            return None

        group_fields = []
        group_has_editable_fields = False

        for field in group.fields.filter(is_active=True):
            field_permission = permission_context.field(field)
            if not field_permission.can_view:
                continue

            effective_can_edit = (
                field_permission.can_edit
                and effective_group_can_edit
                and edit_mode
                and not is_submitted
            )

            if (
                field_permission.can_edit
                and effective_group_can_edit
                and not is_submitted
            ):
                group_has_editable_fields = True

            group_fields.append(
                {
                    "field": field,
                    "can_edit": effective_can_edit,
                    "permission_can_edit": field_permission.can_edit,
                    "value": "",
                    "display_value": "",
                    "choices": (
                        DynamicFormService._get_field_choices(field)
                        if field.field_type == field.FieldType.SELECT
                        else []
                    ),
                    "device_types": (
                        DeviceType.objects.filter(is_active=True)
                        if field.system_key
                        == FormField.SystemKey.DEVICE_TYPE
                        else []
                    ),
                    "device_models": (
                        DeviceModel.objects.filter(is_active=True)
                        if field.system_key
                        == FormField.SystemKey.DEVICE_MODEL
                        else []
                    ),
                    "parent_code": (
                        field.choice_parent_field.code
                        if field.choice_parent_field_id
                        else None
                    ),
                }
            )

        rows = []
        for raw_item in reconstructed_group.get("items", []):
            raw_fields = {
                item["code"]: item
                for item in raw_item.get("fields", [])
            }

            row_fields = []
            for base_context in group_fields:
                field = base_context["field"]
                field_context = dict(base_context)
                raw_field = raw_fields.get(field.code, {})
                field_context["value"] = raw_field.get("value", "")
                field_context["display_value"] = raw_field.get(
                    "display_value",
                    DynamicFormService._get_display_value(
                        field=field,
                        value=field_context["value"],
                    ),
                )
                row_fields.append(field_context)

            child_contexts = []
            child_groups_by_code = {
                child["code"]: child
                for child in raw_item.get("child_groups", [])
            }

            for child_group in group.child_groups.filter(
                is_active=True,
            ).order_by("order", "id"):
                child_context = DynamicFormService._build_nested_group_context(
                    group=child_group,
                    reconstructed_group=child_groups_by_code.get(
                        child_group.code,
                        {"items": []},
                    ),
                    permission_context=permission_context,
                    group_can_edit=effective_group_can_edit,
                    edit_mode=edit_mode,
                    is_submitted=is_submitted,
                )
                if child_context is not None:
                    child_contexts.append(child_context)

            rows.append(
                {
                    "row_id": str(raw_item.get("row_id", raw_item.get("_id", ""))),
                    "row_order": raw_item.get("row_order", 0),
                    "parent_row_id": (
                        str(raw_item["parent_row_id"])
                        if raw_item.get("parent_row_id") is not None
                        else None
                    ),
                    "fields": row_fields,
                    "child_groups": child_contexts,
                }
            )

        context = {
            "group": group,
            "fields": group_fields,
            "items": rows,
            "permissions": {
                "can_view": group_can_view,
                "can_edit": effective_group_can_edit,
                "can_add": group_can_add,
                "can_delete": group_can_delete,
            },
            "has_editable_fields": group_has_editable_fields,
            "display_type": group.display_type,
            "group_type": group.group_type,
        }

        if group.display_type == FormRepeatableGroup.DisplayType.TABLE:
            context["flat_table"] = DynamicFormService._build_flat_table_context(
                context,
                permission_context,
                edit_mode,
                is_submitted,
            )

        return context

    @staticmethod
    def _build_flat_table_context(
        group_context,
        permission_context,
        edit_mode,
        is_submitted,
    ):
        """
        Derive flat TABLE rows/columns from the canonical repeatable tree.
        This changes presentation only; RepeatableRow remains the source
        of truth and row identity is never replaced by a visual index.
        """
        columns = []
        seen_columns = set()

        def append_context_columns(context):
            for field_context in context["fields"]:
                key = (
                    context["group"].code,
                    field_context["field"].code,
                )
                if key in seen_columns:
                    continue
                seen_columns.add(key)
                columns.append({
                    "group_code": context["group"].code,
                    "group_label": context["group"].label,
                    "field_context": field_context,
                })

        def build_empty_child_context(child_group, inherited_can_edit):
            group_permission = permission_context.group(child_group)
            if not group_permission.can_view:
                return None

            # Child-group edit permission is independent of the parent-group
            # edit permission. The parent controls its own row actions; a
            # child group must be evaluated from its own access rule.
            can_edit = (
                group_permission.can_edit
                and edit_mode
                and not is_submitted
            )
            can_add = (
                group_permission.can_add
                and not is_submitted
            )
            can_delete = (
                group_permission.can_delete
                and not is_submitted
            )

            fields = []
            for field in child_group.fields.filter(is_active=True):
                field_permission = permission_context.field(field)
                if not field_permission.can_view:
                    continue

                fields.append({
                    "field": field,
                    "can_edit": (
                        field_permission.can_edit
                        and can_edit
                    ),
                    "permission_can_edit": field_permission.can_edit,
                    "value": "",
                    "display_value": "",
                    "choices": (
                        DynamicFormService._get_field_choices(field)
                        if field.field_type == FormField.FieldType.SELECT
                        else []
                    ),
                    "device_types": (
                        DeviceType.objects.filter(is_active=True)
                        if field.system_key == FormField.SystemKey.DEVICE_TYPE
                        else []
                    ),
                    "device_models": (
                        DeviceModel.objects.filter(is_active=True)
                        if field.system_key == FormField.SystemKey.DEVICE_MODEL
                        else []
                    ),
                    "parent_code": (
                        field.choice_parent_field.code
                        if field.choice_parent_field_id
                        else None
                    ),
                })

            return {
                "group": child_group,
                "fields": fields,
                "items": [],
                "permissions": {
                    "can_view": True,
                    "can_edit": can_edit,
                    "can_add": can_add,
                    "can_delete": can_delete,
                },
                "child_groups": [
                    child
                    for child in (
                        build_empty_child_context(
                            nested,
                            can_edit,
                        )
                        for nested in child_group.child_groups.filter(
                            is_active=True,
                        ).order_by("order", "id")
                    )
                    if child is not None
                ],
            }

        append_context_columns(group_context)

        child_context_by_code = {}
        for item in group_context["items"]:
            for child in item["child_groups"]:
                child_context_by_code[child["group"].code] = child

        for child_group in group_context["group"].child_groups.filter(
            is_active=True,
        ).order_by("order", "id"):
            child_context = child_context_by_code.get(
                child_group.code
            )
            if child_context is None:
                child_context = build_empty_child_context(
                    child_group,
                    group_context["permissions"]["can_edit"],
                )

            if child_context is None:
                continue

            append_context_columns(child_context)

            for nested in child_context.get("child_groups", []):
                append_context_columns(nested)

        # Existing populated contexts may contain deeper descendants.
        for item in group_context["items"]:
            for child in item["child_groups"]:
                append_context_columns(child)
                for nested_item in child["items"]:
                    for nested in nested_item["child_groups"]:
                        append_context_columns(nested)

        child_template_contexts = []

        def build_child_template_context(child_group):
            if child_group.display_type != FormRepeatableGroup.DisplayType.TABLE:
                return None

            group_permission = permission_context.group(child_group)
            if not group_permission.can_view:
                return None

            child_context = {
                "group": child_group,
                "can_add": (
                    group_permission.can_add
                    and not is_submitted
                ),
                "can_delete": (
                    group_permission.can_delete
                    and not is_submitted
                ),
                "child_groups": [],
            }

            for nested_group in child_group.child_groups.filter(
                is_active=True,
            ).order_by("order", "id"):
                nested_context = build_child_template_context(
                    nested_group
                )
                if nested_context is not None:
                    child_context["child_groups"].append(
                        nested_context
                    )

            return child_context

        for child_group in group_context["group"].child_groups.filter(
            is_active=True,
        ).order_by("order", "id"):
            child_template_context = build_child_template_context(
                child_group
            )
            if child_template_context is not None:
                child_template_contexts.append(child_template_context)

        rows = []

        def field_cells(item, context, path):
            values = {
                value["field"].code: value
                for value in item["fields"]
            }
            prefix = "".join(
                f"{group_code}_{index}_"
                for group_code, index in path
            )
            cells = []

            for field_context in context["fields"]:
                field = field_context["field"]
                value = values.get(field.code, {})
                cells.append({
                    "group_code": context["group"].code,
                    "field_context": dict(field_context),
                    "field": field,
                    "value": value.get("value", ""),
                    "display_value": value.get("display_value", ""),
                    "can_edit": field_context["can_edit"],
                    "input_prefix": prefix,
                })

            return cells

        def emit(
            item,
            context,
            path,
            ancestor_cells,
        ):
            own_cells = field_cells(item, context, path)
            child_contexts = list(item["child_groups"])
            populated_children = [
                child for child in child_contexts
                if child.get("items")
            ]

            if not populated_children:
                rows.append({
                    "row_id": item["row_id"],
                    "row_group_code": context["group"].code,
                    "parent_row_id": item["parent_row_id"],
                    "path": path,
                    "id_input_name": (
                        "".join(
                            f"{group_code}_{index}_"
                            for group_code, index in path
                        )
                        + "__id"
                    ),
                    "path_key": "".join(
                        f"{group_code}_{index}_"
                        for group_code, index in path
                    ).rstrip("_"),
                    "cells": [
                        dict(
                            cell,
                            show=False,
                            _ancestor_path=tuple(ancestor_path),
                        )
                        for ancestor_path, cells in ancestor_cells
                        for cell in cells
                    ] + [
                        dict(cell, show=True)
                        for cell in own_cells
                    ],
                    "add_children": [
                        {
                            "group_code": child["group"].code,
                            "group_label": child["group"].label,
                            "can_add": child["permissions"]["can_add"],
                            "parent_row_id": item["row_id"],
                        }
                        for child in child_contexts
                    ],
                    "can_delete": context["permissions"]["can_delete"],
                    "delete_group_code": context["group"].code,
                    "delete_group_label": context["group"].label,
                })
                return

            first_row_index = len(rows)

            for child in populated_children:
                for child_index, child_item in enumerate(child["items"]):
                    emit(
                        child_item,
                        child,
                        path + [
                            (child["group"].code, child_index)
                        ],
                        ancestor_cells + [(
                            path,
                            own_cells,
                        )],
                    )

            if first_row_index < len(rows):
                rows[first_row_index]["add_children"] = [
                    {
                        "group_code": child["group"].code,
                        "group_label": child["group"].label,
                        "can_add": child["permissions"]["can_add"],
                        "parent_row_id": item["row_id"],
                    }
                    for child in child_contexts
                ]
        for root_index, item in enumerate(group_context["items"]):
            emit(
                item,
                group_context,
                [(group_context["group"].code, root_index)],
                [],
            )

        first_ancestor_rows = set()

        for row in rows:
            for cell in row["cells"]:
                ancestor_path = cell.pop("_ancestor_path", None)
                if ancestor_path is None:
                    continue

                if ancestor_path not in first_ancestor_rows:
                    cell["show"] = True
                    first_ancestor_rows.add(ancestor_path)

        for row in rows:
            row["column_cells"] = [
                next(
                    (
                        cell for cell in row["cells"]
                        if (
                            cell["group_code"] == column["group_code"]
                            and cell["field"].code
                            == column["field_context"]["field"].code
                        )
                    ),
                    {
                        "group_code": column["group_code"],
                        "field_context": column["field_context"],
                        "field": column["field_context"]["field"],
                        "value": "",
                        "display_value": "",
                        "can_edit": False,
                        "show": False,
                        "input_prefix": "",
                    },
                )
                for column in columns
            ]

        return {
            "columns": columns,
            "rows": rows,
            "child_templates": child_template_contexts,
        }

    @staticmethod
    def get_form_for_step(
        *,
        instance,
        user,
        submitted_data=None,
        edit_mode=False,
    ):
        workflow = instance.workflow
        step = instance.current_step

        if step is None:
            return None
        
        current_step_execution = (
            instance.step_executions
            .filter(
                workflow_step=step,
            )
            .order_by("-performed_at")
            .first()
        )

        step_is_submitted = (
            current_step_execution is not None
            and current_step_execution.is_submitted
        )

        form = (
            FormDefinition.objects.filter(
                workflow=workflow,
                is_active=True,
            )
            .first()
        )

        if form is None:
            return None

        form_data = FormData.objects.filter(
            instance=instance,
        ).first()

        data = form_data.data if form_data else {}

        # Repeatable groups are persisted in RepeatableRow/RepeatableRowValue,
        # not in FormData.data. Build the read-side representation once so
        # normal repeatable groups render from their canonical store on GET.
        reconstructed = RepeatableRowReadService.reconstruct_instance(
            instance=instance,
        )
        repeatable_data = {}
        for reconstructed_group in reconstructed.get("groups", []):
            repeatable_data[reconstructed_group["code"]] = [
                {
                    "_id": str(item["row_id"]),
                    "row_id": str(item["row_id"]),
                    "row_order": item.get("row_order", 0),
                    "parent_row_id": (
                        str(item["parent_row_id"])
                        if item.get("parent_row_id") is not None
                        else None
                    ),
                    **{
                        field["code"]: field["value"]
                        for field in item.get("fields", [])
                    },
                    "fields": item.get("fields", []),
                    "child_groups": item.get("child_groups", []),
                }
                for item in reconstructed_group.get("items", [])
            ]

        current_step_execution = (
            instance.step_executions
            .filter(
                workflow_step=step,
            )
            .order_by("-performed_at")
            .first()
        )

        is_submitted = (
            current_step_execution.is_submitted
            if current_step_execution
            else False
        )

        has_saved_device_data = (
            InstanceDevice.objects
            .filter(
                instance=instance,
                is_active=True,
            )
            .exists()
        )

        has_repeatable_data = any(
            items
            for items in repeatable_data.values()
        )

        has_saved_data = (
            bool(data)
            or has_repeatable_data
            or has_saved_device_data
        )
        permission_context = PermissionContext.build(
            workflow=workflow,
            form=form,
            step=step,
            user=user,
        )

        sections = []

        for section in form.sections.filter(
            is_active=True,
        ):
            fields = []

            # -------------------------------------------------
            # Normal fields
            # -------------------------------------------------

            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            ):
                field_permission = permission_context.field(field)

                can_view = field_permission.can_view
                permission_can_edit = field_permission.can_edit

                if not can_view:
                    continue

                can_edit = (
                    permission_can_edit
                    and edit_mode
                    and not is_submitted
                )

                value = data.get(
                    field.code,
                    "",
                )

                choices = []

                if field.field_type == field.FieldType.SELECT:

                    if field.choice_parent_field_id:

                        coherent, parent_value = (
                            DynamicFormService
                            ._parent_value_for_field(
                                field,
                                form_data=data,
                                submitted_data=submitted_data,
                            )
                        )

                        if coherent:
                            choices = (
                                DynamicFormService
                                ._dependent_choices(
                                    field,
                                    parent_value,
                                )
                            )
                        else:
                            # Unrepresentable parent/child placement:
                            # never lock the operator out of a choice.
                            choices = (
                                DynamicFormService
                                ._get_field_choices(field)
                            )

                    else:

                        choices = (
                            DynamicFormService
                            ._dependent_choices(
                                field,
                                "",
                            )
                        )

                fields.append(
                    OperatorFormSerializer.field(
                        field=field,
                        can_edit=can_edit,
                        permission_can_edit=(
                            permission_can_edit
                            and not is_submitted
                        ),
                        value=value,
                        display_value=DynamicFormService._get_display_value(
                            field=field,
                            value=value,
                        ),
                        choices=choices,
                        parent_code=(
                            field.choice_parent_field.code
                            if field.choice_parent_field_id
                            else None
                        ),
                    )
                )

            # -------------------------------------------------
            # Repeatable groups
            # -------------------------------------------------

            repeatable_groups = []

            for group in section.repeatable_groups.filter(
                is_active=True,
                parent_group__isnull=True,
            ):



                # -------------------------------------------------
                # Repeatable Group Access
                # -------------------------------------------------

                group_permission = permission_context.group(group)

                group_can_view = group_permission.can_view
                group_can_edit = group_permission.can_edit
                group_can_add = group_permission.can_add
                group_can_delete = group_permission.can_delete

                # Submitted step is always read-only.
                if is_submitted:
                    group_can_edit = False
                    group_can_add = False
                    group_can_delete = False

                # User has no permission to see this group.
                #----------Debug-----------
                #-------End-Debug----------
                if not group_can_view:
                    continue

                group_fields = []
                group_has_editable_fields = False

                for field in group.fields.filter(
                    is_active=True,
                ):
                    field_permission = permission_context.field(field)

                    can_view = field_permission.can_view
                    can_edit = field_permission.can_edit

                    #---------------Debug-------------
                    #------------End-Debug------------

                    if not can_view:
                        continue

                    effective_can_edit = (
                        can_view
                        and can_edit
                        and group_can_edit
                        and edit_mode
                        and not is_submitted
                    )
                    if (
                        can_view
                        and can_edit
                        and group_can_edit
                        and not is_submitted
                    ):
                        group_has_editable_fields = True

                    field_data = {
                        "field": field,
                        "can_edit": effective_can_edit,
                        "choices": (
                            DynamicFormService._dependent_choices(
                                field,
                                "",
                            )
                            if field.field_type == field.FieldType.SELECT
                            else []
                        ),
                        "device_types": (
                            DeviceType.objects.filter(
                                is_active=True,
                            )
                            if field.system_key == FormField.SystemKey.DEVICE_TYPE
                            else []
                        ),
                        "device_models": (
                            DeviceModel.objects.filter(
                                is_active=True,
                            )
                            if field.system_key == FormField.SystemKey.DEVICE_MODEL
                            else []
                        ),
                        "parent_code": (
                            field.choice_parent_field.code
                            if field.choice_parent_field_id
                            else None
                        ),
                    }

                    group_fields.append(field_data)
#------------------------Debug-----------------------
# --------------------End-Debug----------------------
                # -------------------------------------------------
                # A DEVICE group is a valid workflow component even
                # when it has no visible FormFields: its rows come
                # from InstanceDevice and its semantics come from
                # group_type=DEVICE. Only NORMAL groups require at
                # least one visible field to be rendered.
                # -------------------------------------------------

                if (
                    not group_fields
                    and group.group_type
                    != FormRepeatableGroup.GroupType.DEVICE
                ):
                    continue

                # Saved repeatable items.
                #
                # Device groups use InstanceDevice
                # as their source of truth.
                #

                if group.group_type == FormRepeatableGroup.GroupType.DEVICE:

                    # =========================================================
                    # DEVICE REPEATABLE GROUP
                    # =========================================================
                    #
                    # Source of truth:
                    #
                    #     InstanceDevice
                    #
                    # A device can be in one of two states:
                    #
                    # 1. Draft device
                    #    instance_device.device is None
                    #
                    #    IMEI / Device Type / Device Model are editable
                    #    according to FieldAccess and edit_mode.
                    #
                    # 2. Existing device
                    #    instance_device.device is not None
                    #
                    #    IMEI / Device Type / Device Model are immutable.
                    #    Other fields remain editable according to permissions.
                    #
                    # =========================================================

                    instance_devices = (
                        InstanceDeviceService.get_devices_for_instance(
                            instance=instance,
                        )
                    )

                    # DEVICE row identity is owned by RepeatableRow.
                    # InstanceDevice is only the device-assignment identity.
                    device_row_ids = {
                        row.instance_device_id: row.pk
                        for row in (
                            RepeatableRow.objects
                            .filter(
                                instance=instance,
                                group=group,
                                instance_device__in=instance_devices,
                            )
                            .only("pk", "instance_device_id")
                        )
                    }

                    # ---------------------------------------------------------
                    # POST data has priority only when validation failed.
                    #
                    # In normal GET requests, InstanceDevice remains the source
                    # of truth.
                    # ---------------------------------------------------------

                    submitted_device_items = []

                    if submitted_data is not None:
                        submitted_device_items = (
                            DynamicFormService._parse_repeatable_data(
                                submitted_data=submitted_data,
                                group_code=group.code,
                            )
                        )

                    items = []

                    # =========================================================
                    # FIELD HELPERS
                    # =========================================================

                    def get_field_info(field):
                        """
                        Return effective field permissions and metadata.
                        """

                        field_permission = permission_context.field(field)

                        can_view = field_permission.can_view
                        permission_can_edit = field_permission.can_edit

                        effective_can_edit = (
                            can_view
                            and permission_can_edit
                            and edit_mode
                            and not is_submitted
                        )

                        return {
                            "can_view": can_view,
                            "can_edit": effective_can_edit,
                            "permission_can_edit": permission_can_edit,
                        }

                    # =========================================================
                    # SYSTEM FIELD MAP
                    # =========================================================

                    field_map = {}

                    for field in group.fields.filter(
                        is_active=True,
                    ):

                        field_info = get_field_info(field)

                        if not field_info["can_view"]:
                            continue

                        if field.system_key != FormField.SystemKey.NONE:
                            field_map[field.system_key] = field

                    imei_field = field_map.get(
                        FormField.SystemKey.IMEI
                    )

                    device_type_field = field_map.get(
                        FormField.SystemKey.DEVICE_TYPE
                    )

                    device_model_field = field_map.get(
                        FormField.SystemKey.DEVICE_MODEL
                    )

                    # =========================================================
                    # BUILD GROUP FIELDS
                    # =========================================================

                    group_fields = []

                    for field in group.fields.filter(
                        is_active=True,
                    ):

                        field_info = get_field_info(field)

                        if not field_info["can_view"]:
                            continue

                        group_fields.append(
                            {
                                "field": field,
                                "can_edit": field_info["can_edit"],
                                "permission_can_edit": field_info[
                                    "permission_can_edit"
                                ],
                                "choices": (
                                    DynamicFormService._get_field_choices(field)
                                    if field.field_type == field.FieldType.SELECT
                                    else []
                                ),
                                "device_types": (
                                    DeviceType.objects.filter(
                                        is_active=True,
                                    )
                                    if field.system_key
                                    == FormField.SystemKey.DEVICE_TYPE
                                    else []
                                ),
                                "device_models": (
                                    DeviceModel.objects.filter(
                                        is_active=True,
                                    )
                                    if field.system_key
                                    == FormField.SystemKey.DEVICE_MODEL
                                    else []
                                ),
                            }
                        )

                    # -------------------------------------------------
                    # A DEVICE group remains renderable without fields.
                    # -------------------------------------------------

                    group_has_editable_fields = (
                        any(
                            field_info["permission_can_edit"]
                            for field_info in group_fields
                        )
                        or (
                            group.group_type
                            == FormRepeatableGroup.GroupType.DEVICE
                            and group_can_add
                        )
                    )

                    # =========================================================
                    # CASE 1
                    # =========================================================
                    #
                    # Validation failed and POST contains device data.
                    #
                    # Render the submitted values so the operator does not lose
                    # what was entered.
                    #
                    # =========================================================

                    if submitted_device_items:

                        for submitted_item in submitted_device_items:

                            if not isinstance(
                                submitted_item,
                                dict,
                            ):
                                continue

                            # -------------------------------------------------
                            # Resolve submitted IDs
                            # -------------------------------------------------

                            device_type = None
                            device_model = None

                            submitted_device_type_id = (
                                submitted_item.get(
                                    "device_type"
                                )
                            )

                            submitted_device_model_id = (
                                submitted_item.get(
                                    "device_model_id"
                                )
                            )

                            if submitted_device_type_id:

                                device_type = (
                                    DeviceType.objects
                                    .filter(
                                        pk=submitted_device_type_id,
                                        is_active=True,
                                    )
                                    .first()
                                )

                            if submitted_device_model_id:

                                device_model = (
                                    DeviceModel.objects
                                    .filter(
                                        pk=submitted_device_model_id,
                                        is_active=True,
                                    )
                                    .first()
                                )

                            # -------------------------------------------------
                            # Existing device detection
                            # -------------------------------------------------

                            instance_device_id = (
                                submitted_item.get(
                                    "instance_device_id"
                                )
                            )

                            existing_instance_device = None

                            if instance_device_id:

                                existing_instance_device = (
                                    InstanceDevice.objects
                                    .filter(
                                        pk=instance_device_id,
                                        instance=instance,
                                        is_active=True,
                                    )
                                    .select_related(
                                        "device",
                                        "device__device_model",
                                        "device__device_model__device_type",
                                    )
                                    .first()
                                )

                            is_existing_device = (
                                existing_instance_device is not None
                                and existing_instance_device.device_id
                                is not None
                            )

                            # -------------------------------------------------
                            # Existing device:
                            #
                            # Always use the real Device identity.
                            # POST cannot change it.
                            # -------------------------------------------------

                            if is_existing_device:

                                real_device = (
                                    existing_instance_device.device
                                )

                                real_device_model = (
                                    real_device.device_model
                                )

                                real_device_type = (
                                    real_device_model.device_type
                                )

                                device_type = real_device_type
                                device_model = real_device_model

                                imei = ""

                                for identifier in (
                                    real_device.identifiers.all()
                                ):

                                    if (
                                        identifier.identifier_type
                                        == DeviceIdentifier.IdentifierType.IMEI
                                    ):
                                        imei = identifier.value
                                        break

                            else:

                                imei = str(
                                    submitted_item.get(
                                        "imei",
                                        "",
                                    )
                                ).strip()

                            # -------------------------------------------------
                            # Build fields
                            # -------------------------------------------------

                            item_fields = []

                            for field_info in group_fields:

                                field = field_info["field"]

                                value = ""
                                display_value = ""

                                # ---------------------------------------------
                                # IMEI
                                # ---------------------------------------------

                                if (
                                    field.system_key
                                    == FormField.SystemKey.IMEI
                                ):

                                    value = imei
                                    display_value = imei

                                # ---------------------------------------------
                                # DEVICE TYPE
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DEVICE_TYPE
                                ):

                                    value = (
                                        device_type.pk
                                        if device_type
                                        else ""
                                    )

                                    display_value = (
                                        device_type.name
                                        if device_type
                                        else ""
                                    )

                                # ---------------------------------------------
                                # DEVICE MODEL
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DEVICE_MODEL
                                ):

                                    value = (
                                        device_model.pk
                                        if device_model
                                        else ""
                                    )

                                    display_value = (
                                        str(device_model)
                                        if device_model
                                        else ""
                                    )

                                # ---------------------------------------------
                                # REPORTED PROBLEM
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.REPORTED_PROBLEM
                                ):

                                    value = submitted_item.get(
                                        "problem",
                                        "",
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # DESCRIPTION
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DESCRIPTION
                                ):

                                    value = submitted_item.get(
                                        "description",
                                        "",
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # WARRANTY STATUS
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.WARRANTY_STATUS
                                ):

                                    value = submitted_item.get(
                                        "warranty_status",
                                        "",
                                    )

                                    display_value = (
                                        DynamicFormService._get_display_value(
                                            field=field,
                                            value=value,
                                        )
                                    )

                                # ---------------------------------------------
                                # STATUS
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.STATUS
                                ):

                                    value = submitted_item.get(
                                        "status",
                                        "",
                                    )

                                    display_value = (
                                        DynamicFormService._get_display_value(
                                            field=field,
                                            value=value,
                                        )
                                    )

                                else:

                                    value = submitted_item.get(
                                        field.code,
                                        "",
                                    )

                                    display_value = value

                                # -------------------------------------------------
                                # Existing Device Identity Fields
                                #
                                # IMEI / TYPE / MODEL are immutable.
                                # -------------------------------------------------

                                field_can_edit = field_info[
                                    "can_edit"
                                ]

                                if is_existing_device and (
                                    field.system_key
                                    in {
                                        FormField.SystemKey.IMEI,
                                        FormField.SystemKey.DEVICE_TYPE,
                                        FormField.SystemKey.DEVICE_MODEL,
                                    }
                                ):
                                    field_can_edit = False

                                # -------------------------------------------------
                                # Device models filtered by type
                                # -------------------------------------------------

                                device_models = (
                                    DeviceModel.objects.filter(
                                        device_type=device_type,
                                        is_active=True,
                                    )
                                    .order_by(
                                        "brand",
                                        "name",
                                    )
                                    if (
                                        field.system_key
                                        == FormField.SystemKey.DEVICE_MODEL
                                        and device_type
                                    )
                                    else field_info.get(
                                        "device_models",
                                        [],
                                    )
                                )

                                item_fields.append(
                                    {
                                        "field": field,
                                        "can_edit": field_can_edit,
                                        "is_immutable": (
                                            field.system_key
                                            in {
                                                FormField.SystemKey.IMEI,
                                                FormField.SystemKey.DEVICE_TYPE,
                                                FormField.SystemKey.DEVICE_MODEL,
                                            }
                                        ),
                                        "is_imei_immutable": (
                                            field.system_key
                                            == FormField.SystemKey.IMEI
                                        ),
                                        "value": value,
                                        "display_value": display_value,
                                        "choices": field_info.get(
                                            "choices",
                                            [],
                                        ),
                                        "device_types": field_info.get(
                                            "device_types",
                                            [],
                                        ),
                                        "device_models": device_models,
                                    }
                                )

                            # -------------------------------------------------
                            # Build item
                            # -------------------------------------------------

                            item = {
                                "instance_device_id": (
                                    instance_device_id or ""
                                ),
                                "device_id": (
                                    existing_instance_device.device_id
                                    if is_existing_device
                                    else ""
                                ),
                                "is_existing_device": (
                                    is_existing_device
                                ),
                                "device_model_id": (
                                    device_model.pk
                                    if device_model
                                    else ""
                                ),
                                "device_type": (
                                    device_type.name
                                    if device_type
                                    else ""
                                ),
                                "device_model": (
                                    str(device_model)
                                    if device_model
                                    else ""
                                ),
                                "reported_problem": submitted_item.get(
                                    "problem",
                                    "",
                                ),
                                "description": submitted_item.get(
                                    "description",
                                    "",
                                ),
                                "warranty_status": submitted_item.get(
                                    "warranty_status",
                                    "",
                                ),
                                "status": submitted_item.get(
                                    "status",
                                    "",
                                ),
                                "identifiers": [
                                    {
                                        "type": "IMEI",
                                        "value": imei,
                                    }
                                ],
                                "fields": item_fields,
                            }

                            # -------------------------------------------------
                            # History availability
                            #
                            # Template can use this flag for the "سوابق"
                            # button.
                            # -------------------------------------------------

                            item["has_history"] = (
                                is_existing_device
                            )

                            items.append(item)

                    # =========================================================
                    # CASE 2
                    # =========================================================
                    #
                    # Normal GET:
                    #
                    # Load devices from InstanceDevice.
                    #
                    # =========================================================

                    else:

                        for instance_device in instance_devices:

                            # -------------------------------------------------
                            # Determine device state
                            # -------------------------------------------------

                            is_existing_device = (
                                instance_device.device_id
                                is not None
                            )

                            # -------------------------------------------------
                            # DRAFT DEVICE
                            # -------------------------------------------------

                            if not is_existing_device:

                                draft_model = (
                                    instance_device.draft_device_model
                                )

                                draft_type = (
                                    draft_model.device_type
                                    if draft_model
                                    else (
                                        instance_device
                                        .draft_device_type
                                    )
                                )

                                imei = (
                                    instance_device.draft_imei
                                    or ""
                                )

                                device_type = draft_type
                                device_model = draft_model

                            # -------------------------------------------------
                            # EXISTING DEVICE
                            # -------------------------------------------------

                            else:

                                device = (
                                    instance_device.device
                                )

                                device_model = (
                                    device.device_model
                                )

                                device_type = (
                                    device_model.device_type
                                    if device_model
                                    else None
                                )

                                imei = ""

                                for identifier in (
                                    device.identifiers.all()
                                ):

                                    if (
                                        identifier.identifier_type
                                        == DeviceIdentifier.IdentifierType.IMEI
                                    ):

                                        imei = identifier.value
                                        break

                            # -------------------------------------------------
                            # Device models for selected type
                            # -------------------------------------------------

                            device_models_for_type = (
                                DeviceModel.objects
                                .filter(
                                    device_type=device_type,
                                    is_active=True,
                                )
                                .order_by(
                                    "brand",
                                    "name",
                                )
                                if device_type
                                else DeviceModel.objects.none()
                            )

                            # -------------------------------------------------
                            # Build fields
                            # -------------------------------------------------

                            item_fields = []

                            for field_info in group_fields:

                                field = field_info["field"]

                                value = ""
                                display_value = ""

                                # ---------------------------------------------
                                # IMEI
                                # ---------------------------------------------

                                if (
                                    field.system_key
                                    == FormField.SystemKey.IMEI
                                ):

                                    value = imei
                                    display_value = imei

                                # ---------------------------------------------
                                # DEVICE TYPE
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DEVICE_TYPE
                                ):

                                    value = (
                                        device_type.pk
                                        if device_type
                                        else ""
                                    )

                                    display_value = (
                                        device_type.name
                                        if device_type
                                        else ""
                                    )

                                # ---------------------------------------------
                                # DEVICE MODEL
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DEVICE_MODEL
                                ):

                                    value = (
                                        device_model.pk
                                        if device_model
                                        else ""
                                    )

                                    display_value = (
                                        str(device_model)
                                        if device_model
                                        else ""
                                    )

                                # ---------------------------------------------
                                # REPORTED PROBLEM
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.REPORTED_PROBLEM
                                ):

                                    value = (
                                        instance_device.reported_problem
                                        or ""
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # DESCRIPTION
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DESCRIPTION
                                ):

                                    value = (
                                        instance_device.description
                                        or ""
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # WARRANTY STATUS
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.WARRANTY_STATUS
                                ):

                                    value = (
                                        instance_device.warranty_status
                                        or ""
                                    )

                                    display_value = (
                                        DynamicFormService._get_display_value(
                                            field=field,
                                            value=value,
                                        )
                                    )

                                # ---------------------------------------------
                                # STATUS
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.STATUS
                                ):

                                    value = (
                                        instance_device.status
                                        or ""
                                    )

                                    display_value = (
                                        DynamicFormService._get_display_value(
                                            field=field,
                                            value=value,
                                        )
                                    )

                                else:

                                    value = ""

                                    display_value = ""

                                # -------------------------------------------------
                                # Identity fields
                                #
                                # Existing Device:
                                #     IMEI / TYPE / MODEL => immutable
                                #
                                # Draft Device:
                                #     according to FieldAccess + edit_mode
                                # -------------------------------------------------

                                field_can_edit = field_info[
                                    "can_edit"
                                ]

                                is_identity_field = (
                                    field.system_key
                                    in {
                                        FormField.SystemKey.IMEI,
                                        FormField.SystemKey.DEVICE_TYPE,
                                        FormField.SystemKey.DEVICE_MODEL,
                                    }
                                )

                                if (
                                    is_existing_device
                                    and is_identity_field
                                ):
                                    field_can_edit = False

                                # -------------------------------------------------
                                # Device model list
                                # -------------------------------------------------

                                device_models = (
                                    device_models_for_type
                                    if (
                                        field.system_key
                                        == FormField.SystemKey.DEVICE_MODEL
                                    )
                                    else field_info.get(
                                        "device_models",
                                        [],
                                    )
                                )

                                item_fields.append(
                                    {
                                        "field": field,
                                        "can_edit": field_can_edit,
                                        "is_immutable": (
                                            is_identity_field
                                        ),
                                        "is_imei_immutable": (
                                            field.system_key
                                            == FormField.SystemKey.IMEI
                                        ),
                                        "value": value,
                                        "display_value": display_value,
                                        "choices": field_info.get(
                                            "choices",
                                            [],
                                        ),
                                        "device_types": field_info.get(
                                            "device_types",
                                            [],
                                        ),
                                        "device_models": device_models,
                                    }
                                )

                            # -------------------------------------------------
                            # Build device item
                            # -------------------------------------------------

                            items.append(
                                {
                                    "row_id": str(
                                        device_row_ids.get(
                                            instance_device.pk,
                                            "",
                                        )
                                    ),
                                    "row_order": len(items),
                                    "parent_row_id": None,
                                    "fields": item_fields,
                                    "device": {
                                        "instance_device": instance_device,
                                        "device": instance_device.device,
                                        "device_id": (
                                            instance_device.device_id or ""
                                        ),
                                        "instance_device_id": instance_device.pk,
                                        "device_type": device_type,
                                        "device_model": device_model,
                                        "identifiers": [
                                            {
                                                "type": identifier.identifier_type,
                                                "value": identifier.value,
                                            }
                                            for identifier in (
                                                instance_device.device.identifiers.all()
                                                if instance_device.device
                                                else []
                                            )
                                        ] or [
                                            {
                                                "type": "IMEI",
                                                "value": imei,
                                            }
                                        ],
                                        "imei": imei,
                                        "warranty_status": (
                                            instance_device.warranty_status or ""
                                        ),
                                        "status": instance_device.status or "",
                                        "reported_problem": (
                                            instance_device.reported_problem or ""
                                        ),
                                        "description": (
                                            instance_device.description or ""
                                        ),
                                        "is_existing_device": is_existing_device,
                                        "has_history": is_existing_device,
                                    },
                                }
                            )

                    group_context = {
                        "group": group,
                        "fields": group_fields,
                        "items": items,
                        "permissions": {
                            "can_view": group_can_view,
                            "can_edit": group_can_edit,
                            "can_add": group_can_add,
                            "can_delete": group_can_delete,
                        },
                        "has_editable_fields": group_has_editable_fields,
                        "display_type": group.display_type,
                        "group_type": group.group_type,
                    }
                    group_context = OperatorFormSerializer.group_context(
                        group_context=group_context,
                    )

                else:
                    # -------------------------------------------------
                    # NORMAL REPEATABLE GROUP
                    #
                    # DynamicFormService prepares authoritative values,
                    # permissions, choices and nested child contexts.
                    # OperatorFormSerializer owns the presentation shape.
                    # -------------------------------------------------

                    if submitted_data is not None:
                        raw_items = (
                            DynamicFormService._parse_repeatable_data(
                                submitted_data=submitted_data,
                                group_code=group.code,
                            )
                        )
                    else:
                        raw_items = repeatable_data.get(
                            group.code,
                            [],
                        )

                        if not isinstance(raw_items, list):
                            raw_items = []

                    rows = []

                    for row_index, raw_item in enumerate(raw_items):
                        if not isinstance(raw_item, dict):
                            continue

                        row_field_contexts = [
                            dict(field_context)
                            for field_context in group_fields
                        ]

                        for field_context in row_field_contexts:
                            field = field_context["field"]
                            value = raw_item.get(field.code, "")
                            field_context["value"] = value

                            if field.field_type == field.FieldType.SELECT:
                                if field.choice_parent_field_id:
                                    coherent, parent_value = (
                                        DynamicFormService._parent_value_for_field(
                                            field,
                                            form_data=data,
                                            submitted_data=submitted_data,
                                            raw_item=raw_item,
                                        )
                                    )
                                    if coherent:
                                        field_context["choices"] = (
                                            DynamicFormService._dependent_choices(
                                                field,
                                                parent_value,
                                            )
                                        )
                                    else:
                                        field_context["choices"] = (
                                            DynamicFormService._get_field_choices(
                                                field
                                            )
                                        )
                                else:
                                    field_context["choices"] = (
                                        DynamicFormService._dependent_choices(
                                            field,
                                            "",
                                        )
                                    )

                            field_context["display_value"] = (
                                DynamicFormService._get_display_value(
                                    field=field,
                                    value=value,
                                )
                            )

                        child_contexts = []
                        child_groups_by_code = {
                            child["code"]: child
                            for child in raw_item.get("child_groups", [])
                        }

                        for child_group in group.child_groups.filter(
                            is_active=True,
                        ).order_by("order", "id"):
                            child_context = DynamicFormService._build_nested_group_context(
                                group=child_group,
                                reconstructed_group=child_groups_by_code.get(
                                    child_group.code,
                                    {"items": []},
                                ),
                                permission_context=permission_context,
                                group_can_edit=group_can_edit,
                                edit_mode=edit_mode,
                                is_submitted=is_submitted,
                            )
                            if child_context is not None:
                                child_contexts.append(child_context)

                        rows.append(
                            {
                                "row_id": str(
                                    raw_item.get(
                                        "row_id",
                                        raw_item.get("_id", ""),
                                    )
                                ),
                                "row_order": raw_item.get("row_order", row_index),
                                "parent_row_id": (
                                    str(raw_item["parent_row_id"])
                                    if raw_item.get("parent_row_id") is not None
                                    else None
                                ),
                                "fields": row_field_contexts,
                                "child_groups": child_contexts,
                            }
                        )

                    group_context = {
                        "group": group,
                        "fields": group_fields,
                        "items": rows,
                        "permissions": {
                            "can_view": group_can_view,
                            "can_edit": group_can_edit,
                            "can_add": group_can_add,
                            "can_delete": group_can_delete,
                        },
                        "has_editable_fields": group_has_editable_fields,
                        "display_type": group.display_type,
                        "group_type": group.group_type,
                    }

                    if group.display_type == FormRepeatableGroup.DisplayType.TABLE:
                        group_context["flat_table"] = (
                            DynamicFormService._build_flat_table_context(
                                group_context,
                                permission_context,
                                edit_mode,
                                is_submitted,
                            )
                        )

                    group_context = OperatorFormSerializer.group_context(
                        group_context=group_context,
                    )

                repeatable_groups.append(group_context)

            # -------------------------------------------------
            # Mixed top-level layout (display-only)
            #
            # Combines the visible top-level fields (repeatable_group
            # IS NULL) and the visible repeatable groups into a single
            # presentation collection ordered by ``layout_order``.
            # Nested group fields are already excluded because they
            # never enter ``fields``. Existing ``fields`` and
            # ``repeatable_groups`` collections are left untouched.
            # -------------------------------------------------

            layout_items = [
                {"type": "field", "item": field_data}
                for field_data in fields
            ]

            layout_items.extend(
                {"type": "group", "item": group_data}
                for group_data in repeatable_groups
            )

            layout_items.sort(
                key=DynamicFormService._layout_sort_key,
            )

            # -------------------------------------------------
            # Add section only when it contains something
            # -------------------------------------------------
            if fields or repeatable_groups:
                section_context = {
                    "section": section,
                    "fields": fields,
                    "repeatable_groups": repeatable_groups,
                    "layout_items": layout_items,
                }
                sections.append(
                    OperatorFormSerializer.section(
                        section_context=section_context,
                    )
                )

        has_editable_fields = any(
            item["permission_can_edit"]
            for section in sections
            for item in section["fields"]
        ) or any(
            group["has_editable_fields"]
            for section in sections
            for group in section["repeatable_groups"]
        )

        can_reenter_edit_mode = (
            not step_is_submitted
            and has_editable_fields
        )

        return {
            "form": form,
            "sections": sections,
            "has_saved_data": has_saved_data,
            "is_submitted": step_is_submitted,
            "has_editable_fields": has_editable_fields,
            "can_reenter_edit_mode": can_reenter_edit_mode,
        }