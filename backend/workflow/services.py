from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .notification_services import NotificationService

from .authorization import WorkflowAuthorizationService
from .sla_services import SLAService
from .realtime_services import WorkflowRealtimeService
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

        if not workflow.is_active:
            raise ValidationError(
                "این Workflow فعال نیست."
            )

        WorkflowAuthorizationService.require_permission(
            user=user,
            workflow=workflow,
            action=WorkflowPermission.Action.START,
        )

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

        instance = WorkflowInstance.objects.create(
            workflow=workflow,
            current_step=first_step,
            started_by=user,
            status=WorkflowInstance.Status.ACTIVE,
        )

        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=first_step,
            performed_by=user,
        )

        SLAService.start_sla_if_configured(
            step_execution=step_execution,
        )

        transaction.on_commit(
            lambda: WorkflowRealtimeService.notify_instance_changed(
                instance_id=instance.pk,
                workflow_id=workflow.pk,
                actor_id=user.pk,
            )
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

        instance = (
            WorkflowInstance.objects
            .select_for_update()
            .get(pk=instance.pk)
        )

        if instance.status != WorkflowInstance.Status.ACTIVE:
            raise ValidationError(
                "این نمونه از فرآیند فعال نیست."
            )

        if not transition.is_active:
            raise ValidationError(
                "این Transition فعال نیست."
            )

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

        is_finish = transition.to_step is None

        if (
            not is_finish
            and transition.to_step.workflow_id
            != instance.workflow_id
        ):
            raise ValidationError(
                "مرحله مقصد متعلق به Workflow این Instance نیست."
            )

        if instance.current_step_id != transition.from_step_id:
            raise ValidationError(
                "این Transition برای مرحله فعلی قابل اجرا نیست."
            )

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

        WorkflowAuthorizationService.require_permission(
            user=user,
            workflow=instance.workflow,
            action=WorkflowPermission.Action.TRANSITION,
            transition=transition,
        )

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

        SLAService.complete_sla(
            step_execution=current_step_execution,
        )

        transition_execution = WorkflowTransitionExecution.objects.create(
            instance=instance,
            transition=transition,
            performed_by=user,
            notes=notes,
            data=data or {},
        )

        if is_finish:
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
            step_execution = WorkflowStepExecution.objects.create(
                instance=instance,
                workflow_step=transition.to_step,
                performed_by=user,
            )

            SLAService.start_sla_if_configured(
                step_execution=step_execution,
            )

            instance.current_step = transition.to_step

            instance.save(
                update_fields=[
                    "current_step",
                ]
            )

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

        transaction.on_commit(
            lambda: WorkflowRealtimeService.notify_instance_changed(
                instance_id=instance.pk,
                workflow_id=instance.workflow_id,
                actor_id=user.pk,
            )
        )

        return transition_execution
