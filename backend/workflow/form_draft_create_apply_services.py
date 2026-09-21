from django.core.exceptions import ValidationError
from django.db import transaction

from .form_draft_diff_services import (
    FormDraftDiff,
    RowChangeAction,
    RowReference,
    RowReferenceKind,
)
from .models import FormField, FormRepeatableGroup, RepeatableRow
from .repeatable_row_services import RepeatableRowService


class FormDraftCreateApplyService:
    """
    Apply CREATE changes from a validated draft diff.

    This stage intentionally handles NORMAL repeatable groups only.
    UPDATE and DELETE are not applied here, and DEVICE creation remains
    a separate domain step because it requires InstanceDevice semantics.

    The caller is responsible for running row-identity and permission
    validation before applying the diff.
    """

    @classmethod
    @transaction.atomic
    def apply(cls, *, instance, diff: FormDraftDiff):
        created_rows = {}

        for group_diff in diff.groups:
            for change in group_diff.changes:
                if change.action != RowChangeAction.CREATE:
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

        if group.group_type != FormRepeatableGroup.GroupType.NORMAL:
            raise ValidationError(
                "Apply CREATE برای گروه‌های DEVICE در این مرحله پشتیبانی نمی‌شود."
            )

        parent_row = cls._resolve_parent(
            instance=instance,
            parent_reference=change.parent_reference,
            created_rows=created_rows,
        )

        row = RepeatableRowService.create_row(
            instance=instance,
            group=group,
            parent_row=parent_row,
        )

        fields_by_code = {
            field.code: field
            for field in group.fields.filter(is_active=True)
        }

        for field_code, value in change.desired_row.fields.items():
            field = fields_by_code.get(field_code)
            if field is None:
                raise ValidationError(
                    f"فیلد «{field_code}» برای گروه «{group.name}» وجود ندارد."
                )

            if field.system_key != FormField.SystemKey.NONE:
                raise ValidationError(
                    f"فیلد سیستمی «{field.code}» نمی‌تواند در این مرحله "
                    "به RepeatableRowValue تبدیل شود."
                )

            RepeatableRowService.set_value(
                row=row,
                field=field,
                value=value,
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
