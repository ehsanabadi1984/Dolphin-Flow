from django.core.exceptions import ValidationError
from django.db import transaction

from .form_draft_diff_services import FormDraftDiff, RowChangeAction
from .models import FormRepeatableGroup, RepeatableRow
from .repeatable_row_services import RepeatableRowService


class FormDraftDeleteApplyService:
    """
    Apply DELETE changes from a validated draft diff.

    This stage handles NORMAL repeatable groups only. DELETE changes are
    expected to be ordered bottom-up by FormDraftDiffService so child rows
    are removed before their parents.

    Permission validation is intentionally owned by
    FormDraftPermissionService and must run before this service.
    """

    @classmethod
    @transaction.atomic
    def apply(cls, *, instance, diff: FormDraftDiff):
        deleted_rows = []

        for group_diff in diff.groups:
            for change in group_diff.changes:
                if change.action != RowChangeAction.DELETE:
                    continue

                cls._delete_row(
                    instance=instance,
                    change=change,
                )
                deleted_rows.append(change.row_id)

        return tuple(deleted_rows)

    @classmethod
    def _delete_row(cls, *, instance, change):
        group = change.group

        if group.group_type != FormRepeatableGroup.GroupType.NORMAL:
            raise ValidationError(
                "Apply DELETE برای گروه‌های DEVICE در این مرحله پشتیبانی نمی‌شود."
            )

        if change.row_id is None:
            raise ValidationError(
                "DELETE باید یک Row موجود داشته باشد."
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

        RepeatableRowService.delete_row(row=row)
