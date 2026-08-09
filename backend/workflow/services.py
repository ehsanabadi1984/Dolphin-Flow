from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    WorkflowInstance,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
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
        # 2. Validate workflow membership
        # ---------------------------------------------------------

        is_member = workflow.memberships.filter(
            user=user,
            is_active=True,
        ).exists()

        if not is_member:
            raise PermissionDenied(
                "کاربر عضو این فرآیند نیست."
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

        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=first_step,
            performed_by=user,
            data=data or {},
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
        # 5. Validate workflow membership
        # ---------------------------------------------------------

        is_member = instance.workflow.memberships.filter(
            user=user,
            is_active=True,
        ).exists()

        if not is_member:
            raise PermissionDenied(
                "کاربر عضو این فرآیند نیست."
            )

        # ---------------------------------------------------------
        # 6. Create transition execution record
        # ---------------------------------------------------------

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

        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=transition.to_step,
            performed_by=user,
            notes=notes,
            data=data or {},
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

        return transition_execution