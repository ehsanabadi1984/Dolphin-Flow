from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    Notification,
    WorkflowInstance,
    WorkflowStepExecution,
)
from .notification_services import NotificationService
from .realtime_services import WorkflowRealtimeService
from .sla_services import SLAService


class WorkflowOverrideService:
    """Administrative correction of a workflow instance's current step."""

    MIN_REASON_LENGTH = 5

    @staticmethod
    @transaction.atomic
    def override_instance_step(*, instance, target_step, performed_by, reason):
        instance = (
            WorkflowInstance.objects
            .select_for_update()
            .select_related("workflow", "current_step")
            .get(pk=instance.pk)
        )

        if not performed_by.is_active or not performed_by.is_staff:
            raise ValidationError("فقط کاربران فعال Admin می‌توانند مسیر فرآیند را اصلاح کنند.")

        reason = (reason or "").strip()
        if len(reason) < WorkflowOverrideService.MIN_REASON_LENGTH:
            raise ValidationError("دلیل اصلاح مسیر الزامی است و باید حداقل ۵ کاراکتر باشد.")

        if target_step is None:
            raise ValidationError("مرحله مقصد باید مشخص شود.")

        if target_step.workflow_id != instance.workflow_id:
            raise ValidationError("مرحله مقصد متعلق به Workflow این Instance نیست.")

        if not target_step.is_active:
            raise ValidationError("مرحله مقصد فعال نیست.")

        if instance.current_step_id == target_step.pk:
            raise ValidationError("مرحله مقصد با مرحله فعلی یکسان است.")

        if instance.status == WorkflowInstance.Status.CANCELLED:
            raise ValidationError("فرآیند لغو شده قابل اصلاح مسیر نیست.")

        if instance.status not in (
            WorkflowInstance.Status.ACTIVE,
            WorkflowInstance.Status.COMPLETED,
        ):
            raise ValidationError("وضعیت فعلی فرآیند برای اصلاح مسیر مجاز نیست.")

        now = timezone.now()
        from_step = instance.current_step
        from_step_id = from_step.pk if from_step else None
        from_step_name = from_step.name if from_step else None

        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=target_step,
            performed_by=performed_by,
            data={
                "override": {
                    "from_step_id": from_step_id,
                    "from_step_name": from_step_name,
                    "to_step_id": target_step.pk,
                    "to_step_name": target_step.name,
                    "reason": reason,
                    "performed_by_id": performed_by.pk,
                    "performed_at": now.isoformat(),
                },
            },
            is_submitted=False,
        )

        SLAService.start_sla_if_configured(
            step_execution=step_execution,
        )

        instance.current_step = target_step

        update_fields = ["current_step"]

        if instance.status == WorkflowInstance.Status.COMPLETED:
            instance.status = WorkflowInstance.Status.ACTIVE
            instance.completed_at = None
            update_fields.extend(["status", "completed_at"])

        instance.save(update_fields=update_fields)

        recipient = target_step.assigned_to
        if (
            recipient
            and recipient.is_active
            and recipient != performed_by
        ):
            NotificationService.create(
                recipient=recipient,
                notification_type=Notification.NotificationType.ACTION_REQUIRED,
                title=f"اصلاح مسیر فرآیند «{instance.workflow.name}»",
                message=(
                    f"فرآیند «{instance.workflow.name}» توسط Admin از مرحله "
                    f"«{from_step_name or '—'}» به مرحله «{target_step.name}» "
                    "منتقل شد و نیازمند اقدام شماست."
                ),
                workflow_instance=instance,
                workflow_step=target_step,
            )

        transaction.on_commit(
            lambda: WorkflowRealtimeService.notify_instance_changed(
                instance_id=instance.pk,
                workflow_id=instance.workflow_id,
                actor_id=performed_by.pk,
            )
        )

        return step_execution
