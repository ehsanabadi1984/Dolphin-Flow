from django.core.exceptions import ValidationError
from django.db import transaction

from .form_draft_diff_services import (
    FormDraftDiff,
    RowChangeAction,
)
from .models import FormField, FormRepeatableGroup, RepeatableRow
from .repeatable_row_services import RepeatableRowService


class FormDraftUpdateApplyService:
    """
    Apply UPDATE changes from a validated draft diff.

    This stage handles NORMAL repeatable groups only. It persists only
    fields explicitly present in the desired row. Omitted fields are left
    untouched.

    Permission validation is intentionally owned by
    FormDraftPermissionService and must run before this service.
    """

    @classmethod
    @transaction.atomic
    def apply(cls, *, instance, diff: FormDraftDiff):
        updated_rows = {}

        for group_diff in diff.groups:
            for change in group_diff.changes:
                if change.action != RowChangeAction.UPDATE:
                    continue

                row = cls._update_row(
                    instance=instance,
                    change=change,
                )
                updated_rows[change.row_reference] = row

        return updated_rows

    @classmethod
    def _update_row(cls, *, instance, change):
        group = change.group

        if group.group_type != FormRepeatableGroup.GroupType.NORMAL:
            raise ValidationError(
                "Apply UPDATE برای گروه‌های DEVICE در این مرحله پشتیبانی نمی‌شود."
            )

        if change.row_id is None or change.desired_row is None:
            raise ValidationError(
                "UPDATE باید یک Row موجود و desired state داشته باشد."
            )

        row = (
            RepeatableRow.objects
            .select_related("instance", "group")
            .get(pk=change.row_id)
        )

        if row.instance_id != instance.pk:
            raise ValidationError(
                "Row موردنظر متعلق به WorkflowInstance فعلی نیست."
            )

        if row.group_id != group.pk:
            raise ValidationError(
                "Row موردنظر متعلق به گروه این تغییر نیست."
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

        return RepeatableRowService.get_row(row_id=row.pk)
