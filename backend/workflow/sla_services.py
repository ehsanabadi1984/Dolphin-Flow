from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from .calendar_services import CalendarService
from .models import WorkflowStepSLA


class SLAService:

    @staticmethod
    def get_sla(*, step):
        try:
            return step.sla
        except WorkflowStepSLA.DoesNotExist:
            raise ValidationError(
                "برای این مرحله SLA تعریف نشده است."
            )

    @staticmethod
    def calculate_due_at(*, step, start):
        sla = SLAService.get_sla(step=step)

        if not sla.is_active:
            raise ValidationError(
                "SLA این مرحله فعال نیست."
            )

        if sla.duration <= timedelta(0):
            raise ValidationError(
                "مدت SLA باید بیشتر از صفر باشد."
            )

        return CalendarService.add_working_duration(
            calendar=sla.calendar,
            start=start,
            duration=sla.duration,
        )

    @staticmethod
    def calculate_warning_at(*, step, start):
        sla = SLAService.get_sla(step=step)

        if not sla.is_active:
            raise ValidationError(
                "SLA این مرحله فعال نیست."
            )

        if sla.warning_before is None:
            return None

        if sla.warning_before <= timedelta(0):
            return SLAService.calculate_due_at(
                step=step,
                start=start,
            )

        if sla.warning_before >= sla.duration:
            return start

        due_at = SLAService.calculate_due_at(
            step=step,
            start=start,
        )

        return CalendarService.subtract_working_duration(
            calendar=sla.calendar,
            end=due_at,
            duration=sla.warning_before,
        )

    @staticmethod
    def start_sla(*, step_execution, start=None):
        if start is None:
            start = timezone.now()

        if step_execution.sla_started_at is not None:
            return step_execution

        step = step_execution.workflow_step

        due_at = SLAService.calculate_due_at(
            step=step,
            start=start,
        )

        warning_at = SLAService.calculate_warning_at(
            step=step,
            start=start,
        )

        step_execution.sla_started_at = start
        step_execution.sla_due_at = due_at
        step_execution.sla_warning_at = warning_at

        step_execution.save(
            update_fields=[
                "sla_started_at",
                "sla_due_at",
                "sla_warning_at",
            ]
        )

        return step_execution
    
    @staticmethod
    def start_sla_if_configured(*, step_execution):
        try:
            step_execution.workflow_step.sla
        except WorkflowStepSLA.DoesNotExist:
            return step_execution

        return SLAService.start_sla(
            step_execution=step_execution,
            start=step_execution.performed_at,
        )

    @staticmethod
    def complete_sla(*, step_execution, completed_at=None):
        if step_execution.sla_started_at is None:
            return step_execution

        if step_execution.sla_completed_at is not None:
            return step_execution

        if completed_at is None:
            completed_at = timezone.now()

        step_execution.sla_completed_at = completed_at

        step_execution.save(
            update_fields=["sla_completed_at"]
        )

        return step_execution

    @staticmethod
    def mark_warning_sent(*, step_execution, sent_at=None):
        if step_execution.sla_warning_at is None:
            return step_execution

        if step_execution.sla_completed_at is not None:
            return step_execution

        if step_execution.sla_warning_sent_at is not None:
            return step_execution

        if sent_at is None:
            sent_at = timezone.now()

        step_execution.sla_warning_sent_at = sent_at

        step_execution.save(
            update_fields=["sla_warning_sent_at"]
        )

        return step_execution

    @staticmethod
    def mark_breached(*, step_execution, breached_at=None):
        if step_execution.sla_due_at is None:
            return step_execution

        if step_execution.sla_completed_at is not None:
            return step_execution

        if step_execution.sla_breached_at is not None:
            return step_execution

        if breached_at is None:
            breached_at = timezone.now()

        step_execution.sla_breached_at = breached_at

        step_execution.save(
            update_fields=["sla_breached_at"]
        )

        return step_execution

    @staticmethod
    def is_warning_due(*, step_execution, now=None):
        if now is None:
            now = timezone.now()

        if step_execution.sla_warning_at is None:
            return False

        if step_execution.sla_warning_sent_at is not None:
            return False
        
        if step_execution.sla_completed_at is not None:
            return False

        return now >= step_execution.sla_warning_at

    @staticmethod
    def check_breach(*, step_execution, now=None):
        if now is None:
            now = timezone.now()

        if step_execution.sla_due_at is None:
            return False

        if step_execution.sla_completed_at is not None:
            return False

        if step_execution.sla_breached_at is not None:
            return True

        if now < step_execution.sla_due_at:
            return False

        step_execution.sla_breached_at = now

        step_execution.save(
            update_fields=["sla_breached_at"]
        )

        return True
