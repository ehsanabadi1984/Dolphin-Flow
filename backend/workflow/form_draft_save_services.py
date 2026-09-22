from dataclasses import dataclass
from typing import Mapping

from django.core.exceptions import ValidationError
from django.db import transaction

from .form_draft_create_apply_services import FormDraftCreateApplyService
from .form_draft_delete_apply_services import FormDraftDeleteApplyService
from .form_draft_device_create_apply_services import FormDraftDeviceCreateApplyService
from .form_draft_device_update_apply_services import FormDraftDeviceUpdateApplyService
from .form_draft_diff_services import FormDraftDiff, FormDraftDiffService
from .form_draft_update_apply_services import FormDraftUpdateApplyService
from .form_draft_payloads import NormalizedFormPayload, NormalizedRow
from .form_draft_normal_field_apply_services import FormDraftNormalFieldApplyService
from .form_draft_permission_services import FormDraftPermissionService
from .form_draft_structural_validation_services import FormDraftStructuralValidationService
from .form_draft_value_validation_services import FormDraftValueValidationService
from .models import FormData, FormDefinition
from .permission_context import PermissionContext


@dataclass(frozen=True)
class FormDraftSaveResult:
    form_data: FormData | None
    saved: bool
    is_draft: bool
    permission_context: PermissionContext
    normalized_payload: NormalizedFormPayload
    diff: FormDraftDiff


class FormDraftSaveService:
    @classmethod
    def save(cls, *, instance, step, user, submitted_data, edit_mode):
        with transaction.atomic():
            form = cls._get_form(instance=instance)
            cls._validate_context(
                instance=instance,
                step=step,
                edit_mode=edit_mode,
            )
            permission_context = PermissionContext.build(
                workflow=instance.workflow,
                form=form,
                step=step,
                user=user,
            )
            FormDraftStructuralValidationService.validate_payload(
                instance=instance,
                form=form,
                submitted_data=submitted_data,
            )
            normalized_payload = cls._normalize_submitted_data(
                form=form,
                submitted_data=submitted_data,
            )
            diff = FormDraftDiffService.build(
                instance=instance,
                form=form,
                normalized_payload=normalized_payload,
            )
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=permission_context,
            )
            FormDraftValueValidationService.validate_payload(
                instance=instance,
                form=form,
                normalized_payload=normalized_payload,
            )
            return cls._save_draft(
                instance=instance,
                step=step,
                user=user,
                form=form,
                permission_context=permission_context,
                normalized_payload=normalized_payload,
                diff=diff,
            )

    @staticmethod
    def _get_form(*, instance):
        form = FormDefinition.objects.filter(
            workflow=instance.workflow,
            is_active=True,
        ).first()
        if form is None:
            raise ValidationError("برای این Workflow فرم فعالی تعریف نشده است.")
        return form

    @staticmethod
    def _validate_context(*, instance, step, edit_mode):
        if step is None:
            raise ValidationError("مرحله فرآیند برای ذخیره فرم مشخص نشده است.")
        if instance.workflow_id != step.workflow_id:
            raise ValidationError("مرحله انتخاب‌شده متعلق به فرآیند این نمونه نیست.")
        if instance.current_step_id != step.pk:
            raise ValidationError("این مرحله، مرحله فعلی فرآیند نیست.")
        execution = instance.step_executions.filter(
            workflow_step=step,
        ).order_by("-performed_at").first()
        if execution is None:
            raise ValidationError("اجرای فعالی برای مرحله فعلی پیدا نشد.")
        if execution.is_submitted:
            raise ValidationError("فرم این مرحله قبلاً ارسال شده و قابل ویرایش نیست.")
        if not edit_mode:
            raise ValidationError("فرم در حالت ویرایش نیست و قابل ذخیره نیست.")

    @classmethod
    def _normalize_submitted_data(cls, *, form, submitted_data):
        if not isinstance(submitted_data, Mapping):
            raise ValidationError("داده‌های فرم باید به صورت یک شیء ارسال شوند.")

        normal_fields = {}
        repeatable_groups = {}

        sections = form.sections.filter(
            is_active=True,
        ).prefetch_related(
            "fields",
            "repeatable_groups__fields",
            "repeatable_groups__child_groups__fields",
        )

        for section in sections:
            for field in section.fields.all():
                if not field.is_active or field.repeatable_group_id is not None:
                    continue
                if field.code in submitted_data:
                    normal_fields[field.code] = submitted_data[field.code]

            for group in section.repeatable_groups.filter(parent_group__isnull=True):
                if not group.is_active or group.code not in submitted_data:
                    continue

                raw_items = submitted_data[group.code]
                if not isinstance(raw_items, list):
                    raise ValidationError(
                        f"داده‌های گروه تکرارشونده «{group.name}» باید به صورت لیست باشند."
                    )

                repeatable_groups[group.code] = tuple(
                    cls._normalize_row(
                        group=group,
                        raw_item=raw_item,
                    )
                    for raw_item in raw_items
                )

        return NormalizedFormPayload(
            normal_fields=normal_fields,
            repeatable_groups=repeatable_groups,
        )

    @classmethod
    def _normalize_row(cls, *, group, raw_item):
        if not isinstance(raw_item, Mapping):
            raise ValidationError(
                f"هر ردیف از گروه «{group.name}» باید به صورت یک شیء باشد."
            )

        row_id = raw_item.get("row_id")
        if row_id is not None:
            if isinstance(row_id, bool) or not isinstance(row_id, int) or row_id <= 0:
                raise ValidationError(
                    f"شناسه ردیف گروه «{group.name}» معتبر نیست."
                )

        field_codes = {
            field.code
            for field in group.fields.all()
            if field.is_active
        }

        fields = {
            key: value
            for key, value in raw_item.items()
            if key in field_codes
        }

        child_groups = {}
        for child_group in group.child_groups.all():
            if not child_group.is_active or child_group.code not in raw_item:
                continue

            raw_children = raw_item[child_group.code]
            if not isinstance(raw_children, list):
                raise ValidationError(
                    f"داده‌های گروه تکرارشونده «{child_group.name}» باید به صورت لیست باشند."
                )

            child_groups[child_group.code] = tuple(
                cls._normalize_row(
                    group=child_group,
                    raw_item=child_item,
                )
                for child_item in raw_children
            )

        return NormalizedRow(
            row_id=row_id,
            fields=fields,
            child_groups=child_groups,
        )

    @staticmethod
    def _save_draft(
        *,
        instance,
        step,
        user,
        form,
        permission_context,
        normalized_payload,
        diff,
    ):
        del step, user, form
        created_rows = {}
        form_data = FormDraftNormalFieldApplyService.apply(
            instance=instance,
            diff=diff,
        )
        FormDraftCreateApplyService.apply(
            instance=instance,
            diff=diff,
            created_rows=created_rows,
        )
        FormDraftDeviceCreateApplyService.apply(
            instance=instance,
            diff=diff,
            created_rows=created_rows,
        )
        FormDraftDeviceUpdateApplyService.apply(
            instance=instance,
            diff=diff,
        )
        FormDraftUpdateApplyService.apply(
            instance=instance,
            diff=diff,
        )
        FormDraftDeleteApplyService.apply(
            instance=instance,
            diff=diff,
        )
        return FormDraftSaveResult(
            form_data=form_data,
            saved=True,
            is_draft=True,
            permission_context=permission_context,
            normalized_payload=normalized_payload,
            diff=diff,
        )
