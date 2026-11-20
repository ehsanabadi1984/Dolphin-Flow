from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .notification_services import (
    NotificationService,
    WorkflowTransitionNotificationService,
)

from .authorization import WorkflowAuthorizationService
from .sla_services import SLAService
from .realtime_services import WorkflowRealtimeService
from .models import (
    WorkflowInstance,
    WorkflowStep,
    WorkflowPermission,
    WorkflowStepExecution,
    WorkflowStepAssignmentHistory,
    WorkflowTransitionExecution,
    Notification,
)
from .form_draft_submit_services import FormDraftSubmitService
from .assignment_services import WorkflowStepAssignmentService


class WorkflowExecutionService:

    @staticmethod
    def _get_active_step_execution(*, instance):
        """
        Return the single actionable execution for the instance's current step.

        The caller must lock the WorkflowInstance before calling this helper.
        Locking the execution rows protects the selected execution while the
        surrounding transition transaction is in progress.
        """
        if instance.current_step_id is None:
            raise ValidationError(
                "این نمونه مرحله فعالی برای اجرا ندارد."
            )

        executions = list(
            instance.step_executions
            .select_for_update()
            .filter(
                workflow_step_id=instance.current_step_id,
                is_submitted=False,
            )
            .order_by("pk")[:2]
        )

        if not executions:
            raise ValidationError(
                "اجرای فعال و ارسال‌نشده‌ای برای مرحله فعلی پیدا نشد."
            )

        if len(executions) > 1:
            raise ValidationError(
                "برای مرحله فعلی بیش از یک اجرای فعال پیدا شد؛ "
                "ادامه عملیات ایمن نیست."
            )

        return executions[0]

    @staticmethod
    @transaction.atomic
    def accept_transition_execution(
        *,
        transition_execution,
        user,
    ):
        """
        Resolve a pending acceptance-required transition as accepted.
        """
        instance = (
            WorkflowInstance.objects
            .select_for_update()
            .get(pk=transition_execution.instance_id)
        )

        if instance.status != WorkflowInstance.Status.ACTIVE:
            raise ValidationError(
                "این نمونه از فرآیند فعال نیست."
            )

        transition_execution = (
            WorkflowTransitionExecution.objects
            .select_for_update()
            .select_related("transition")
            .get(pk=transition_execution.pk)
        )

        transition = transition_execution.transition

        if transition_execution.instance_id != instance.pk:
            raise ValidationError(
                "این Transition Execution متعلق به Instance دیگری است."
            )

        if transition.workflow_id != instance.workflow_id:
            raise ValidationError(
                "این Transition متعلق به Workflow این Instance نیست."
            )

        if not transition.is_active:
            raise ValidationError(
                "این Transition فعال نیست."
            )

        if not transition.requires_acceptance:
            raise ValidationError(
                "این Transition نیازمند تأیید نیست."
            )

        if transition.to_step is None:
            raise ValidationError(
                "Transition تأییدشونده باید مرحله مقصد داشته باشد."
            )

        if transition.to_step.workflow_id != instance.workflow_id:
            raise ValidationError(
                "مرحله مقصد متعلق به Workflow این Instance نیست."
            )

        if transition_execution.status != WorkflowTransitionExecution.Status.PENDING:
            raise ValidationError(
                "این Transition Execution قبلاً تعیین تکلیف شده است."
            )

        if instance.current_step_id != transition.from_step_id:
            raise ValidationError(
                "این Transition Execution دیگر مربوط به مرحله فعلی نیست."
            )

        WorkflowAuthorizationService.require_permission(
            user=user,
            workflow=instance.workflow,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            step=transition.to_step,
        )

        # Recover the latest submitted source execution preceding this
        # transition. Do not filter by completed_by: a missing completer must
        # become a notification issue, not block acceptance.
        previous_execution = (
            WorkflowStepExecution.objects
            .filter(
                instance=instance,
                workflow_step=transition.from_step,
                is_submitted=True,
                submitted_at__lte=transition_execution.performed_at,
            )
            .order_by("-submitted_at", "-pk")
            .first()
        )
        if previous_execution is None:
            raise ValidationError(
                "اجرای تکمیل‌شده مرحله مبدأ برای این درخواست پذیرش پیدا نشد."
            )

        manual_selection = (
            transition.to_step.assignment_policy
            == WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS
        )
        if manual_selection and transition_execution.proposed_assignee_id is None:
            raise ValidationError(
                "مسئول پیشنهادی مرحله مقصد برای این درخواست ثبت نشده است."
            )
        if (
            not manual_selection
            and transition_execution.proposed_assignee_id is not None
        ):
            raise ValidationError(
                "برای سیاست تخصیص این مرحله، مسئول پیشنهادی دستی مجاز نیست."
            )

        assignee = WorkflowStepAssignmentService.resolve_assignee(
            workflow=instance.workflow,
            step=transition.to_step,
            instance=instance,
            previous_execution=previous_execution,
            selected_assignee=(
                transition_execution.proposed_assignee
                if manual_selection else None
            ),
        )

        # Assignment is finalized only now, after the proposed/resolved user
        # has been revalidated against current membership and EXECUTE access.
        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=transition.to_step,
            performed_by=user,
            entered_by=user,
        )
        WorkflowStepAssignmentService.assign_execution(
            execution=step_execution,
            assignee=assignee,
            changed_by=user,
            source=WorkflowStepAssignmentHistory.Source.ACCEPTANCE,
            reason="تخصیص مسئول مقصد هنگام پذیرش انتقال",
        )

        transition_execution.status = (
            WorkflowTransitionExecution.Status.ACCEPTED
        )
        transition_execution.accepted_by = user
        transition_execution.rejected_by = None
        transition_execution.save(
            update_fields=[
                "status",
                "accepted_by",
                "rejected_by",
            ]
        )

        SLAService.start_sla_if_configured(
            step_execution=step_execution,
        )

        instance.current_step = transition.to_step
        instance.save(update_fields=["current_step"])

        # Resolve the ACCEPT recipient only after the destination execution
        # has been created, assigned, and the transition has been finalized.
        WorkflowTransitionNotificationService.notify_outcome(
            transition=transition,
            transition_execution=transition_execution,
            instance=instance,
            outcome="ACCEPT",
            source_execution=previous_execution,
            result_execution=step_execution,
        )

        transaction.on_commit(
            lambda: WorkflowRealtimeService.notify_instance_changed(
                instance_id=instance.pk,
                workflow_id=instance.workflow_id,
                actor_id=user.pk,
            )
        )

        return transition_execution

    @staticmethod
    @transaction.atomic
    def reject_transition_execution(
        *,
        transition_execution,
        user,
    ):
        """
        Resolve a pending acceptance-required transition as rejected.
        """
        instance = (
            WorkflowInstance.objects
            .select_for_update()
            .get(pk=transition_execution.instance_id)
        )

        if instance.status != WorkflowInstance.Status.ACTIVE:
            raise ValidationError(
                "این نمونه از فرآیند فعال نیست."
            )

        transition_execution = (
            WorkflowTransitionExecution.objects
            .select_for_update()
            .select_related("transition")
            .get(pk=transition_execution.pk)
        )

        transition = transition_execution.transition

        if transition_execution.instance_id != instance.pk:
            raise ValidationError(
                "این Transition Execution متعلق به Instance دیگری است."
            )

        if transition.workflow_id != instance.workflow_id:
            raise ValidationError(
                "این Transition متعلق به Workflow این Instance نیست."
            )

        if not transition.is_active:
            raise ValidationError(
                "این Transition فعال نیست."
            )

        if not transition.requires_acceptance:
            raise ValidationError(
                "این Transition نیازمند تأیید نیست."
            )

        if transition.to_step is None:
            raise ValidationError(
                "Transition تأییدشونده باید مرحله مقصد داشته باشد."
            )

        if transition.to_step.workflow_id != instance.workflow_id:
            raise ValidationError(
                "مرحله مقصد متعلق به Workflow این Instance نیست."
            )

        if transition_execution.status != WorkflowTransitionExecution.Status.PENDING:
            raise ValidationError(
                "این Transition Execution قبلاً تعیین تکلیف شده است."
            )

        if instance.current_step_id != transition.from_step_id:
            raise ValidationError(
                "این Transition Execution دیگر مربوط به مرحله فعلی نیست."
            )

        reject_to_step = transition.reject_to_step
        if reject_to_step is None:
            raise ValidationError(
                "برای رد این Transition مرحله بازگشت تنظیم نشده است."
            )

        if reject_to_step.workflow_id != instance.workflow_id:
            raise ValidationError(
                "مرحله بازگشت متعلق به Workflow این Instance نیست."
            )

        WorkflowAuthorizationService.require_permission(
            user=user,
            workflow=instance.workflow,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="REJECT",
            step=transition.to_step,
        )

        # Recover the latest submitted source execution preceding this
        # transition. Do not filter by completed_by: a missing completer must
        # become a notification issue, not block rejection.
        previous_execution = (
            WorkflowStepExecution.objects
            .filter(
                instance=instance,
                workflow_step=transition.from_step,
                is_submitted=True,
                submitted_at__lte=transition_execution.performed_at,
            )
            .order_by("-submitted_at", "-pk")
            .first()
        )
        if previous_execution is None:
            raise ValidationError(
                "اجرای تکمیل‌شده مرحله مبدأ برای این درخواست رد پیدا نشد."
            )

        assignee = WorkflowStepAssignmentService.resolve_assignee(
            workflow=instance.workflow,
            step=reject_to_step,
            instance=instance,
            previous_execution=previous_execution,
        )

        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=reject_to_step,
            performed_by=user,
            entered_by=user,
        )
        WorkflowStepAssignmentService.assign_execution(
            execution=step_execution,
            assignee=assignee,
            changed_by=user,
            source=WorkflowStepAssignmentHistory.Source.POLICY,
            reason="تخصیص مسئول مرحله بازگشت پس از رد انتقال",
        )

        transition_execution.status = (
            WorkflowTransitionExecution.Status.REJECTED
        )
        transition_execution.accepted_by = None
        transition_execution.rejected_by = user
        transition_execution.save(
            update_fields=[
                "status",
                "accepted_by",
                "rejected_by",
            ]
        )

        SLAService.start_sla_if_configured(
            step_execution=step_execution,
        )

        instance.current_step = reject_to_step
        instance.save(update_fields=["current_step"])

        # Resolve the REJECT recipient only after the return execution
        # has been created, assigned, and the transition has been finalized.
        WorkflowTransitionNotificationService.notify_outcome(
            transition=transition,
            transition_execution=transition_execution,
            instance=instance,
            outcome="REJECT",
            source_execution=previous_execution,
            result_execution=step_execution,
        )

        transaction.on_commit(
            lambda: WorkflowRealtimeService.notify_instance_changed(
                instance_id=instance.pk,
                workflow_id=instance.workflow_id,
                actor_id=user.pk,
            )
        )

        return transition_execution

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

        assignee = WorkflowStepAssignmentService.resolve_assignee(
            workflow=workflow,
            step=first_step,
            instance=instance,
        )

        step_execution = WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=first_step,
            performed_by=user,
            entered_by=user,
        )

        WorkflowStepAssignmentService.assign_execution(
            execution=step_execution,
            assignee=assignee,
            changed_by=user,
            source=WorkflowStepAssignmentHistory.Source.INITIAL,
            reason="تخصیص اولیه هنگام شروع فرآیند",
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
        selected_assignee=None,
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
            WorkflowExecutionService._get_active_step_execution(
                instance=instance,
            )
        )

        if current_step_execution.assigned_to_id != user.pk:
            raise ValidationError(
                "فقط مسئول اجرای فعال این مرحله می‌تواند فرم را ارسال و فرآیند را منتقل کند."
            )

        WorkflowStepAssignmentService.validate_assignee(
            workflow=instance.workflow,
            step=instance.current_step,
            assignee=user,
        )

        WorkflowAuthorizationService.require_permission(
            user=user,
            workflow=instance.workflow,
            action=WorkflowPermission.Action.TRANSITION,
            transition=transition,
        )

        form = getattr(instance.workflow, "form_definition", None)

        if form is not None:
            FormDraftSubmitService.validate(
                instance=instance,
                form=form,
                user=user,
            )

        from .history_services import HistoryService

        history_snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=user,
        )

        now = timezone.now()

        current_step_execution.completed_by = user
        current_step_execution.is_submitted = True
        current_step_execution.submitted_at = now
        current_step_execution.data = {
            "history": history_snapshot,
        }

        current_step_execution.save(
            update_fields=[
                "completed_by",
                "is_submitted",
                "submitted_at",
                "data",
            ]
        )

        SLAService.complete_sla(
            step_execution=current_step_execution,
        )

        manual_destination = (
            not is_finish
            and transition.to_step.assignment_policy
            == WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS
        )
        if selected_assignee is not None and not manual_destination:
            raise ValidationError(
                "انتخاب مسئول دستی برای سیاست تخصیص این مرحله مجاز نیست."
            )

        manually_resolved_assignee = None
        if manual_destination:
            manually_resolved_assignee = (
                WorkflowStepAssignmentService.resolve_assignee(
                    workflow=instance.workflow,
                    step=transition.to_step,
                    instance=instance,
                    previous_execution=current_step_execution,
                    selected_assignee=selected_assignee,
                )
            )

        transition_execution = WorkflowTransitionExecution.objects.create(
            instance=instance,
            transition=transition,
            performed_by=user,
            notes=notes,
            data=data or {},
            proposed_assignee=(
                manually_resolved_assignee
                if transition.requires_acceptance and manual_destination
                else None
            ),
            status=(
                WorkflowTransitionExecution.Status.PENDING
                if transition.requires_acceptance
                else WorkflowTransitionExecution.Status.ACCEPTED
            ),
        )

        from .file_share_services import FileShareDraftService
        FileShareDraftService.finalize_for_submit(
            instance=instance,
            step=instance.current_step,
            sender=user,
            transition_execution=transition_execution,
            form_snapshot=history_snapshot,
        )

        if transition.requires_acceptance:
            acceptance_users = {
                recipient.pk: recipient
                for action_code in ("ACCEPT", "REJECT")
                for recipient in WorkflowAuthorizationService.get_users_with_step_action_permission(
                    workflow=instance.workflow,
                    step=transition.to_step,
                    action_code=action_code,
                )
                if recipient != user
            }

            for recipient in acceptance_users.values():
                NotificationService.create(
                    recipient=recipient,
                    notification_type=(
                        Notification.NotificationType.ACTION_REQUIRED
                    ),
                    title="نیاز به تأیید دریافت",
                    message=(
                        f"فرآیند «{instance.workflow.name}» "
                        f"در انتظار تعیین تکلیف در مرحله "
                        f"«{transition.to_step.name}» است."
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
            assignee = (
                manually_resolved_assignee
                if manual_destination
                else WorkflowStepAssignmentService.resolve_assignee(
                    workflow=instance.workflow,
                    step=transition.to_step,
                    instance=instance,
                    previous_execution=current_step_execution,
                )
            )

            step_execution = WorkflowStepExecution.objects.create(
                instance=instance,
                workflow_step=transition.to_step,
                performed_by=user,
                entered_by=user,
            )

            WorkflowStepAssignmentService.assign_execution(
                execution=step_execution,
                assignee=assignee,
                changed_by=user,
                source=(
                    WorkflowStepAssignmentHistory.Source.MANUAL
                    if manual_destination
                    else WorkflowStepAssignmentHistory.Source.POLICY
                ),
                reason=(
                    "انتخاب مسئول مقصد توسط تکمیل‌کننده مرحله مبدأ"
                    if manual_destination
                    else "تخصیص مسئول هنگام ورود به مرحله"
                ),
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

            recipient = assignee

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
