from django.db import models, transaction
from django.utils import timezone

from .sla_services import SLAService
from .notification_services import NotificationService
from .realtime_services import WorkflowRealtimeService

from .models import (
    WorkflowStepExecution,
    WorkflowInstance,
    Notification,
)


class SLAMonitorService:

    @staticmethod
    def notify_workflow_members(
        *,
        step_execution,
        notification_type,
    ):
        responsible_user = step_execution.workflow_step.assigned_to

        if (
            responsible_user is None
            or not responsible_user.is_active
        ):
            return 0

        if notification_type == Notification.NotificationType.SLA_WARNING:
            title = "هشدار SLA"
            message = (
                f"زمان SLA مرحله «"
                f"{step_execution.workflow_step.name}"
                f"» رو به پایان است."
            )

        elif notification_type == Notification.NotificationType.SLA_BREACHED:
            title = "نقض SLA"
            message = (
                f"SLA مرحله «"
                f"{step_execution.workflow_step.name}"
                f"» نقض شده است."
            )

        else:
            return 0

        NotificationService.create(
            recipient=responsible_user,
            notification_type=notification_type,
            title=title,
            message=message,
            workflow_instance=step_execution.instance,
            workflow_step=step_execution.workflow_step,
        )

        return 1

    @staticmethod
    def process_active_slas(*, now=None):
        if now is None:
            now = timezone.now()

        executions = (
            WorkflowStepExecution.objects
            .filter(
                instance__isnull=False,
                instance__status=WorkflowInstance.Status.ACTIVE,
                instance__current_step_id=models.F("workflow_step_id"),
                sla_started_at__isnull=False,
                sla_completed_at__isnull=True,
                is_submitted=False,
            )
            .select_related(
                "workflow_step",
                "workflow_step__workflow",
                "workflow_step__assigned_to",
                "instance",
            )
        )

        warning_count = 0
        breach_count = 0

        for execution in executions:
            with transaction.atomic():
                # WorkflowExecutionService locks the instance first and then
                # the step execution when a transition is executed. Lock in
                # the same order here so a transition finishing at the SLA
                # boundary cannot race the monitor into sending a notification.
                instance = (
                    WorkflowInstance.objects
                    .select_for_update()
                    .get(pk=execution.instance_id)
                )

                execution = (
                    WorkflowStepExecution.objects
                    .select_for_update()
                    .select_related(
                        "workflow_step",
                        "workflow_step__workflow",
                        "workflow_step__assigned_to",
                        "instance",
                    )
                    .get(pk=execution.pk)
                )

                if (
                    instance.status != WorkflowInstance.Status.ACTIVE
                    or instance.current_step_id != execution.workflow_step_id
                    or execution.is_submitted
                    or execution.sla_completed_at is not None
                ):
                    continue

                if SLAService.is_warning_due(
                    step_execution=execution,
                    now=now,
                ):
                    SLAMonitorService.notify_workflow_members(
                        step_execution=execution,
                        notification_type=Notification.NotificationType.SLA_WARNING,
                    )

                    SLAService.mark_warning_sent(
                        step_execution=execution,
                        sent_at=now,
                    )

                    warning_count += 1

                    transaction.on_commit(
                        lambda instance_id=execution.instance_id, workflow_id=execution.workflow_step.workflow_id: WorkflowRealtimeService.notify_instance_changed(
                            instance_id=instance_id,
                            workflow_id=workflow_id,
                        )
                    )

                if (
                    execution.sla_breached_at is None
                    and SLAService.check_breach(
                        step_execution=execution,
                        now=now,
                    )
                ):
                    SLAMonitorService.notify_workflow_members(
                        step_execution=execution,
                        notification_type=Notification.NotificationType.SLA_BREACHED,
                    )

                    breach_count += 1

                    transaction.on_commit(
                        lambda instance_id=execution.instance_id, workflow_id=execution.workflow_step.workflow_id: WorkflowRealtimeService.notify_instance_changed(
                            instance_id=instance_id,
                            workflow_id=workflow_id,
                        )
                    )

        return {
            "warning_count": warning_count,
            "breach_count": breach_count,
        }
