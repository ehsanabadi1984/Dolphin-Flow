from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .authorization import WorkflowAuthorizationService
from .models import (
    WorkflowStep,
    WorkflowInstanceEvent,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
)


class WorkflowStepAssignmentService:
    """Resolve and persist the assignee for an individual step execution."""

    @staticmethod
    def get_eligible_assignees(*, workflow, step):
        if not workflow or not step or step.workflow_id != workflow.pk:
            return []

        return WorkflowAuthorizationService.get_users_with_step_execute_permission(
            workflow=workflow,
            step=step,
        )

    @staticmethod
    def validate_assignee(*, workflow, step, assignee):
        if not workflow or not step or step.workflow_id != workflow.pk:
            raise ValidationError("مرحله انتخاب‌شده متعلق به این فرآیند نیست.")

        if not assignee or not getattr(assignee, "pk", None):
            raise ValidationError("مسئول مرحله مشخص نشده است.")

        if not getattr(assignee, "is_active", False):
            raise ValidationError("کاربر انتخاب‌شده غیرفعال است.")

        if not workflow.memberships.filter(
            user_id=assignee.pk,
            is_active=True,
        ).exists():
            raise ValidationError("کاربر انتخاب‌شده عضو فعال این فرآیند نیست.")

        eligible_ids = {
            user.pk
            for user in WorkflowStepAssignmentService.get_eligible_assignees(
                workflow=workflow,
                step=step,
            )
        }
        if assignee.pk not in eligible_ids:
            raise ValidationError(
                "کاربر انتخاب‌شده مجوز مؤثر EXECUTE برای این مرحله را ندارد."
            )

        return assignee

    @staticmethod
    def validate_policy_configuration(*, step):
        policy = step.assignment_policy
        source_step = step.assignment_source_step

        if policy == WorkflowStep.AssignmentPolicy.STEP_COMPLETER:
            if source_step is None:
                raise ValidationError(
                    "برای سیاست تکمیل‌کننده مرحله مرجع، انتخاب مرحله مرجع الزامی است."
                )
            if source_step.workflow_id != step.workflow_id:
                raise ValidationError(
                    "مرحله مرجع تخصیص باید متعلق به همان فرآیند باشد."
                )
        elif source_step is not None:
            raise ValidationError(
                "مرحله مرجع فقط برای سیاست تکمیل‌کننده مرحله مرجع قابل استفاده است."
            )

    @staticmethod
    def get_override_assignee_state(*, workflow, step, instance):
        """Return the assignee decision required for an administrative override."""
        if not workflow or not step or step.workflow_id != workflow.pk:
            raise ValidationError("مرحله مقصد متعلق به فرآیند مشخص‌شده نیست.")
        if not instance or instance.workflow_id != workflow.pk:
            raise ValidationError("نمونه فرآیند با فرآیند مرحله مقصد هم‌خوانی ندارد.")

        # The latest entry event is authoritative, including when its assignee
        # snapshot is empty or its user is no longer eligible. Never fall back
        # to an older assignee in that case.
        previous_event = (
            WorkflowInstanceEvent.objects
            .filter(instance=instance, workflow_step=step)
            .select_related("assigned_to")
            .order_by("-occurred_at", "-pk")
            .first()
        )
        if previous_event is not None:
            historical_assignee = previous_event.assigned_to
            latest_assignment = (
                WorkflowStepAssignmentHistory.objects
                .filter(
                    instance=instance,
                    workflow_step=step,
                    created_at__gte=previous_event.occurred_at,
                )
                .select_related("new_assignee")
                .order_by("-created_at", "-pk")
                .first()
            )
            if latest_assignment is not None:
                historical_assignee = latest_assignment.new_assignee

            if historical_assignee is None:
                return {
                    "required": True,
                    "assignee": None,
                    "reason": "آخرین ورود یا تغییر تخصیص این مرحله مسئول معتبر و قابل بازیابی ندارد.",
                }
            try:
                assignee = WorkflowStepAssignmentService.validate_assignee(
                    workflow=workflow,
                    step=step,
                    assignee=historical_assignee,
                )
            except ValidationError as exc:
                return {
                    "required": True,
                    "assignee": None,
                    "reason": str(exc),
                }
            return {"required": False, "assignee": assignee, "reason": ""}

        # Compatibility path for executions created before independent entry
        # events were introduced (or legacy fixtures/data not yet backfilled).
        previous_execution = (
            WorkflowStepExecution.objects
            .filter(instance=instance, workflow_step=step)
            .select_related("assigned_to")
            .order_by("-performed_at", "-pk")
            .first()
        )
        if previous_execution is not None:
            if previous_execution.assigned_to_id is None:
                return {
                    "required": True,
                    "assignee": None,
                    "reason": "اجرای تاریخی این مرحله مسئول مشخصی ندارد.",
                }
            try:
                assignee = WorkflowStepAssignmentService.validate_assignee(
                    workflow=workflow,
                    step=step,
                    assignee=previous_execution.assigned_to,
                )
            except ValidationError as exc:
                return {
                    "required": True,
                    "assignee": None,
                    "reason": str(exc),
                }
            return {"required": False, "assignee": assignee, "reason": ""}

        # A first-time entry follows the configured policy. Policies that
        # cannot determine one eligible user require an explicit admin choice.
        if step.assignment_policy == WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS:
            return {
                "required": True,
                "assignee": None,
                "reason": "این سیاست برای ورود از مسیر Override نیازمند انتخاب صریح مدیر است.",
            }
        try:
            assignee = WorkflowStepAssignmentService.resolve_assignee(
                workflow=workflow,
                step=step,
                instance=instance,
            )
        except ValidationError as exc:
            return {
                "required": True,
                "assignee": None,
                "reason": str(exc),
            }
        return {"required": False, "assignee": assignee, "reason": ""}

    @staticmethod
    def resolve_override_assignee(
        *,
        workflow,
        step,
        instance,
        selected_assignee=None,
    ):
        """Resolve and revalidate the assignee for an administrative override."""
        state = WorkflowStepAssignmentService.get_override_assignee_state(
            workflow=workflow,
            step=step,
            instance=instance,
        )
        if state["required"]:
            if selected_assignee is None:
                raise ValidationError(
                    state["reason"] or "برای اصلاح مسیر، انتخاب مسئول توسط Admin الزامی است."
                )
            return WorkflowStepAssignmentService.validate_assignee(
                workflow=workflow,
                step=step,
                assignee=selected_assignee,
            )

        resolved_assignee = state["assignee"]
        if (
            selected_assignee is not None
            and selected_assignee.pk != resolved_assignee.pk
        ):
            raise ValidationError(
                "برای ورود مجدد به این مرحله باید مسئول معتبر آخرین ورود حفظ شود."
            )
        return resolved_assignee

    @staticmethod
    def resolve_assignee(
        *,
        workflow,
        step,
        instance,
        previous_execution=None,
        selected_assignee=None,
    ):
        if not workflow or not step or step.workflow_id != workflow.pk:
            raise ValidationError("مرحله مقصد متعلق به فرآیند مشخص‌شده نیست.")
        if not instance or instance.workflow_id != workflow.pk:
            raise ValidationError("نمونه فرآیند با فرآیند مرحله مقصد هم‌خوانی ندارد.")

        WorkflowStepAssignmentService.validate_policy_configuration(step=step)
        policy = step.assignment_policy

        if policy == WorkflowStep.AssignmentPolicy.FIXED:
            assignee = step.assigned_to
            if assignee is None:
                raise ValidationError("برای این مرحله مسئول ثابت تعیین نشده است.")

        elif policy == WorkflowStep.AssignmentPolicy.INSTANCE_STARTER:
            assignee = instance.started_by
            if assignee is None:
                raise ValidationError("شروع‌کننده نمونه فرآیند مشخص نیست.")

        elif policy == WorkflowStep.AssignmentPolicy.STEP_COMPLETER:
            source_executions = WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=step.assignment_source_step,
                is_submitted=True,
            )
            if source_executions.filter(submitted_at__isnull=True).exists():
                raise ValidationError(
                    "زمان تکمیل یکی از نوبت‌های مرحله مرجع ثبت نشده و ترتیب آن‌ها قابل اثبات نیست."
                )

            if (
                previous_execution is not None
                and previous_execution.instance_id == instance.pk
                and previous_execution.workflow_step_id
                == step.assignment_source_step_id
                and (
                    not previous_execution.is_submitted
                    or previous_execution.submitted_at is None
                )
            ):
                raise ValidationError(
                    "نوبت اجرای مرحله مرجع تکمیل‌شده و دارای زمان ثبت نیست."
                )

            source_execution = (
                source_executions
                .filter(submitted_at__isnull=False)
                .select_related("completed_by")
                .order_by("-submitted_at", "-pk")
                .first()
            )

            if source_execution is None or source_execution.completed_by is None:
                raise ValidationError(
                    "آخرین نوبت تکمیل‌شده مرحله مرجع، تکمیل‌کننده ثبت‌شده ندارد."
                )
            assignee = source_execution.completed_by

        elif policy == WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS:
            if previous_execution is None:
                raise ValidationError("نوبت اجرای مبدأ برای انتخاب مسئول موجود نیست.")
            if previous_execution.instance_id != instance.pk:
                raise ValidationError("نوبت اجرای مبدأ متعلق به این نمونه فرآیند نیست.")
            if previous_execution.workflow_step.workflow_id != workflow.pk:
                raise ValidationError("مرحله مبدأ متعلق به این فرآیند نیست.")
            if previous_execution.completed_by_id is None:
                raise ValidationError("تکمیل‌کننده نوبت اجرای مبدأ مشخص نیست.")
            if selected_assignee is None:
                raise ValidationError("انتخاب مسئول مرحله مقصد الزامی است.")
            assignee = selected_assignee

        elif policy == WorkflowStep.AssignmentPolicy.AUTO_SINGLE:
            candidates = WorkflowStepAssignmentService.get_eligible_assignees(
                workflow=workflow,
                step=step,
            )
            if len(candidates) != 1:
                raise ValidationError(
                    "تخصیص خودکار فقط در صورت وجود دقیقاً یک مسئول واجد شرایط ممکن است."
                )
            assignee = candidates[0]

        else:
            raise ValidationError("سیاست تخصیص مسئول این مرحله معتبر نیست.")

        return WorkflowStepAssignmentService.validate_assignee(
            workflow=workflow,
            step=step,
            assignee=assignee,
        )

    @staticmethod
    @transaction.atomic
    def assign_execution(
        *,
        execution,
        assignee,
        changed_by=None,
        source=WorkflowStepAssignmentHistory.Source.POLICY,
        reason="",
    ):
        if source not in WorkflowStepAssignmentHistory.Source.values:
            raise ValidationError("منشأ تخصیص مسئول معتبر نیست.")
        if not execution or not getattr(execution, "pk", None):
            raise ValidationError("نوبت اجرای معتبری برای تخصیص ارائه نشده است.")

        locked_execution = (
            WorkflowStepExecution.objects
            .select_for_update()
            .select_related("workflow_step__workflow")
            .get(pk=execution.pk)
        )
        workflow = locked_execution.workflow_step.workflow
        step = locked_execution.workflow_step

        WorkflowStepAssignmentService.validate_assignee(
            workflow=workflow,
            step=step,
            assignee=assignee,
        )

        previous_assignee = locked_execution.assigned_to
        if (
            previous_assignee is not None
            and previous_assignee.pk == assignee.pk
            and locked_execution.assigned_at is not None
        ):
            execution.assigned_to = locked_execution.assigned_to
            execution.assigned_at = locked_execution.assigned_at
            return execution

        now = timezone.now()
        locked_execution.assigned_to = assignee
        locked_execution.assigned_at = now
        locked_execution.save(update_fields=["assigned_to", "assigned_at"])

        WorkflowStepAssignmentHistory.objects.create(
            step_execution=locked_execution,
            instance=locked_execution.instance,
            workflow_step=step,
            previous_assignee=previous_assignee,
            new_assignee=assignee,
            changed_by=changed_by,
            source=source,
            reason=reason or "",
        )

        execution.assigned_to = assignee
        execution.assigned_at = now
        return execution
