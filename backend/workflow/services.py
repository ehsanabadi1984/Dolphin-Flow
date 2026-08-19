from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .notification_services import NotificationService

from .authorization import WorkflowAuthorizationService
from .sla_services import SLAService
from .models import (
    FormData,
    WorkflowInstance,
    WorkflowPermission,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
    WorkflowMembership,
    Notification,
)


class WorkflowExecutionService:

    @staticmethod
    @transaction.atomic

    def start_workflow(
        *,
        workflow,
        user,
        data=None,
    ):
        """
        Start a new workflow instance.

        The instance starts at the first active workflow step.
        """

        # ---------------------------------------------------------
        # 1. Validate workflow
        # ---------------------------------------------------------

        if not workflow.is_active:
            raise ValidationError(
                "این Workflow فعال نیست."
            )

        # ---------------------------------------------------------
        # 2. Authorization
        # ---------------------------------------------------------

        WorkflowAuthorizationService.require_permission(
            user=user,
            workflow=workflow,
            action=WorkflowPermission.Action.EXECUTE,
        )

        # ---------------------------------------------------------
        # 3. Find the first active step
        # ---------------------------------------------------------

        first_step = (
            workflow.steps
            .filter(is_active=True)
            .order_by("order")
            .first()
        )

        if first_step is None:
            raise ValidationError(
                "این Workflow هیچ مرحله فعالی ندارد."
            )

        # ---------------------------------------------------------
        # 4. Create workflow instance
        # ---------------------------------------------------------

        instance = WorkflowInstance.objects.create(
            workflow=workflow,
            current_step=first_step,
            started_by=user,
            status=WorkflowInstance.Status.ACTIVE,
        )

        # ---------------------------------------------------------
        # 5. Record the first step execution
        # ---------------------------------------------------------

        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=first_step,
            performed_by=user,
            data=data or {},
        )

        SLAService.start_sla_if_configured(
            step_execution=step_execution,
        )

        return instance

    @staticmethod
    @transaction.atomic
    def execute_transition(
        *,
        instance,
        transition,
        user,
        notes="",
        data=None,
    ):
        """
        Execute a workflow transition for a workflow instance.

        All state changes and execution records are committed
        atomically.
        """

        # Lock the instance to prevent concurrent transitions.
        instance = (
            WorkflowInstance.objects
            .select_for_update()
            .get(pk=instance.pk)
        )

        # ---------------------------------------------------------
        # 1. Validate instance status
        # ---------------------------------------------------------

        if instance.status != WorkflowInstance.Status.ACTIVE:
            raise ValidationError(
                "این نمونه از فرآیند فعال نیست."
            )

        # ---------------------------------------------------------
        # 2. Validate transition
        # ---------------------------------------------------------

        if not transition.is_active:
            raise ValidationError(
                "این Transition فعال نیست."
            )

        # ---------------------------------------------------------
        # 3. Validate workflow consistency
        # ---------------------------------------------------------

        if transition.workflow_id != instance.workflow_id:
            raise ValidationError(
                "این Transition متعلق به Workflow این Instance نیست."
            )

        if (
            transition.from_step.workflow_id
            != instance.workflow_id
        ):
            raise ValidationError(
                "مرحله مبدأ متعلق به Workflow این Instance نیست."
            )

        if (
            transition.to_step.workflow_id
            != instance.workflow_id
        ):
            raise ValidationError(
                "مرحله مقصد متعلق به Workflow این Instance نیست."
            )

        # ---------------------------------------------------------
        # 4. Validate current step
        # ---------------------------------------------------------

        if instance.current_step_id != transition.from_step_id:
            raise ValidationError(
                "این Transition برای مرحله فعلی قابل اجرا نیست."
            )

        # ---------------------------------------------------------
        # 5. Validate current step form submission
        # ---------------------------------------------------------

        current_step_execution = (
            instance.step_executions
            .filter(
                workflow_step=instance.current_step,
            )
            .order_by("-performed_at")
            .first()
        )

        if current_step_execution is None:
            raise ValidationError(
                "اجرای مرحله فعلی این Workflow پیدا نشد."
            )

        if not current_step_execution.is_submitted:
            raise ValidationError(
                "ابتدا فرم این مرحله را ارسال کنید."
            )

        # ---------------------------------------------------------
        # 6. Authorization
        # ---------------------------------------------------------

        WorkflowAuthorizationService.require_permission(
            user=user,
            workflow=instance.workflow,
            action=WorkflowPermission.Action.TRANSITION,
            transition=transition,
        )

        # ---------------------------------------------------------
        # 6. Create transition execution record
        # ---------------------------------------------------------

        current_step_execution = (
            instance.step_executions
            .filter(
                workflow_step=instance.current_step,
                sla_started_at__isnull=False,
                sla_completed_at__isnull=True,
            )
            .order_by("-performed_at")
            .first()
        )

        if current_step_execution is None:
            raise ValidationError(
                "اجرای مرحله فعلی پیدا نشد."
            )

        if current_step_execution.is_submitted:
            raise ValidationError(
                "فرم این مرحله قبلاً ارسال شده است."
            )

        SLAService.complete_sla(
            step_execution=current_step_execution,
        )

        current_step_execution.is_submitted = True
        current_step_execution.submitted_at = timezone.now()

        current_step_execution.save(
            update_fields=[
                "is_submitted",
                "submitted_at",
            ]
        )

        transition_execution = WorkflowTransitionExecution.objects.create(
            instance=instance,
            transition=transition,
            performed_by=user,
            notes=notes,
            data=data or {},
        )

        # ---------------------------------------------------------
        # 7. Record arrival at the new step
        # ---------------------------------------------------------

        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=transition.to_step,
            performed_by=user,
            notes=notes,
            data=data or {},
        )

        SLAService.start_sla_if_configured(
            step_execution=step_execution,
        )

        # ---------------------------------------------------------
        # 8. Move instance to the destination step
        # ---------------------------------------------------------

        instance.current_step = transition.to_step

        # ---------------------------------------------------------
        # 9. Complete workflow if destination is the final step
        # ---------------------------------------------------------

        has_next_step = instance.workflow.steps.filter(
            is_active=True,
            order__gt=transition.to_step.order,
        ).exists()

        if not has_next_step:
            instance.status = WorkflowInstance.Status.COMPLETED
            instance.completed_at = timezone.now()

            instance.save(
                update_fields=[
                    "current_step",
                    "status",
                    "completed_at",
                ]
            )

        else:
            instance.save(
                update_fields=[
                    "current_step",
                ]
            )
            # ---------------------------------------------------------
            # 10. Notify executors of the destination step
            # ---------------------------------------------------------

            recipients = (
                instance.workflow.memberships
                .filter(
                    is_active=True,
                    role=WorkflowMembership.Role.EXECUTOR,
                    user__is_active=True,
                )
                .select_related("user")
            )

            for membership in recipients:
                NotificationService.create(
                    recipient=membership.user,
                    notification_type=(
                        Notification.NotificationType.STEP_ENTERED
                    ),
                    title=(
                        f"ورود فرآیند به مرحله "
                        f"«{transition.to_step.name}»"
                    ),
                    message=(
                        f"فرآیند «{instance.workflow.name}» "
                        f"به مرحله «{transition.to_step.name}» "
                        "وارد شد و نیاز به بررسی دارد."
                    ),
                    workflow_instance=instance,
                    workflow_step=transition.to_step,
                    transition_execution=transition_execution,
                )

        return transition_execution