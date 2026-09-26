from django.core.exceptions import ValidationError

from .form_draft_payloads import NormalizedFormPayload, NormalizedRow
from .models import FormData, FormField, FormRepeatableGroup, RepeatableRow
from .repeatable_row_read_services import RepeatableRowReadService


class FormDraftSubmitValidationService:
    """
    Stage 12.5: validate completeness for final Submit.

    This validator is read-only and accepts the canonical normalized payload.
    It does not persist data, check permissions, or perform domain/device
    validation.

    Omitted top-level fields/groups mean "unchanged" and therefore fall back
    to persisted canonical state. An explicitly supplied empty value/group is
    treated as empty and fails completeness when required.

    DEVICE groups keep their existing domain rule: at least one row/device is
    required. Device field/domain integrity is owned by the device/domain
    validation layer and is not duplicated here.
    """

    @classmethod
    def validate_payload(
        cls,
        *,
        instance,
        form,
        normalized_payload: NormalizedFormPayload,
    ):
        errors = []

        errors.extend(
            cls._validate_normal_fields(
                instance=instance,
                form=form,
                submitted_values=normalized_payload.normal_fields,
            )
        )

        for group in cls._active_root_groups(form=form):
            if group.group_type == FormRepeatableGroup.GroupType.DEVICE:
                errors.extend(
                    cls._validate_device_group(
                        instance=instance,
                        group=group,
                        normalized_payload=normalized_payload,
                    )
                )
                continue

            errors.extend(
                cls._validate_normal_group(
                    instance=instance,
                    group=group,
                    normalized_payload=normalized_payload,
                )
            )

        if errors:
            error = ValidationError(
                "فرم برای ارسال نهایی کامل نیست."
            )
            error.validation_errors = errors
            raise error

    @classmethod
    def _validate_normal_fields(cls, *, instance, form, submitted_values):
        errors = []
        form_data = (
            FormData.objects.filter(instance=instance).first()
        )
        persisted = (form_data.data or {}) if form_data else {}

        fields = cls._normal_fields(form=form)

        for field in fields:
            if not field.is_required:
                continue

            value = (
                submitted_values[field.code]
                if field.code in submitted_values
                else persisted.get(field.code, "")
            )

            if cls._is_empty(value):
                errors.append(
                    cls._field_error(
                        field=field,
                        message=f"فیلد «{field.label}» الزامی است.",
                    )
                )

        return errors

    @classmethod
    def _validate_device_group(
        cls,
        *,
        instance,
        group,
        normalized_payload,
    ):
        if group.code in normalized_payload.repeatable_groups:
            rows = normalized_payload.repeatable_groups[group.code]
            count = len(rows)
        else:
            count = (
                RepeatableRow.objects
                .filter(
                    instance=instance,
                    group=group,
                    parent_row__isnull=True,
                )
                .count()
            )

        if count:
            return []

        return [
            {
                "type": "device_group",
                "group_code": group.code,
                "group_label": group.name,
                "message": (
                    f"حداقل یک دستگاه باید در گروه «{group.name}» "
                    "وجود داشته باشد."
                ),
            }
        ]

    @classmethod
    def _validate_normal_group(
        cls,
        *,
        instance,
        group,
        normalized_payload,
        parent_row=None,
    ):
        if parent_row is not None:
            raise ValueError(
                "_validate_normal_group expects a root group."
            )

        if group.code in normalized_payload.repeatable_groups:
            rows = normalized_payload.repeatable_groups[group.code]
        else:
            rows = tuple(
                cls._persisted_rows(
                    instance=instance,
                    group=group,
                    parent_row=None,
                )
            )

        errors = []

        if group.is_required and not rows:
            errors.append(
                {
                    "type": "group",
                    "code": group.code,
                    "label": group.name,
                    "message": (
                        f"گروه «{group.name}» "
                        "حداقل یک مورد الزامی دارد."
                    ),
                }
            )

        for row in rows:
            errors.extend(
                cls._validate_row(
                    instance=instance,
                    group=group,
                    row=row,
                )
            )

        return errors

    @classmethod
    def _validate_row(cls, *, instance, group, row):
        persisted_values = cls._persisted_values(row_id=row.row_id)
        errors = []

        for field in group.fields.filter(
            is_active=True,
            is_required=True,
        ).order_by("order", "id"):
            if field.code in row.fields:
                value = row.fields[field.code]
            else:
                value = persisted_values.get(field.code, "")

            if cls._is_empty(value):
                errors.append(
                    cls._field_error(
                        field=field,
                        message=f"فیلد «{field.label}» الزامی است.",
                        group=group,
                        row=row,
                    )
                )

        for child_group in group.child_groups.filter(
            is_active=True,
        ).order_by("order", "id"):
            child_rows = row.child_groups.get(
                child_group.code,
            )

            if child_rows is None:
                child_rows = tuple(
                    cls._persisted_rows(
                        instance=instance,
                        group=child_group,
                        parent_row_id=row.row_id,
                    )
                )

            if child_group.group_type == FormRepeatableGroup.GroupType.DEVICE:
                if child_group.is_required and not child_rows:
                    errors.append(
                        {
                            "type": "group",
                            "code": child_group.code,
                            "label": child_group.name,
                            "message": (
                                f"گروه «{child_group.name}» "
                                "حداقل یک مورد الزامی دارد."
                            ),
                        }
                    )
                continue

            if child_group.is_required and not child_rows:
                errors.append(
                    {
                        "type": "group",
                        "code": child_group.code,
                        "label": child_group.name,
                        "message": (
                            f"گروه «{child_group.name}» "
                            "حداقل یک مورد الزامی دارد."
                        ),
                    }
                )

            for child_row in child_rows:
                errors.extend(
                    cls._validate_row(
                        instance=instance,
                        group=child_group,
                        row=child_row,
                    )
                )

        return errors

    @staticmethod
    def _persisted_rows(*, instance, group, parent_row=None, parent_row_id=None):
        if parent_row is not None:
            parent_row_id = parent_row.pk

        queryset = RepeatableRow.objects.filter(
            instance=instance,
            group=group,
            parent_row_id=parent_row_id,
        ).order_by("row_order", "id")

        return tuple(
            NormalizedRow(
                row_id=row.pk,
                fields={},
                child_groups={},
            )
            for row in queryset
        )

    @staticmethod
    def _persisted_values(*, row_id):
        if row_id is None:
            return {}

        row = RepeatableRow.objects.filter(pk=row_id).first()
        if row is None:
            return {}

        reconstructed = RepeatableRowReadService.reconstruct_row(row=row)
        return {
            item["code"]: item["value"]
            for item in reconstructed["fields"]
        }

    @staticmethod
    def _normal_fields(*, form):
        return (
            field
            for section in form.sections.filter(is_active=True)
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            ).order_by("order", "id")
        )

    @staticmethod
    def _active_root_groups(*, form):
        return (
            group
            for section in form.sections.filter(is_active=True)
            for group in section.repeatable_groups.filter(
                is_active=True,
                parent_group__isnull=True,
            ).order_by("order", "id")
        )

    @staticmethod
    def _field_error(*, field, message, group=None, row=None):
        error = {
            "type": "field",
            "code": field.code,
            "label": field.label,
            "message": message,
        }

        if group is not None:
            error["group_code"] = group.code

        if row is not None:
            error["row_id"] = row.row_id

        return error

    @staticmethod
    def _is_empty(value):
        return value is None or (
            isinstance(value, str) and not value.strip()
        )
