from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .form_file_models import FormFile
from .models import (
    FormField,
    FormRepeatableGroup,
    RepeatableRow,
    RepeatableRowValue,
    WorkflowInstance,
)


class RepeatableRowService:
    """
    Application service for the persistence lifecycle of repeatable rows.

    This service owns row/value mutations without changing the legacy
    FormData JSON persistence yet. Integration with DynamicFormService
    is intentionally a later phase.
    """

    _UNSET = object()

    @staticmethod
    @transaction.atomic
    def create_row(
        *,
        instance,
        group,
        parent_row=None,
        row_order=None,
        instance_device=None,
    ):
        instance = (
            WorkflowInstance.objects
            .select_for_update()
            .get(pk=instance.pk)
        )

        RepeatableRowService._validate_context(
            instance=instance,
            group=group,
            parent_row=parent_row,
            instance_device=instance_device,
        )

        if row_order is None:
            sibling_filter = {
                "instance": instance,
                "group": group,
                "parent_row": parent_row,
            }

            last_row = (
                RepeatableRow.objects
                .select_for_update()
                .filter(**sibling_filter)
                .order_by("-row_order", "-id")
                .first()
            )

            row_order = (
                last_row.row_order + 1
                if last_row is not None
                else 0
            )

        row = RepeatableRow(
            instance=instance,
            group=group,
            parent_row=parent_row,
            row_order=row_order,
            instance_device=instance_device,
        )
        row.full_clean()
        row.save()

        return row

    @staticmethod
    @transaction.atomic
    def update_row(
        *,
        row,
        parent_row=_UNSET,
        row_order=None,
        instance_device=_UNSET,
    ):
        if row is None or row.pk is None:
            raise ValidationError("RepeatableRow مشخص نشده است.")

        locked_row = (
            RepeatableRow.objects
            .select_for_update(of=("self",))
            .select_related(
                "instance",
                "group",
                "group__section__form__workflow",
                "parent_row",
                "instance_device",
            )
            .get(pk=row.pk)
        )

        if parent_row is not RepeatableRowService._UNSET:
            locked_row.parent_row = parent_row

        if row_order is not None:
            locked_row.row_order = row_order

        if instance_device is not RepeatableRowService._UNSET:
            locked_row.instance_device = instance_device

        RepeatableRowService._validate_context(
            instance=locked_row.instance,
            group=locked_row.group,
            parent_row=locked_row.parent_row,
            instance_device=locked_row.instance_device,
            row=locked_row,
        )

        locked_row.full_clean()
        locked_row.save()

        return locked_row

    @staticmethod
    @transaction.atomic
    def delete_row(*, row):
        if row is None or row.pk is None:
            raise ValidationError("RepeatableRow مشخص نشده است.")

        locked_row = (
            RepeatableRow.objects
            .select_for_update()
            .get(pk=row.pk)
        )

        if locked_row.child_rows.exists():
            raise ValidationError(
                "این Row دارای Rowهای فرزند است و ابتدا باید فرزندان حذف شوند."
            )

        if locked_row.instance_device_id:
            raise ValidationError(
                "Row متصل به InstanceDevice را نمی‌توان حذف کرد."
            )

        form_data = getattr(locked_row.instance, "form_data", None)
        if form_data is not None:
            FormFile.delete_for_row(
                form_data=form_data,
                row_id=locked_row.pk,
            )

        locked_row.values.all().delete()
        locked_row.delete()

    @staticmethod
    def get_row(*, row_id):
        return (
            RepeatableRow.objects
            .select_related(
                "instance",
                "group",
                "group__section",
                "instance_device",
                "parent_row",
            )
            .prefetch_related(
                "values__field",
                "child_rows",
            )
            .get(pk=row_id)
        )

    @staticmethod
    def get_rows(
        *,
        instance,
        group,
        parent_row=None,
    ):
        return (
            RepeatableRow.objects
            .filter(
                instance=instance,
                group=group,
                parent_row=parent_row,
            )
            .select_related(
                "instance",
                "group",
                "instance_device",
                "parent_row",
            )
            .prefetch_related(
                "values__field",
            )
            .order_by("row_order", "id")
        )

    @staticmethod
    @transaction.atomic
    def set_value(
        *,
        row,
        field,
        value,
    ):
        if row is None or row.pk is None:
            raise ValidationError("RepeatableRow مشخص نشده است.")

        if field is None or field.pk is None:
            raise ValidationError("FormField مشخص نشده است.")

        locked_row = (
            RepeatableRow.objects
            .select_for_update()
            .get(pk=row.pk)
        )

        field = (
            FormField.objects
            .select_related(
                "repeatable_group",
                "choice_static_set",
                "choice_lookup_list",
                "choice_model",
            )
            .get(pk=field.pk)
        )

        if field.repeatable_group_id != locked_row.group_id:
            raise ValidationError(
                "فیلد باید متعلق به همان RepeatableGroup ردیف باشد."
            )

        value_kwargs = RepeatableRowService._value_kwargs(
            field=field,
            value=value,
        )

        row_value, _ = (
            RepeatableRowValue.objects
            .select_for_update()
            .get_or_create(
                row=locked_row,
                field=field,
            )
        )

        for name in (
            "text_value",
            "decimal_value",
            "date_value",
            "datetime_value",
            "boolean_value",
            "static_choice_item",
            "lookup_item",
            "reference_id",
        ):
            setattr(row_value, name, value_kwargs.get(name))

        row_value.full_clean()
        row_value.save()

        return row_value

    @staticmethod
    @transaction.atomic
    def remove_value(*, row, field):
        if row is None or row.pk is None:
            raise ValidationError("RepeatableRow مشخص نشده است.")

        if field is None or field.pk is None:
            raise ValidationError("FormField مشخص نشده است.")

        deleted, _ = (
            RepeatableRowValue.objects
            .filter(
                row=row,
                field=field,
            )
            .delete()
        )

        return deleted > 0

    @staticmethod
    def _value_kwargs(*, field, value):
        kwargs = {
            "text_value": None,
            "decimal_value": None,
            "date_value": None,
            "datetime_value": None,
            "boolean_value": None,
            "static_choice_item": None,
            "lookup_item": None,
            "reference_id": None,
        }

        if field.field_type in (
            FormField.FieldType.TEXT,
            FormField.FieldType.TEXTAREA,
        ):
            kwargs["text_value"] = "" if value is None else str(value)
            return kwargs

        if field.field_type == FormField.FieldType.NUMBER:
            if value is None or value == "":
                raise ValidationError("مقدار NUMBER نمی‌تواند خالی باشد.")
            kwargs["decimal_value"] = Decimal(str(value))
            return kwargs

        if field.field_type == FormField.FieldType.DATE:
            if value is None:
                raise ValidationError("مقدار DATE نمی‌تواند خالی باشد.")
            kwargs["date_value"] = value
            return kwargs

        if field.field_type == FormField.FieldType.DATETIME:
            if value is None:
                raise ValidationError("مقدار DATETIME نمی‌تواند خالی باشد.")
            kwargs["datetime_value"] = value
            return kwargs

        if field.field_type == FormField.FieldType.BOOLEAN:
            if not isinstance(value, bool):
                raise ValidationError("مقدار BOOLEAN باید True یا False باشد.")
            kwargs["boolean_value"] = value
            return kwargs

        if field.field_type == FormField.FieldType.SELECT:
            if value is None or value == "":
                raise ValidationError("مقدار SELECT نمی‌تواند خالی باشد.")

            if field.choice_source == FormField.ChoiceSource.STATIC:
                choice = (
                    field.choice_static_set.items
                    .filter(
                        value=str(value),
                        is_active=True,
                    )
                    .first()
                )
                if choice is None:
                    raise ValidationError("گزینه SELECT در مجموعه گزینه‌ها وجود ندارد.")
                kwargs["static_choice_item"] = choice
                return kwargs

            if field.choice_source == FormField.ChoiceSource.LOOKUP:
                item = (
                    field.choice_lookup_list.items
                    .filter(
                        value=str(value),
                        is_active=True,
                    )
                    .first()
                )
                if item is None:
                    raise ValidationError("گزینه SELECT در لیست داده‌ای وجود ندارد.")
                kwargs["lookup_item"] = item
                return kwargs

            if field.choice_source == FormField.ChoiceSource.MODEL:
                kwargs["reference_id"] = str(value)
                return kwargs

            raise ValidationError("فیلد SELECT منبع گزینه معتبر ندارد.")

        raise ValidationError(
            f"نوع فیلد «{field.field_type}» برای RepeatableRowValue پشتیبانی نمی‌شود."
        )

    @staticmethod
    def _validate_context(
        *,
        instance,
        group,
        parent_row=None,
        instance_device=None,
        row=None,
    ):
        if not isinstance(instance, WorkflowInstance) or instance.pk is None:
            raise ValidationError("WorkflowInstance معتبر نیست.")

        if not isinstance(group, FormRepeatableGroup) or group.pk is None:
            raise ValidationError("RepeatableGroup معتبر نیست.")

        if group.section.form.workflow_id != instance.workflow_id:
            raise ValidationError(
                "گروه تکرارشونده و WorkflowInstance باید متعلق به یک Workflow باشند."
            )

        if parent_row is not None:
            if parent_row.pk is None:
                raise ValidationError("Row والد باید ذخیره شده باشد.")

            if parent_row.instance_id != instance.pk:
                raise ValidationError(
                    "Row والد باید متعلق به همان WorkflowInstance باشد."
                )

            if not group.parent_group_id:
                raise ValidationError(
                    "این گروه parent_group ندارد و نمی‌تواند زیر یک Row دیگر قرار بگیرد."
                )

            if parent_row.group_id != group.parent_group_id:
                raise ValidationError(
                    "Row والد باید متعلق به parent_group همین گروه باشد."
                )

        if instance_device is not None:
            if instance_device.pk is None:
                raise ValidationError("InstanceDevice باید ذخیره شده باشد.")

            if group.group_type != FormRepeatableGroup.GroupType.DEVICE:
                raise ValidationError(
                    "InstanceDevice فقط برای Row گروه DEVICE مجاز است."
                )

            if instance_device.instance_id != instance.pk:
                raise ValidationError(
                    "InstanceDevice باید متعلق به همان WorkflowInstance باشد."
                )

        if row is not None and parent_row is row:
            raise ValidationError(
                "یک Row نمی‌تواند والد خودش باشد."
            )
