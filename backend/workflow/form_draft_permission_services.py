from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .form_draft_diff_services import (
    FormDraftDiff,
    RowChangeAction,
)
from .models import FormField
from .permission_context import PermissionContext
from .repeatable_row_read_services import RepeatableRowReadService


class FormDraftPermissionService:
    """
    Validate write permissions for a side-effect-free FormDraftDiff.

    Row permissions are evaluated from the group:
    - CREATE -> can_add
    - UPDATE -> can_edit
    - DELETE -> can_delete

    Field permissions are evaluated independently:
    - editable field -> mutation is allowed
    - non-editable existing field -> omitted is preserved; submitting the
      same value is tolerated, but a different value is rejected
    - non-editable new field -> the submitted value is rejected because there
      is no persisted value that can be preserved

    This service never mutates rows, values, devices, or the diff itself.
    """

    @classmethod
    def validate(
        cls,
        *,
        diff: FormDraftDiff,
        permission_context: PermissionContext,
    ):
        for group_diff in diff.groups:
            for change in group_diff.changes:
                cls._validate_row_permission(
                    change=change,
                    permission_context=permission_context,
                )

                if change.action == RowChangeAction.DELETE:
                    continue

                cls._validate_field_permissions(
                    change=change,
                    permission_context=permission_context,
                )

    @staticmethod
    def _validate_row_permission(*, change, permission_context):
        permission = permission_context.group(change.group)

        if change.action == RowChangeAction.CREATE:
            allowed = permission.can_add
            action = "افزودن"
        elif change.action == RowChangeAction.UPDATE:
            allowed = permission.can_edit
            action = "ویرایش"
        else:
            allowed = permission.can_delete
            action = "حذف"

        if not allowed:
            raise ValidationError(
                f"شما اجازه {action} ردیف از گروه «{change.group.name}» را ندارید."
            )

    @classmethod
    def _validate_field_permissions(
        cls,
        *,
        change,
        permission_context,
    ):
        desired_row = change.desired_row
        if desired_row is None:
            return

        fields_by_code = {
            field.code: field
            for field in change.group.fields.filter(is_active=True)
        }

        persisted_values = {}
        if change.action == RowChangeAction.UPDATE:
            persisted_values = cls._get_persisted_values(
                row_id=change.row_id,
            )

        for field_code, submitted_value in desired_row.fields.items():
            field = fields_by_code[field_code]
            permission = permission_context.field(field)

            if permission.can_edit:
                continue

            if change.action == RowChangeAction.CREATE:
                raise ValidationError(
                    f"شما اجازه ثبت مقدار فیلد «{field.label}» "
                    f"در ردیف جدید گروه «{change.group.name}» را ندارید."
                )

            persisted_value = persisted_values.get(field_code)
            if cls._values_equal(
                field=field,
                submitted_value=submitted_value,
                persisted_value=persisted_value,
            ):
                continue

            raise ValidationError(
                f"شما اجازه ویرایش فیلد «{field.label}» "
                f"در گروه «{change.group.name}» را ندارید."
            )

    @staticmethod
    def _get_persisted_values(*, row_id):
        reconstructed = RepeatableRowReadService.reconstruct_row(
            row=type(
                "RowReference",
                (),
                {"pk": row_id},
            )()
        )
        return {
            item["code"]: item["value"]
            for item in reconstructed["fields"]
        }

    @staticmethod
    def _values_equal(*, field, submitted_value, persisted_value):
        if submitted_value in ("", None) and persisted_value in ("", None):
            return True

        if field.field_type == FormField.FieldType.NUMBER:
            try:
                return Decimal(str(submitted_value)) == Decimal(
                    str(persisted_value)
                )
            except (InvalidOperation, TypeError, ValueError):
                return str(submitted_value) == str(persisted_value)

        if field.field_type == FormField.FieldType.BOOLEAN:
            return FormDraftPermissionService._boolean_value(
                submitted_value
            ) == FormDraftPermissionService._boolean_value(
                persisted_value
            )

        if field.field_type in (
            FormField.FieldType.DATE,
            FormField.FieldType.DATETIME,
            FormField.FieldType.SELECT,
        ):
            return str(submitted_value) == str(persisted_value)

        return submitted_value == persisted_value

    @staticmethod
    def _boolean_value(value):
        if isinstance(value, bool):
            return value

        if value is None or value == "":
            return None

        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False

        return value
