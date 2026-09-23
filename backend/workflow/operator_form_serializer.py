class OperatorFormSerializer:
    """Serialize workflow form state into the Operator Panel template contract."""

    @staticmethod
    def field(
        *,
        field,
        can_edit,
        permission_can_edit=None,
        value="",
        display_value="",
        choices=None,
        parent_code=None,
        device_types=None,
        device_models=None,
        is_immutable=None,
        is_imei_immutable=None,
    ):
        data = {
            "field": field,
            "can_edit": can_edit,
            "permission_can_edit": (
                can_edit
                if permission_can_edit is None
                else permission_can_edit
            ),
            "value": value,
            "display_value": display_value,
            "choices": choices or [],
            "parent_code": parent_code,
        }

        if device_types is not None:
            data["device_types"] = device_types

        if device_models is not None:
            data["device_models"] = device_models

        if is_immutable is not None:
            data["is_immutable"] = is_immutable

        if is_imei_immutable is not None:
            data["is_imei_immutable"] = is_imei_immutable

        return data

    @staticmethod
    def item(*, fields, row_id="", child_groups=None, **extra):
        """Build a repeatable item presentation context."""

        data = {
            **extra,
            "_id": row_id,
            "row_id": row_id,
            "fields": fields,
        }

        if child_groups is not None:
            data["child_groups"] = child_groups

        return data

    @staticmethod
    def row(*, row_context):
        """Serialize one canonical RowContext into the operator template contract."""
        fields = []

        for field_context in row_context.get("fields", []):
            field = field_context["field"]
            fields.append(
                OperatorFormSerializer.field(
                    field=field,
                    can_edit=field_context["can_edit"],
                    permission_can_edit=field_context.get(
                        "permission_can_edit",
                        False,
                    ),
                    value=field_context.get("value", ""),
                    display_value=field_context.get(
                        "display_value",
                        "",
                    ),
                    choices=field_context.get("choices", []),
                    device_types=field_context.get("device_types"),
                    device_models=field_context.get("device_models"),
                    parent_code=field_context.get("parent_code"),
                    is_immutable=field_context.get("is_immutable"),
                    is_imei_immutable=field_context.get(
                        "is_imei_immutable"
                    ),
                )
            )

        return OperatorFormSerializer.item(
            row_id=row_context.get("row_id", ""),
            row_order=row_context.get("row_order"),
            parent_row_id=row_context.get("parent_row_id"),
            child_groups=row_context.get("child_groups", []),
            device=row_context.get("device"),
            fields=fields,
        )

    @staticmethod
    def group_context(*, group_context):
        """Serialize a GroupContext into the operator template contract."""
        items = [
            OperatorFormSerializer.row(row_context=row)
            for row in group_context.get("items", [])
        ]

        permissions = group_context.get("permissions", {})

        return OperatorFormSerializer.repeatable_group(
            group=group_context["group"],
            fields=group_context.get("fields", []),
            items=items,
            has_editable_fields=group_context.get(
                "has_editable_fields",
                False,
            ),
            can_view=permissions.get("can_view", False),
            can_edit=permissions.get("can_edit", False),
            can_add=permissions.get("can_add", False),
            can_delete=permissions.get("can_delete", False),
        )

    @staticmethod
    def normal_item(
        *,
        row_id="",
        field_contexts,
        values,
        display_values,
        child_groups=None,
    ):
        """Serialize one normal repeatable row for operator presentation."""

        fields = []

        for field_context in field_contexts:
            field = field_context["field"]
            fields.append(
                OperatorFormSerializer.field(
                    field=field,
                    can_edit=field_context["can_edit"],
                    permission_can_edit=field_context.get(
                        "permission_can_edit",
                        False,
                    ),
                    value=values.get(field.code, ""),
                    display_value=display_values.get(
                        field.code,
                        "",
                    ),
                    choices=field_context.get("choices", []),
                    device_types=field_context.get(
                        "device_types"
                    ),
                    device_models=field_context.get(
                        "device_models"
                    ),
                    parent_code=field_context.get("parent_code"),
                )
            )

        return OperatorFormSerializer.item(
            row_id=row_id,
            fields=fields,
            child_groups=child_groups,
        )

    @staticmethod
    def normal_repeatable_group(
        *,
        group,
        group_fields,
        field_contexts_by_item,
        item_contexts,
        has_editable_fields,
        can_view,
        can_edit,
        can_add,
        can_delete,
    ):
        """Serialize a normal repeatable group and its rows."""

        items = []

        for index, item_context in enumerate(item_contexts):
            field_contexts = field_contexts_by_item[index]
            items.append(
                OperatorFormSerializer.normal_item(
                    row_id=item_context.get("row_id", ""),
                    field_contexts=field_contexts,
                    values=item_context.get("values", {}),
                    display_values=item_context.get(
                        "display_values",
                        {},
                    ),
                    child_groups=item_context.get(
                        "child_groups",
                        [],
                    ),
                )
            )

        return OperatorFormSerializer.repeatable_group(
            group=group,
            fields=group_fields,
            items=items,
            has_editable_fields=has_editable_fields,
            can_view=can_view,
            can_edit=can_edit,
            can_add=can_add,
            can_delete=can_delete,
        )

    @staticmethod
    def repeatable_group(
        *,
        group,
        fields,
        items,
        has_editable_fields,
        can_view,
        can_edit,
        can_add,
        can_delete,
    ):
        """Build a repeatable group presentation context."""

        return {
            "group": group,
            "fields": fields,
            "items": items,
            "has_editable_fields": has_editable_fields,
            "can_view": can_view,
            "can_edit": can_edit,
            "can_add": can_add,
            "can_delete": can_delete,
        }
