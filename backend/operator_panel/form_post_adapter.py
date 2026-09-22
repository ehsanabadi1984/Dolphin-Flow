from django.core.exceptions import ValidationError

from workflow.models import FormField, FormRepeatableGroup, RepeatableRow


class OperatorPanelFormPostAdapter:
    """
    Translate the Operator Panel's flat HTML form POST into the structured
    payload expected by FormDraftSaveService.

    This adapter owns HTTP/template naming conventions only. It does not
    perform authorization, validation, diffing, or persistence.
    """

    @classmethod
    def adapt(cls, *, form, submitted_data, instance=None):
        if submitted_data is None:
            raise ValidationError("داده‌های فرم ارسال نشده است.")

        payload = {}

        for section in form.sections.filter(is_active=True).prefetch_related(
            "fields",
            "repeatable_groups__fields",
            "repeatable_groups__child_groups__fields",
        ):
            for field in section.fields.all():
                if (
                    field.is_active
                    and field.repeatable_group_id is None
                    and field.code in submitted_data
                ):
                    payload[field.code] = cls._field_value(
                        submitted_data=submitted_data,
                        key=field.code,
                        field=field,
                    )

            for group in section.repeatable_groups.filter(
                is_active=True,
                parent_group__isnull=True,
            ):
                rows = cls._parse_group(
                    group=group,
                    submitted_data=submitted_data,
                    instance=instance,
                )
                if rows is not None:
                    payload[group.code] = rows

        return payload

    @classmethod
    def _parse_group(cls, *, group, submitted_data, instance):
        prefix = f"{group.code}_"
        items = {}

        for key in submitted_data.keys():
            if not key.startswith(prefix) or key.endswith("__id"):
                continue

            remainder = key[len(prefix):]
            parts = remainder.split("_", 1)

            if len(parts) != 2:
                continue

            index, field_code = parts
            if not index.isdigit():
                continue

            field = group.fields.filter(
                is_active=True,
                code=field_code,
            ).first()
            if field is None:
                continue

            index = int(index)
            items.setdefault(index, {})
            items[index][field_code] = cls._field_value(
                submitted_data=submitted_data,
                key=key,
                field=field,
            )

        id_prefix = f"{group.code}_"
        for key in submitted_data.keys():
            if not (
                key.startswith(id_prefix)
                and key.endswith("__id")
            ):
                continue

            middle = key[len(id_prefix):-len("__id")]
            if not middle.isdigit():
                continue

            index = int(middle)
            row_id = cls._value(submitted_data, key)
            if row_id:
                try:
                    items.setdefault(index, {})["row_id"] = int(row_id)
                except (TypeError, ValueError):
                    items.setdefault(index, {})["row_id"] = None

        instance_device_prefix = f"{group.code}_"
        if instance is not None:
            for key in submitted_data.keys():
                if not (
                    key.startswith(instance_device_prefix)
                    and key.endswith("_instance_device_id")
                ):
                    continue

                middle = key[
                    len(instance_device_prefix):-len("_instance_device_id")
                ]
                if not middle.isdigit():
                    continue

                index = int(middle)
                instance_device_id = cls._value(
                    submitted_data,
                    key,
                )
                if not instance_device_id:
                    continue

                try:
                    row_id = (
                        RepeatableRow.objects
                        .filter(
                            instance=instance,
                            group=group,
                            instance_device_id=int(instance_device_id),
                        )
                        .values_list("pk", flat=True)
                        .first()
                    )
                except (TypeError, ValueError):
                    row_id = None

                if row_id is not None:
                    items.setdefault(index, {})["row_id"] = row_id

        if not items:
            return None

        return [
            items[index]
            for index in sorted(items)
        ]

    @staticmethod
    def _field_value(*, submitted_data, key, field):
        if field.field_type == FormField.FieldType.BOOLEAN:
            values = (
                submitted_data.getlist(key)
                if hasattr(submitted_data, "getlist")
                else [submitted_data.get(key, "")]
            )
            return any(
                str(value).strip().lower() in {"1", "true", "on", "yes"}
                for value in values
            )
        return OperatorPanelFormPostAdapter._value(submitted_data, key)

    @staticmethod
    def _value(submitted_data, key):
        if hasattr(submitted_data, "getlist"):
            values = submitted_data.getlist(key)
            if len(values) > 1:
                return values
            return values[0] if values else ""

        value = submitted_data.get(key, "")
        return value
