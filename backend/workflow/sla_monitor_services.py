from django.utils import timezone

from .sla_services import SLAService
from .notification_services import NotificationService

from .models import (
    WorkflowStepExecution,
    Notification,
)


class SLAMonitorService:

    @staticmethod
    def notify_workflow_members(
        *,
        step_execution,
        notification_type,
    ):
        workflow = step_execution.workflow_step.workflow

        memberships = (
            workflow.memberships
            .filter(
                is_active=True,
                role__in=[
                    "EXECUTOR",
                    "MANAGER",
                ],
            )
            .select_related("user")
        )

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

        count = 0

        for membership in memberships:
            NotificationService.create(
                recipient=membership.user,
                notification_type=notification_type,
                title=title,
                message=message,
                workflow_instance=step_execution.instance,
                workflow_step=step_execution.workflow_step,
            )
            count += 1

        return count

    @staticmethod
    def process_active_slas(*, now=None):
        if now is None:
            now = timezone.now()

        executions = (
            WorkflowStepExecution.objects
            .filter(
                sla_started_at__isnull=False,
                sla_completed_at__isnull=True,
            )
            .select_related("workflow_step")
        )

        warning_count = 0
        breach_count = 0

        for execution in executions:
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
        return {
            "warning_count": warning_count,
            "breach_count": breach_count,
        }