from datetime import datetime, time, timedelta
from django.contrib.auth import get_user_model

from django.test import TestCase
from django.utils import timezone

from workflow.models import (
    BusinessCalendar,
    CalendarException,
    WeeklySchedule,
    WorkingInterval,
    Workflow,
    WorkflowStep,
    WorkflowStepSLA,
    WorkflowStepExecution,
)
from workflow.sla_services import SLAService


class SLAServiceTests(TestCase):

    def setUp(self):

        User = get_user_model()

        self.user = User.objects.create_user(
            username="sla_test_user",
            password="test-password",
        )

        self.calendar = BusinessCalendar.objects.create(
            name="SLA Test Calendar",
            timezone="Asia/Tehran",
            is_active=True,
        )

        # Monday تا Wednesday + Saturday و Sunday کاری
        # Thursday و Friday غیرکاری
        for weekday in WeeklySchedule.Weekday:
            is_working = weekday.value not in [
                WeeklySchedule.Weekday.THURSDAY,
                WeeklySchedule.Weekday.FRIDAY,
            ]

            schedule = WeeklySchedule.objects.create(
                calendar=self.calendar,
                weekday=weekday.value,
                is_working=is_working,
            )

            if is_working:
                WorkingInterval.objects.create(
                    weekly_schedule=schedule,
                    start_time=time(8, 0),
                    end_time=time(13, 0),
                )

                WorkingInterval.objects.create(
                    weekly_schedule=schedule,
                    start_time=time(13, 30),
                    end_time=time(16, 30),
                )

        self.workflow = Workflow.objects.create(
            name="SLA Test Workflow",
            code="SLA_TEST_WORKFLOW",
            is_active=True,
        )

        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="SLA Test Step",
            code="SLA_TEST_STEP",
            order=1,
            is_active=True,
        )

    def create_sla(
        self,
        *,
        duration,
        warning_before=None,
    ):
        return WorkflowStepSLA.objects.create(
            step=self.step,
            calendar=self.calendar,
            duration=duration,
            warning_before=warning_before,
            is_active=True,
        )

    def make_datetime(
        self,
        year,
        month,
        day,
        hour,
        minute=0,
    ):
        return timezone.make_aware(
            datetime(
                year,
                month,
                day,
                hour,
                minute,
            )
        )

    def test_calculates_due_at_inside_working_interval(self):
        self.create_sla(
            duration=timedelta(hours=2),
        )

        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        result = SLAService.calculate_due_at(
            step=self.step,
            start=start,
        )

        self.assertEqual(
            result,
            self.make_datetime(
                2026,
                8,
                15,
                12,
            ),
        )

    def test_calculates_due_at_across_lunch_break(self):
        self.create_sla(
            duration=timedelta(hours=2),
        )

        start = self.make_datetime(
            2026,
            8,
            15,
            12,
        )

        result = SLAService.calculate_due_at(
            step=self.step,
            start=start,
        )

        self.assertEqual(
            result,
            self.make_datetime(
                2026,
                8,
                15,
                14,
                30,
            ),
        )

    def test_calculates_due_at_across_non_working_days(self):
        self.create_sla(
            duration=timedelta(hours=2),
        )

        # Saturday 16:00
        # Saturday remaining: 30 minutes
        # Sunday: 1h30m
        start = self.make_datetime(
            2026,
            8,
            15,
            16,
        )

        result = SLAService.calculate_due_at(
            step=self.step,
            start=start,
        )

        self.assertEqual(
            result,
            self.make_datetime(
                2026,
                8,
                16,
                9,
                30,
            ),
        )

    def test_calculates_due_at_when_start_is_non_working(self):
        self.create_sla(
            duration=timedelta(hours=1),
        )

        # 13:00 is the lunch break.
        start = self.make_datetime(
            2026,
            8,
            15,
            13,
        )

        result = SLAService.calculate_due_at(
            step=self.step,
            start=start,
        )

        self.assertEqual(
            result,
            self.make_datetime(
                2026,
                8,
                15,
                14,
                30,
            ),
        )

    def test_calculates_warning_at(self):
        self.create_sla(
            duration=timedelta(hours=4),
            warning_before=timedelta(hours=1),
        )

        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        result = SLAService.calculate_due_at(
            step=self.step,
            start=start,
        )

        warning_at = SLAService.calculate_warning_at(
            step=self.step,
            start=start,
        )

        self.assertEqual(
            result,
            self.make_datetime(
                2026,
                8,
                15,
                14,
                30,
            ),
        )

        self.assertEqual(
            warning_at,
            self.make_datetime(
                2026,
                8,
                15,
                13,
                30,
            ),
        )

    def test_non_working_exception_is_respected(self):
        self.create_sla(
            duration=timedelta(hours=1),
        )

        CalendarException.objects.create(
            calendar=self.calendar,
            date=datetime(
                2026,
                8,
                15,
            ).date(),
            status=CalendarException.Status.NON_WORKING,
            title="Holiday",
        )

        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        result = SLAService.calculate_due_at(
            step=self.step,
            start=start,
        )

        self.assertEqual(
            result,
            self.make_datetime(
                2026,
                8,
                16,
                9,
            ),
        )

    def test_complete_sla_sets_completed_at(self):
        self.create_sla(
            duration=timedelta(hours=4),
            warning_before=timedelta(hours=1),
        )

        start = self.make_datetime(
            2026, 8, 15, 10,
        )

        self.step_execution = WorkflowStepExecution.objects.create(
            workflow_step=self.step,
            performed_by=self.user,
            sla_started_at=start,
            sla_due_at=SLAService.calculate_due_at(
                step=self.step,
                start=start,
            ),
            sla_warning_at=SLAService.calculate_warning_at(
                step=self.step,
                start=start,
            ),
        )

        completed_at = self.make_datetime(
            2026, 8, 15, 14, 0,
        )

        result = SLAService.complete_sla(
            step_execution=self.step_execution,
            completed_at=completed_at,
        )

        self.assertEqual(
            result.sla_completed_at,
            completed_at,
        )

    def test_completed_sla_is_not_warning_due(self):
        self.create_sla(
            duration=timedelta(hours=4),
            warning_before=timedelta(hours=1),
        )

        start = self.make_datetime(
            2026, 8, 15, 10,
        )

        self.step_execution = WorkflowStepExecution.objects.create(
            workflow_step=self.step,
            performed_by=self.user,
            sla_started_at=start,
            sla_warning_at=SLAService.calculate_warning_at(
                step=self.step,
                start=start,
            ),
        )

        SLAService.complete_sla(
            step_execution=self.step_execution,
            completed_at=self.make_datetime(
                2026, 8, 15, 14,
            ),
        )

        result = SLAService.is_warning_due(
            step_execution=self.step_execution,
            now=self.make_datetime(
                2026, 8, 15, 15,
            ),
        )

        self.assertFalse(result)

    def test_completed_sla_is_not_breached(self):
        self.create_sla(
            duration=timedelta(hours=4),
            warning_before=timedelta(hours=1),
        )

        start = self.make_datetime(
            2026, 8, 15, 10,
        )

        self.step_execution = WorkflowStepExecution.objects.create(
            workflow_step=self.step,
            performed_by=self.user,
            sla_started_at=start,
            sla_due_at=SLAService.calculate_due_at(
                step=self.step,
                start=start,
            ),
        )

        SLAService.complete_sla(
            step_execution=self.step_execution,
            completed_at=self.make_datetime(
                2026, 8, 15, 14,
            ),
        )

        result = SLAService.check_breach(
            step_execution=self.step_execution,
            now=self.make_datetime(
                2026, 8, 15, 16,
            ),
        )

        self.assertFalse(result)

    def test_mark_warning_sent(self):
        self.create_sla(
            duration=timedelta(hours=4),
            warning_before=timedelta(hours=1),
        )

        start = self.make_datetime(2026, 8, 15, 10)

        execution = WorkflowStepExecution.objects.create(
            workflow_step=self.step,
            performed_by=self.user,
            sla_started_at=start,
            sla_warning_at=SLAService.calculate_warning_at(
                step=self.step,
                start=start,
            ),
        )

        warning_sent_at = self.make_datetime(2026, 8, 15, 14, 30)

        result = SLAService.mark_warning_sent(
            step_execution=execution,
            sent_at=warning_sent_at,
        )

        self.assertEqual(
            result.sla_warning_sent_at,
            warning_sent_at,
        )


    def test_mark_breached(self):
        self.create_sla(
            duration=timedelta(hours=4),
            warning_before=timedelta(hours=1),
        )

        start = self.make_datetime(2026, 8, 15, 10)

        execution = WorkflowStepExecution.objects.create(
            workflow_step=self.step,
            performed_by=self.user,
            sla_started_at=start,
            sla_due_at=SLAService.calculate_due_at(
                step=self.step,
                start=start,
            ),
        )

        breached_at = self.make_datetime(2026, 8, 15, 16)

        result = SLAService.mark_breached(
            step_execution=execution,
            breached_at=breached_at,
        )

        self.assertEqual(
            result.sla_breached_at,
            breached_at,
        )