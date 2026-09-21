from django.core.exceptions import ValidationError

from .models import (
    DeviceIdentifier,
    FormField,
    FormRepeatableGroup,
    InstanceDevice,
    RepeatableRow,
    WorkflowInstance,
)


class RepeatableRowReadService:
    """
    Read/reconstruction layer for the new RepeatableRow domain.

    This service is deliberately independent from DynamicFormService and
    does not read or write FormData.data. It reconstructs the canonical
    row structure from RepeatableRow + RepeatableRowValue and resolves
    DEVICE system fields from InstanceDevice.
    """

    @staticmethod
    def get_rows(*, instance, group, parent_row=None):
        if instance is None or instance.pk is None:
            raise ValidationError("WorkflowInstance معتبر نیست.")

        if group is None or group.pk is None:
            raise ValidationError("RepeatableGroup معتبر نیست.")

        if group.section.form.workflow_id != instance.workflow_id:
            raise ValidationError(
                "گروه تکرارشونده و WorkflowInstance باید متعلق به یک Workflow باشند."
            )

        if parent_row is not None and parent_row.instance_id != instance.pk:
            raise ValidationError(
                "Row والد باید متعلق به همان WorkflowInstance باشد."
            )

        return (
            RepeatableRow.objects
            .filter(
                instance=instance,
                group=group,
                parent_row=parent_row,
            )
            .select_related(
                "group",
                "instance_device",
                "instance_device__device",
                "instance_device__device__device_model",
                "instance_device__device__device_model__device_type",
                "instance_device__draft_device_model",
                "instance_device__draft_device_type",
            )
            .prefetch_related(
                "instance_device__device__identifiers",
                "values__field",
                "values__static_choice_item",
                "values__lookup_item",
            )
            .order_by("row_order", "id")
        )

    @staticmethod
    def reconstruct_row(*, row):
        if row is None or row.pk is None:
            raise ValidationError("RepeatableRow معتبر نیست.")

        row = (
            RepeatableRow.objects
            .filter(pk=row.pk)
            .select_related(
                "instance",
                "group",
                "instance_device",
                "instance_device__device",
                "instance_device__device__device_model",
                "instance_device__device__device_model__device_type",
                "instance_device__draft_device_model",
                "instance_device__draft_device_type",
            )
            .prefetch_related(
                "instance_device__device__identifiers",
                "values__field",
                "values__static_choice_item",
                "values__lookup_item",
            )
            .first()
        )

        if row is None:
            raise ValidationError("RepeatableRow پیدا نشد.")

        values_by_field_id = {
            item.field_id: item
            for item in row.values.all()
        }

        fields = []

        for field in row.group.fields.filter(
            is_active=True,
        ).order_by("order", "id"):
            if field.system_key != FormField.SystemKey.NONE:
                value, display_value = (
                    RepeatableRowReadService._system_value(
                        row=row,
                        field=field,
                    )
                )
            else:
                value_object = values_by_field_id.get(field.pk)
                value, display_value = (
                    RepeatableRowReadService._custom_value(
                        field=field,
                        value_object=value_object,
                    )
                )

            fields.append(
                {
                    "code": field.code,
                    "label": field.label,
                    "field_type": field.field_type,
                    "value": value,
                    "display_value": display_value,
                    "system_key": field.system_key,
                }
            )

        return {
            "row_id": row.pk,
            "row_order": row.row_order,
            "parent_row_id": row.parent_row_id,
            "instance_device_id": row.instance_device_id,
            "fields": fields,
        }

    @staticmethod
    def reconstruct_group(
        *,
        instance,
        group,
        parent_row=None,
    ):
        rows = RepeatableRowReadService.get_rows(
            instance=instance,
            group=group,
            parent_row=parent_row,
        )

        items = [
            RepeatableRowReadService._reconstruct_prefetched_row(
                row=row,
            )
            for row in rows
        ]

        child_groups = [
            RepeatableRowReadService.reconstruct_group(
                instance=instance,
                group=child_group,
                parent_row=None,
            )
            for child_group in group.child_groups.filter(
                is_active=True,
            ).order_by("order", "id")
        ]

        if parent_row is not None:
            child_groups = []

        return {
            "code": group.code,
            "name": group.name,
            "group_id": group.pk,
            "group_type": group.group_type,
            "display_type": group.display_type,
            "parent_group_id": group.parent_group_id,
            "items": items,
            "child_groups": child_groups,
        }

    @staticmethod
    def reconstruct_instance(*, instance):
        if instance is None or instance.pk is None:
            raise ValidationError("WorkflowInstance معتبر نیست.")

        groups = (
            FormRepeatableGroup.objects
            .filter(
                section__form__workflow=instance.workflow,
                parent_group__isnull=True,
                is_active=True,
            )
            .select_related("section", "section__form")
            .order_by(
                "section__order",
                "order",
                "id",
            )
        )

        return {
            "instance_id": instance.pk,
            "groups": [
                RepeatableRowReadService.reconstruct_group(
                    instance=instance,
                    group=group,
                )
                for group in groups
            ],
        }

    @staticmethod
    def _reconstruct_prefetched_row(*, row):
        values_by_field_id = {
            item.field_id: item
            for item in row.values.all()
        }

        fields = []

        for field in row.group.fields.filter(
            is_active=True,
        ).order_by("order", "id"):
            if field.system_key != FormField.SystemKey.NONE:
                value, display_value = (
                    RepeatableRowReadService._system_value(
                        row=row,
                        field=field,
                    )
                )
            else:
                value_object = values_by_field_id.get(field.pk)
                value, display_value = (
                    RepeatableRowReadService._custom_value(
                        field=field,
                        value_object=value_object,
                    )
                )

            fields.append(
                {
                    "code": field.code,
                    "label": field.label,
                    "field_type": field.field_type,
                    "value": value,
                    "display_value": display_value,
                    "system_key": field.system_key,
                }
            )

        return {
            "row_id": row.pk,
            "row_order": row.row_order,
            "parent_row_id": row.parent_row_id,
            "instance_device_id": row.instance_device_id,
            "fields": fields,
        }

    @staticmethod
    def _custom_value(*, field, value_object):
        if value_object is None:
            return None, ""

        if field.field_type in (
            FormField.FieldType.TEXT,
            FormField.FieldType.TEXTAREA,
        ):
            return value_object.text_value, value_object.text_value or ""

        if field.field_type == FormField.FieldType.NUMBER:
            value = value_object.decimal_value
            return value, "" if value is None else str(value)

        if field.field_type == FormField.FieldType.DATE:
            value = value_object.date_value
            return value, "" if value is None else value.isoformat()

        if field.field_type == FormField.FieldType.DATETIME:
            value = value_object.datetime_value
            return value, "" if value is None else value.isoformat()

        if field.field_type == FormField.FieldType.BOOLEAN:
            value = value_object.boolean_value
            if value is None:
                return None, ""
            return value, "بله" if value else "خیر"

        if field.field_type == FormField.FieldType.SELECT:
            if field.choice_source == FormField.ChoiceSource.STATIC:
                item = value_object.static_choice_item
                return (
                    item.value if item else None,
                    item.label if item else "",
                )

            if field.choice_source == FormField.ChoiceSource.LOOKUP:
                item = value_object.lookup_item
                return (
                    item.value if item else None,
                    item.label if item else "",
                )

            if field.choice_source == FormField.ChoiceSource.MODEL:
                return (
                    RepeatableRowReadService._model_reference_value(
                        field=field,
                        reference_id=value_object.reference_id,
                    )
                )

        raise ValidationError(
            f"نوع فیلد «{field.field_type}» برای reconstruction پشتیبانی نمی‌شود."
        )

    @staticmethod
    def _model_reference_value(*, field, reference_id):
        if not reference_id or not field.choice_model_id:
            return reference_id, ""

        model_class = field.choice_model.model_class()
        if model_class is None:
            return reference_id, ""

        obj = model_class.objects.filter(
            **{field.choice_value_field: reference_id}
        ).first()

        if obj is None:
            return reference_id, ""

        label = getattr(
            obj,
            field.choice_label_field,
            "",
        )

        return reference_id, str(label)

    @staticmethod
    def _system_value(*, row, field):
        instance_device = row.instance_device

        if instance_device is None:
            return None, ""

        key = field.system_key

        if key == FormField.SystemKey.IMEI:
            if instance_device.device_id:
                identifier = (
                    instance_device.device
                    .identifiers
                    .filter(
                        identifier_type=(
                            DeviceIdentifier.IdentifierType.IMEI
                        )
                    )
                    .first()
                )
                value = identifier.value if identifier else ""
                return value, value

            value = instance_device.draft_imei or ""
            return value, value

        if key == FormField.SystemKey.DEVICE_TYPE:
            if instance_device.device_id:
                obj = (
                    instance_device.device
                    .device_model
                    .device_type
                )
            else:
                obj = instance_device.draft_device_type

            return (
                obj.pk if obj else None,
                str(obj) if obj else "",
            )

        if key == FormField.SystemKey.DEVICE_MODEL:
            if instance_device.device_id:
                obj = instance_device.device.device_model
            else:
                obj = instance_device.draft_device_model

            return (
                obj.pk if obj else None,
                str(obj) if obj else "",
            )

        mapping = {
            FormField.SystemKey.REPORTED_PROBLEM: "reported_problem",
            FormField.SystemKey.DESCRIPTION: "description",
            FormField.SystemKey.WARRANTY_STATUS: "warranty_status",
            FormField.SystemKey.STATUS: "status",
        }

        attribute = mapping.get(key)
        if attribute is None:
            return None, ""

        value = getattr(instance_device, attribute, "")
        return value, value or ""
