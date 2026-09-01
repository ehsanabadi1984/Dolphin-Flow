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
        # 5. Create the first step execution (open)
        # ---------------------------------------------------------

        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=first_step,
            performed_by=user,
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

        Handles both normal transitions (to_step != NULL) and
        Finish transitions (to_step == NULL) that complete the
        workflow.

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

        # Validate to_step workflow (only for normal transitions)
        is_finish = transition.to_step is None

        if (
            not is_finish
            and transition.to_step.workflow_id
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
        # 5. Validate current step execution
        # ---------------------------------------------------------

        current_step_execution = (
            instance.step_executions
            .select_for_update()
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

        if current_step_execution.is_submitted:
            raise ValidationError(
                "فرم این مرحله قبلاً ارسال شده است."
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
        # 7. Validate saved form data (only if workflow has a form)
        # ---------------------------------------------------------

        has_form_definition = hasattr(
            instance.workflow, 'form_definition'
        )

        if has_form_definition:
            form_data = (
                FormData.objects
                .filter(instance=instance)
                .first()
            )

            if form_data is None:
                raise ValidationError(
                    "اطلاعات فرم هنوز ذخیره نشده است."
                )

            # Check for saved data: normal form data or device data
            has_form_data = bool(form_data.data)
            has_device_data = (
                instance.instance_devices
                .filter(is_active=True)
                .exists()
            )

            if not has_form_data and not has_device_data:
                raise ValidationError(
                    "ابتدا اطلاعات فرم یا دستگاه را ذخیره کنید."
                )

        # ---------------------------------------------------------
        # 8. Finalize current step
        # ---------------------------------------------------------

        # Preserve the form and device values as they exist at the
        # moment this step is finalized. The timeline must later read
        # this immutable snapshot, not current form or device data.
        from .form_services import DynamicFormService

        history_snapshot = DynamicFormService._build_history_snapshot(
            instance=instance,
            user=user,
        )

        now = timezone.now()

        current_step_execution.is_submitted = True
        current_step_execution.submitted_at = now
        current_step_execution.data = {
            "history": history_snapshot,
        }

        current_step_execution.save(
            update_fields=[
                "is_submitted",
                "submitted_at",
                "data",
            ]
        )

        # ---------------------------------------------------------
        # 9. Complete SLA for current step
        # ---------------------------------------------------------

        SLAService.complete_sla(
            step_execution=current_step_execution,
        )

        # ---------------------------------------------------------
        # 10. Create transition execution record
        # ---------------------------------------------------------

        transition_execution = WorkflowTransitionExecution.objects.create(
            instance=instance,
            transition=transition,
            performed_by=user,
            notes=notes,
            data=data or {},
        )

        # ---------------------------------------------------------
        # 11. Handle Finish vs Normal transition
        # ---------------------------------------------------------

        if is_finish:
            # FINISH TRANSITION: Complete the workflow
            instance.status = WorkflowInstance.Status.COMPLETED
            instance.completed_at = now
            instance.current_step = None

            instance.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "current_step",
                ]
            )

            # Send workflow completed notification
            NotificationService.create(
                recipient=user,
                notification_type=(
                    Notification.NotificationType.WORKFLOW_COMPLETED
                ),
                title=(
                    f"فرآیند «{instance.workflow.name}» تکمیل شد"
                ),
                message=(
                    f"فرآیند «{instance.workflow.name}» با موفقیت تکمیل شد."
                ),
                workflow_instance=instance,
                transition_execution=transition_execution,
            )
        else:
            # NORMAL TRANSITION: Move to next step

            # Create next step execution
            step_execution = WorkflowStepExecution.objects.create(
                instance=instance,
                workflow_step=transition.to_step,
                performed_by=user,
            )

            SLAService.start_sla_if_configured(
                step_execution=step_execution,
            )

            # Move instance to the destination step
            instance.current_step = transition.to_step

            instance.save(
                update_fields=[
                    "current_step",
                ]
            )

            # Notify executors of the destination step
            recipient = transition.to_step.assigned_to

            if (
                recipient
                and recipient.is_active
                and recipient != user
            ):
                NotificationService.create(
                    recipient=recipient,
                    notification_type=(
                        Notification.NotificationType.ACTION_REQUIRED
                    ),
                    title=(
                        f" فرآیند جدید  "
                        f"«{instance.workflow.name}»"
                    ),
                    message=(
                        f"فرآیند «{instance.workflow.name}» "
                        f"وارد مرحله «{transition.to_step.name}» شده "
                        "و نیازمند اقدام شماست."
                    ),
                    workflow_instance=instance,
                    workflow_step=transition.to_step,
                    transition_execution=transition_execution,
                )

        return transition_execution
