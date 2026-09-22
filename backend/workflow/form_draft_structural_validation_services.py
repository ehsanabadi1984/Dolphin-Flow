from collections.abc import Mapping
from django.core.exceptions import ValidationError

from .form_draft_payloads import NormalizedFormPayload
from .models import RepeatableRow


class FormDraftStructuralValidationService:
    """
    Validate the structural contract of a draft/submit payload.

    This service does not validate field values, required/completeness rules,
    permissions, or persistence. It guarantees that the payload can be
    interpreted unambiguously as the form's current structure and row tree.
    """

    ROW_ID_KEY = "row_id"

    @classmethod
    def validate_payload(cls, *, instance, form, submitted_data):
        if not isinstance(submitted_data, Mapping):
            raise ValidationError("داده‌های فرم باید به صورت یک شیء ارسال شوند.")

        normal_fields, root_groups = cls._active_root_definitions(form=form)
        allowed_root_keys = normal_fields | set(root_groups)

        for key in submitted_data:
            if key not in allowed_root_keys:
                raise ValidationError(
                    f"فیلد یا گروه «{key}» در ساختار فعال این فرم وجود ندارد."
                )

        seen_row_ids = set()
        for group_code in root_groups:
            if group_code not in submitted_data:
                continue

            group = root_groups[group_code]
            raw_items = submitted_data[group_code]
            cls._validate_group_items(
                instance=instance,
                group=group,
                raw_items=raw_items,
                expected_parent_row_id=None,
                seen_row_ids=seen_row_ids,
            )

    @classmethod
    def validate_normalized_payload(cls, *, instance, form, normalized_payload):
        """
        Validate row identity and tree integrity after normalization.

        Value/type validation remains outside this service.
        """
        groups_by_code = {
            group.code: group
            for section in form.sections.filter(is_active=True)
            for group in section.repeatable_groups.filter(
                is_active=True,
                parent_group__isnull=True,
            )
        }

        seen_row_ids = set()
        for group_code, rows in normalized_payload.repeatable_groups.items():
            group = groups_by_code.get(group_code)
            if group is None:
                raise ValidationError(
                    f"گروه تکرارشونده «{group_code}» در فرم فعال نیست."
                )

            cls._validate_normalized_rows(
                instance=instance,
                group=group,
                rows=rows,
                expected_parent_row_id=None,
                seen_row_ids=seen_row_ids,
            )

    @classmethod
    def _validate_normal_fields(cls, *, submitted_data, normal_fields):
        for key in submitted_data:
            if key in normal_fields:
                continue

    @classmethod
    def _validate_group_items(
        cls,
        *,
        instance,
        group,
        raw_items,
        expected_parent_row_id,
        seen_row_ids,
    ):
        if not isinstance(raw_items, list):
            raise ValidationError(
                f"داده‌های گروه تکرارشونده «{group.name}» باید به صورت لیست باشند."
            )

        allowed_keys = cls._allowed_row_keys(group=group)

        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                raise ValidationError(
                    f"هر ردیف از گروه «{group.name}» باید به صورت یک شیء باشد."
                )

            for key in raw_item:
                if key not in allowed_keys:
                    raise ValidationError(
                        f"فیلد یا گروه «{key}» در ردیف گروه «{group.name}» "
                        "در ساختار فعال این فرم وجود ندارد."
                    )

            row_id = raw_item.get(cls.ROW_ID_KEY)
            cls._validate_row_identity(
                instance=instance,
                group=group,
                row_id=row_id,
                expected_parent_row_id=expected_parent_row_id,
                seen_row_ids=seen_row_ids,
            )

            next_parent_row_id = row_id
            for child_group in group.child_groups.filter(is_active=True):
                if child_group.code not in raw_item:
                    continue

                cls._validate_group_items(
                    instance=instance,
                    group=child_group,
                    raw_items=raw_item[child_group.code],
                    expected_parent_row_id=next_parent_row_id,
                    seen_row_ids=seen_row_ids,
                )

    @classmethod
    def _validate_normalized_rows(
        cls,
        *,
        instance,
        group,
        rows,
        expected_parent_row_id,
        seen_row_ids,
    ):
        for normalized_row in rows:
            row_id = normalized_row.row_id
            cls._validate_row_identity(
                instance=instance,
                group=group,
                row_id=row_id,
                expected_parent_row_id=expected_parent_row_id,
                seen_row_ids=seen_row_ids,
            )

            next_parent_row_id = row_id
            for child_group_code, child_rows in normalized_row.child_groups.items():
                child_group = group.child_groups.filter(
                    code=child_group_code,
                    is_active=True,
                ).first()
                if child_group is None:
                    raise ValidationError(
                        f"گروه فرزند «{child_group_code}» در گروه «{group.name}» "
                        "فعال نیست."
                    )

                cls._validate_normalized_rows(
                    instance=instance,
                    group=child_group,
                    rows=child_rows,
                    expected_parent_row_id=next_parent_row_id,
                    seen_row_ids=seen_row_ids,
                )

    @classmethod
    def _validate_row_identity(
        cls,
        *,
        instance,
        group,
        row_id,
        expected_parent_row_id,
        seen_row_ids,
    ):
        if row_id is None:
            # A new row may be nested under either a new or an existing
            # parent row. Existing child rows still require an existing
            # parent identity and are validated below.
            return

        if isinstance(row_id, bool) or not isinstance(row_id, int) or row_id <= 0:
            raise ValidationError(
                f"شناسه ردیف گروه «{group.name}» معتبر نیست."
            )

        if row_id in seen_row_ids:
            raise ValidationError(
                f"Row با شناسه «{row_id}» بیش از یک بار در Payload ارسال شده است."
            )

        try:
            row = RepeatableRow.objects.select_related("group").get(pk=row_id)
        except RepeatableRow.DoesNotExist:
            raise ValidationError(
                f"Row با شناسه «{row_id}» وجود ندارد."
            )

        if row.instance_id != instance.pk:
            raise ValidationError(
                f"Row با شناسه «{row_id}» متعلق به این WorkflowInstance نیست."
            )

        if row.group_id != group.pk:
            raise ValidationError(
                f"Row با شناسه «{row_id}» متعلق به گروه «{group.name}» نیست."
            )

        if row.parent_row_id != expected_parent_row_id:
            raise ValidationError(
                f"ساختار والد Row با شناسه «{row_id}» با Payload مطابقت ندارد."
            )

        seen_row_ids.add(row_id)

    @classmethod
    def _active_root_definitions(cls, *, form):
        normal_fields = set()
        root_groups = {}

        for section in form.sections.filter(is_active=True):
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            ):
                normal_fields.add(field.code)

            for group in section.repeatable_groups.filter(
                is_active=True,
                parent_group__isnull=True,
            ):
                root_groups[group.code] = group

        return normal_fields, root_groups

    @classmethod
    def _allowed_row_keys(cls, *, group):
        field_codes = {
            field.code
            for field in group.fields.filter(is_active=True)
        }
        child_group_codes = {
            child.code
            for child in group.child_groups.filter(is_active=True)
        }
        return {cls.ROW_ID_KEY} | field_codes | child_group_codes
