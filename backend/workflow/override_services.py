from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    Notification,
    WorkflowInstance,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
)
from .assignment_services import WorkflowStepAssignmentService
from .notification_services import NotificationService
from .realtime_services import WorkflowRealtimeService
from .sla_services import SLAService
from .instance_event_services import WorkflowInstanceEventService


class WorkflowOverrideService:
    """Administrative correction of a workflow instance's current step."""

    MIN_REASON_LENGTH = 5
    OVERRIDE_NOTE_PREFIX = "اصلاح مسیر فرآیند:"

    @staticmethod
    @transaction.atomic
    def override_instance_step(
        *,
        instance,
        target_step,
        performed_by,
        reason,
        selected_assignee=None,
    ):
        # Lock only the WorkflowInstance row. current_step is nullable, so
        # select_related("current_step") would introduce a LEFT OUTER JOIN
        # that PostgreSQL cannot combine with FOR UPDATE.
        instance = (
            WorkflowInstance.objects
            .select_for_update()
            .select_related("workflow")
            .get(pk=instance.pk)
        )

        if not performed_by.is_active or not performed_by.is_staff:
            raise ValidationError(
                "فقط کاربران فعال Admin می‌توانند مسیر فرآیند را اصلاح کنند."
            )

        reason = (reason or "").strip()
        if len(reason) < WorkflowOverrideService.MIN_REASON_LENGTH:
            raise ValidationError(
                "دلیل اصلاح مسیر الزامی است و باید حداقل ۵ کاراکتر باشد."
            )

        if target_step is None:
            raise ValidationError("مرحله مقصد باید مشخص شود.")

        if target_step.workflow_id != instance.workflow_id:
            raise ValidationError(
                "مرحله مقصد متعلق به Workflow این Instance نیست."
            )

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
        from_step_name = from_step.name if from_step else "—"

        # Preserve the entry snapshot before removing an unfinished execution.
        # Submitted executions represent completed work and must remain intact.
        if from_step is not None:
            unfinished = list(
                WorkflowStepExecution.objects
                .select_for_update(of=("self",))
                .filter(
                    instance=instance,
                    workflow_step=from_step,
                    is_submitted=False,
                )
                .select_related(
                    "entered_by", "performed_by", "assigned_to", "completed_by",
                )
            )
            if len(unfinished) > 1:
                raise ValidationError(
                    "برای مرحله فعلی بیش از یک اجرای ارسال‌نشده وجود دارد؛ اصلاح مسیر متوقف شد."
                )
            if unfinished:
                WorkflowInstanceEventService.record_step_entry(
                    execution=unfinished[0],
                    actor=unfinished[0].entered_by or unfinished[0].performed_by,
                )

        pending_transitions = []
        if from_step is not None:
            pending_transitions = list(
                WorkflowTransitionExecution.objects
                .select_for_update()
                .filter(
                    instance=instance,
                    transition__from_step=from_step,
                    status=WorkflowTransitionExecution.Status.PENDING,
                )
            )
            if pending_transitions:
                pending_ids = [item.pk for item in pending_transitions]
                WorkflowTransitionExecution.objects.filter(
                    pk__in=pending_ids,
                ).update(
                    status=WorkflowTransitionExecution.Status.SUPERSEDED,
                    resolved_at=now,
                )
                Notification.objects.filter(
                    workflow_instance=instance,
                    transition_execution_id__in=pending_ids,
                    notification_type=Notification.NotificationType.ACTION_REQUIRED,
                    is_read=False,
                ).update(is_read=True, read_at=now)

            # An action-required notification for the step being left is stale.
            Notification.objects.filter(
                workflow_instance=instance,
                workflow_step=from_step,
                notification_type=Notification.NotificationType.ACTION_REQUIRED,
                is_read=False,
            ).update(is_read=True, read_at=now)
        override_note = (
            f"{WorkflowOverrideService.OVERRIDE_NOTE_PREFIX} "
            f"{from_step_name} → {target_step.name} | "
            f"دلیل: {reason}"
        )

        assignee = WorkflowStepAssignmentService.resolve_override_assignee(
            workflow=instance.workflow,
            step=target_step,
            instance=instance,
            selected_assignee=selected_assignee,
        )

        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=target_step,
            performed_by=performed_by,
            entered_by=performed_by,
            performed_at=now,
            notes=override_note,
            data={
                "override": {
                    "version": 1,
                    "from_step_id": from_step.pk if from_step else None,
                    "from_step_name": from_step_name,
                    "to_step_id": target_step.pk,
                    "to_step_name": target_step.name,
                    "reason": reason,
                }
            },
            is_submitted=False,
        )

        WorkflowStepAssignmentService.assign_execution(
            execution=step_execution,
            assignee=assignee,
            changed_by=performed_by,
            source=WorkflowStepAssignmentHistory.Source.OVERRIDE,
            reason=reason,
        )
        SLAService.start_sla_if_configured(
            step_execution=step_execution,
        )

        WorkflowInstanceEventService.record_step_entry(
            execution=step_execution,
            actor=performed_by,
            event_type="OVERRIDE",
        )

        instance.current_step = target_step

        update_fields = ["current_step"]

        if instance.status == WorkflowInstance.Status.COMPLETED:
            instance.status = WorkflowInstance.Status.ACTIVE
            instance.completed_at = None
            update_fields.extend(["status", "completed_at"])

        instance.save(update_fields=update_fields)

        # The event and assignment history are now independent of the execution.
        # Remove only the unfinished execution of the step being left.
        if from_step is not None and unfinished:
            unfinished[0].delete()

        recipient = step_execution.assigned_to
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
                    f"«{from_step_name}» به مرحله «{target_step.name}» "
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
