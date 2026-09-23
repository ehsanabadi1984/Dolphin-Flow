from django.core.exceptions import ValidationError
from django.db import transaction

from .form_draft_diff_services import FormDraftDiff, RowChangeAction
from .form_file_models import FormFile
from .instance_device_services import InstanceDeviceService
from .models import FormRepeatableGroup, RepeatableRow


class FormDraftDeleteApplyService:
    """
    Apply DELETE changes from a validated draft diff.

    DELETE is row-centric and applies to both NORMAL and DEVICE repeatable
    groups. DELETE changes are expected to be ordered bottom-up by
    FormDraftDiffService so child rows are removed before their parents.

    For DEVICE rows, the current RepeatableRow is removed and its
    InstanceDevice assignment is deactivated. InstanceDevice, Device, and
    history records are preserved.

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
    @transaction.atomic
    def delete_row_tree(cls, *, instance, row_id):
        """
        Delete a current form row and its descendants.

        This is the direct operator-panel DELETE path. It is row-centric:
        RepeatableRow/values/files are removed, while InstanceDevice,
        Device, and history remain untouched.
        """
        try:
            row = (
                RepeatableRow.objects
                .select_related("instance", "group")
                .get(
                    pk=row_id,
                    instance=instance,
                )
            )
        except RepeatableRow.DoesNotExist:
            raise ValidationError("Row موردنظر برای حذف یافت نشد.")

        rows = []
        stack = [row]

        while stack:
            current = stack.pop()
            rows.append(current)
            stack.extend(current.child_rows.all())

        deleted_row_ids = tuple(current.pk for current in reversed(rows))

        for current in reversed(rows):
            cls._deactivate_device_assignment(current)
            form_data = getattr(instance, "form_data", None)
            if form_data is not None:
                FormFile.delete_for_row(
                    form_data=form_data,
                    row_id=current.pk,
                )
            current.values.all().delete()
            current.delete()

        return deleted_row_ids

    @staticmethod
    def _deactivate_device_assignment(row):
        if row.instance_device_id is None:
            return

        InstanceDeviceService.deactivate_device(
            instance_device=row.instance_device,
        )

    @classmethod
    def _delete_row(cls, *, instance, change):
        group = change.group

        if group.group_type not in (
            FormRepeatableGroup.GroupType.NORMAL,
            FormRepeatableGroup.GroupType.DEVICE,
        ):
            raise ValidationError(
                "نوع گروه RepeatableRow برای DELETE معتبر نیست."
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

        # Draft DELETE is intentionally row-centric. Do not delegate to
        # RepeatableRowService.delete_row() because that generic service
        # protects rows linked to InstanceDevice. The current-form membership
        # is removed by deleting the Row; the InstanceDevice assignment is
        # preserved for history but deactivated so it is not rendered again.
        cls._deactivate_device_assignment(row)
        form_data = getattr(instance, "form_data", None)
        if form_data is not None:
            FormFile.delete_for_row(
                form_data=form_data,
                row_id=row.pk,
            )

        row.values.all().delete()
        row.delete()
