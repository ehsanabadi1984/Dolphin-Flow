from dataclasses import dataclass
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import FormData, FormDefinition
from .permission_context import PermissionContext


@dataclass(frozen=True)
class FormDraftSaveResult:
    form_data: FormData | None
    saved: bool
    is_draft: bool
    permission_context: PermissionContext


class FormDraftSaveService:
    @classmethod
    def save(cls, *, instance, step, user, submitted_data, edit_mode):
        del submitted_data
        with transaction.atomic():
            form = cls._get_form(instance=instance)
            cls._validate_context(instance=instance, step=step, edit_mode=edit_mode)
            permission_context = PermissionContext.build(
                workflow=instance.workflow,
                form=form,
                step=step,
                user=user,
            )
            return cls._save_draft(
                instance=instance,
                step=step,
                user=user,
                form=form,
                permission_context=permission_context,
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

    @staticmethod
    def _save_draft(*, instance, step, user, form, permission_context):
        del instance, step, user, form
        return FormDraftSaveResult(
            form_data=None,
            saved=False,
            is_draft=True,
            permission_context=permission_context,
        )
