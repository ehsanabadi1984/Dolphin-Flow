from django.core.exceptions import ValidationError
from django.db import transaction

from .device_services import DeviceService
from .form_draft_diff_services import (
    FormDraftDiff,
    RowChangeAction,
)
from .models import (
    DeviceIdentifier,
    FormField,
    FormRepeatableGroup,
    InstanceDevice,
    RepeatableRow,
)
from .repeatable_row_services import RepeatableRowService


class FormDraftDeviceUpdateApplyService:
    """
    Apply UPDATE changes for DEVICE repeatable groups.

    Permission checks are performed by FormDraftPermissionService before this
    service. This service owns DEVICE domain rules and persistence.
    """

    _SYSTEM_FIELD_MAP = {
        FormField.SystemKey.REPORTED_PROBLEM: "reported_problem",
        FormField.SystemKey.DESCRIPTION: "description",
        FormField.SystemKey.WARRANTY_STATUS: "warranty_status",
        FormField.SystemKey.STATUS: "status",
    }

    @classmethod
    @transaction.atomic
    def apply(cls, *, instance, diff: FormDraftDiff):
        updated_rows = {}

        for group_diff in diff.groups:
            for change in group_diff.changes:
                if change.action != RowChangeAction.UPDATE:
                    continue

                if (
                    change.group.group_type
                    != FormRepeatableGroup.GroupType.DEVICE
                ):
                    continue

                row = cls._update_row(
                    instance=instance,
                    change=change,
                )
                updated_rows[change.row_reference] = row

        return updated_rows

    @classmethod
    def _update_row(cls, *, instance, change):
        if change.row_id is None or change.desired_row is None:
            raise ValidationError(
                "UPDATE باید یک Row موجود و desired state داشته باشد."
            )

        row = (
            RepeatableRow.objects
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
            .select_for_update(of=("self",))
            .get(pk=change.row_id)
        )

        if row.instance_id != instance.pk:
            raise ValidationError(
                "Row موردنظر متعلق به WorkflowInstance فعلی نیست."
            )

        if row.group_id != change.group.pk:
            raise ValidationError(
                "Row موردنظر متعلق به گروه این تغییر نیست."
            )

        if row.instance_device_id is None:
            raise ValidationError(
                "Row دستگاه فاقد InstanceDevice است."
            )

        instance_device = row.instance_device
        if not instance_device.is_active:
            raise ValidationError(
                "InstanceDevice غیرفعال قابل ویرایش نیست."
            )

        fields_by_code = {
            field.code: field
            for field in change.group.fields.filter(is_active=True)
        }

        values = change.desired_row.fields
        system_fields = {
            field.system_key: field
            for field in fields_by_code.values()
            if field.system_key != FormField.SystemKey.NONE
        }

        imei_field = system_fields.get(FormField.SystemKey.IMEI)
        model_field = system_fields.get(FormField.SystemKey.DEVICE_MODEL)
        type_field = system_fields.get(FormField.SystemKey.DEVICE_TYPE)

        submitted_imei = (
            cls._string_value(values[imei_field.code])
            if imei_field is not None and imei_field.code in values
            else None
        )

        submitted_model_id = (
            values[model_field.code]
            if model_field is not None and model_field.code in values
            else None
        )
        submitted_type_id = (
            values[type_field.code]
            if type_field is not None and type_field.code in values
            else None
        )

        if instance_device.device_id is not None:
            cls._update_resolved_device(
                instance=instance,
                instance_device=instance_device,
                values=values,
                system_fields=system_fields,
                submitted_imei=submitted_imei,
                submitted_model_id=submitted_model_id,
                submitted_type_id=submitted_type_id,
            )
        else:
            cls._update_unresolved_device(
                instance=instance,
                instance_device=instance_device,
                values=values,
                system_fields=system_fields,
                submitted_imei=submitted_imei,
                submitted_model_id=submitted_model_id,
                submitted_type_id=submitted_type_id,
            )

        cls._apply_custom_values(
            row=row,
            values=values,
            fields_by_code=fields_by_code,
        )

        return RepeatableRowService.get_row(row_id=row.pk)

    @classmethod
    def _update_resolved_device(
        cls,
        *,
        instance,
        instance_device,
        values,
        system_fields,
        submitted_imei,
        submitted_model_id,
        submitted_type_id,
    ):
        if submitted_imei is not None:
            current_imei = cls._current_imei(instance_device)
            if submitted_imei != current_imei:
                raise ValidationError(
                    "IMEI دستگاهی که قبلاً شناسایی شده است قابل تغییر نیست."
                )

        device = instance_device.device
        current_model = device.device_model
        target_model = (
            cls._get_model(submitted_model_id)
            if submitted_model_id not in (None, "")
            else current_model
        )
        target_type = (
            cls._get_type(submitted_type_id)
            if submitted_type_id not in (None, "")
            else current_model.device_type
        )

        if target_model.device_type_id != target_type.pk:
            raise ValidationError(
                "مدل انتخاب‌شده متعلق به نوع دستگاه انتخاب‌شده نیست."
            )

        if target_model.pk != current_model.pk:
            device.device_model = target_model
            device.save(update_fields=["device_model", "updated_at"])

        cls._clear_draft_identity(
            instance_device=instance_device,
            update=False,
        )
        cls._apply_system_values(
            instance_device=instance_device,
            values=values,
            system_fields=system_fields,
        )

    @classmethod
    def _update_unresolved_device(
        cls,
        *,
        instance,
        instance_device,
        values,
        system_fields,
        submitted_imei,
        submitted_model_id,
        submitted_type_id,
    ):
        current_imei = cls._string_value(instance_device.draft_imei)
        imei = (
            submitted_imei
            if submitted_imei is not None
            else current_imei
        )

        current_model = instance_device.draft_device_model
        current_type = instance_device.draft_device_type

        target_model = (
            cls._get_model(submitted_model_id)
            if submitted_model_id not in (None, "")
            else current_model
        )
        target_type = (
            cls._get_type(submitted_type_id)
            if submitted_type_id not in (None, "")
            else current_type
        )

        if target_model is not None and target_type is not None:
            if target_model.device_type_id != target_type.pk:
                raise ValidationError(
                    "مدل انتخاب‌شده متعلق به نوع دستگاه انتخاب‌شده نیست."
                )

        if imei:
            existing_device = DeviceService.get_device_by_identifier(
                identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                value=imei,
            )

            if existing_device is not None:
                if target_model is not None:
                    if existing_device.device_model_id != target_model.pk:
                        raise ValidationError(
                            "این IMEI قبلاً برای مدل دیگری ثبت شده است."
                        )
                else:
                    target_model = existing_device.device_model
                    target_type = existing_device.device_model.device_type

                duplicate = (
                    InstanceDevice.objects
                    .filter(
                        instance=instance,
                        device=existing_device,
                        is_active=True,
                    )
                    .exclude(pk=instance_device.pk)
                    .exists()
                )
                if duplicate:
                    raise ValidationError(
                        "این دستگاه قبلاً به این فرآیند افزوده شده است."
                    )

                instance_device.device = existing_device
                instance_device.draft_imei = ""
                instance_device.draft_device_model = None
                instance_device.draft_device_type = None
                instance_device.save(
                    update_fields=[
                        "device",
                        "draft_imei",
                        "draft_device_model",
                        "draft_device_type",
                        "updated_at",
                    ]
                )

                cls._apply_system_values(
                    instance_device=instance_device,
                    values=values,
                    system_fields=system_fields,
                )
                return

        instance_device.device = None
        instance_device.draft_imei = imei
        instance_device.draft_device_model = target_model
        instance_device.draft_device_type = target_type
        instance_device.save(
            update_fields=[
                "device",
                "draft_imei",
                "draft_device_model",
                "draft_device_type",
                "updated_at",
            ]
        )

        cls._apply_system_values(
            instance_device=instance_device,
            values=values,
            system_fields=system_fields,
        )

    @staticmethod
    def _current_imei(instance_device):
        return (
            instance_device.device.identifiers
            .filter(
                identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            )
            .values_list("value", flat=True)
            .first()
            or ""
        )

    @staticmethod
    def _clear_draft_identity(*, instance_device, update):
        if not (
            instance_device.draft_imei
            or instance_device.draft_device_model_id
            or instance_device.draft_device_type_id
        ):
            return

        instance_device.draft_imei = ""
        instance_device.draft_device_model = None
        instance_device.draft_device_type = None
        instance_device.save(
            update_fields=[
                "draft_imei",
                "draft_device_model",
                "draft_device_type",
                "updated_at",
            ]
        )

    @staticmethod
    def _get_model(model_id):
        if model_id in (None, ""):
            return None

        from .models import DeviceModel

        try:
            return DeviceModel.objects.select_related("device_type").get(
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
        update_fields = []

        for system_key, model_field in cls._SYSTEM_FIELD_MAP.items():
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

    @staticmethod
    def _string_value(value):
        return str(value or "").strip()
