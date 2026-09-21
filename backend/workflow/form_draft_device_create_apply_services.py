from django.core.exceptions import ValidationError
from django.db import transaction

from .device_services import DeviceService
from .form_draft_diff_services import (
    FormDraftDiff,
    RowChangeAction,
    RowReferenceKind,
)
from .models import (
    DeviceIdentifier,
    FormField,
    FormRepeatableGroup,
    InstanceDevice,
    RepeatableRow,
)
from .repeatable_row_services import RepeatableRowService


class FormDraftDeviceCreateApplyService:
    """
    Apply CREATE changes for DEVICE repeatable groups.

    Permissions are validated before this service runs. This service owns
    only DEVICE domain validation and persistence.
    """

    @classmethod
    @transaction.atomic
    def apply(cls, *, instance, diff: FormDraftDiff, created_rows=None):
        if created_rows is None:
            created_rows = {}

        for group_diff in diff.groups:
            for change in group_diff.changes:
                if change.action != RowChangeAction.CREATE:
                    continue

                if (
                    change.group.group_type
                    != FormRepeatableGroup.GroupType.DEVICE
                ):
                    continue

                row = cls._create_row(
                    instance=instance,
                    change=change,
                    created_rows=created_rows,
                )
                created_rows[change.row_reference] = row

        return created_rows

    @classmethod
    def _create_row(cls, *, instance, change, created_rows):
        group = change.group
        parent_row = cls._resolve_parent(
            instance=instance,
            parent_reference=change.parent_reference,
            created_rows=created_rows,
        )

        fields_by_code = {
            field.code: field
            for field in group.fields.filter(is_active=True)
        }

        values = change.desired_row.fields
        system_fields = {
            field.system_key: field
            for field in fields_by_code.values()
            if field.system_key != FormField.SystemKey.NONE
        }

        imei = cls._string_value(
            values.get(
                system_fields.get(FormField.SystemKey.IMEI).code
                if FormField.SystemKey.IMEI in system_fields
                else None
            )
        )
        device_model_id = cls._raw_value(
            values,
            system_fields.get(FormField.SystemKey.DEVICE_MODEL),
        )
        device_type_id = cls._raw_value(
            values,
            system_fields.get(FormField.SystemKey.DEVICE_TYPE),
        )

        device_model = cls._get_model(device_model_id)
        device_type = cls._get_type(device_type_id)

        if device_model and device_type:
            if device_model.device_type_id != device_type.pk:
                raise ValidationError(
                    "مدل انتخاب‌شده متعلق به نوع دستگاه انتخاب‌شده نیست."
                )

        existing_device = None
        if imei:
            existing_device = DeviceService.get_device_by_identifier(
                identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                value=imei,
            )

        if existing_device and device_model:
            if existing_device.device_model_id != device_model.pk:
                raise ValidationError(
                    "این IMEI قبلاً برای مدل دیگری ثبت شده است."
                )

        if existing_device:
            duplicate = InstanceDevice.objects.filter(
                instance=instance,
                device=existing_device,
                is_active=True,
            ).exists()
            if duplicate:
                raise ValidationError(
                    "این دستگاه قبلاً به این فرآیند افزوده شده است."
                )

            instance_device = InstanceDevice.objects.create(
                instance=instance,
                device=existing_device,
                draft_imei="",
                draft_device_model=None,
                draft_device_type=None,
            )
        else:
            instance_device = InstanceDevice.objects.create(
                instance=instance,
                device=None,
                draft_imei=imei,
                draft_device_model=device_model,
                draft_device_type=device_type,
            )

        cls._apply_system_values(
            instance_device=instance_device,
            values=values,
            system_fields=system_fields,
        )

        row = RepeatableRowService.create_row(
            instance=instance,
            group=group,
            parent_row=parent_row,
            instance_device=instance_device,
        )

        cls._apply_custom_values(
            row=row,
            values=values,
            fields_by_code=fields_by_code,
        )

        return row

    @staticmethod
    def _resolve_parent(*, instance, parent_reference, created_rows):
        if parent_reference is None:
            return None

        if parent_reference.kind == RowReferenceKind.CREATE:
            try:
                return created_rows[parent_reference]
            except KeyError:
                raise ValidationError(
                    "Row والد جدید قبل از Row فرزند ایجاد نشده است."
                )

        if parent_reference.kind == RowReferenceKind.EXISTING:
            row = (
                RepeatableRow.objects
                .select_related("instance", "group")
                .get(pk=parent_reference.value)
            )
            if row.instance_id != instance.pk:
                raise ValidationError(
                    "Row والد موجود متعلق به WorkflowInstance فعلی نیست."
                )
            return row

        raise ValidationError("نوع RowReference والد معتبر نیست.")

    @staticmethod
    def _raw_value(values, field):
        if field is None:
            return None
        return values.get(field.code)

    @staticmethod
    def _string_value(value):
        return str(value or "").strip()

    @staticmethod
    def _get_model(model_id):
        if model_id in (None, ""):
            return None

        from .models import DeviceModel

        try:
            return DeviceModel.objects.get(
                pk=model_id,
                is_active=True,
            )
        except DeviceModel.DoesNotExist:
            raise ValidationError("مدل دستگاه معتبر نیست.")

    @staticmethod
    def _get_type(type_id):
        if type_id in (None, ""):
            return None

        from .models import DeviceType

        try:
            return DeviceType.objects.get(
                pk=type_id,
                is_active=True,
            )
        except DeviceType.DoesNotExist:
            raise ValidationError("نوع دستگاه معتبر نیست.")

    @classmethod
    def _apply_system_values(cls, *, instance_device, values, system_fields):
        field_map = {
            FormField.SystemKey.REPORTED_PROBLEM: "reported_problem",
            FormField.SystemKey.DESCRIPTION: "description",
            FormField.SystemKey.WARRANTY_STATUS: "warranty_status",
            FormField.SystemKey.STATUS: "status",
        }

        update_fields = []

        for system_key, model_field in field_map.items():
            field = system_fields.get(system_key)
            if field is None or field.code not in values:
                continue

            setattr(
                instance_device,
                model_field,
                values[field.code] if values[field.code] is not None else "",
            )
            update_fields.append(model_field)

        if update_fields:
            update_fields.append("updated_at")
            instance_device.save(update_fields=update_fields)

    @staticmethod
    def _apply_custom_values(*, row, values, fields_by_code):
        for field_code, value in values.items():
            field = fields_by_code.get(field_code)

            if field is None:
                raise ValidationError(
                    f"فیلد «{field_code}» برای گروه «{row.group.name}» وجود ندارد."
                )

            if field.system_key != FormField.SystemKey.NONE:
                continue

            RepeatableRowService.set_value(
                row=row,
                field=field,
                value=value,
            )
