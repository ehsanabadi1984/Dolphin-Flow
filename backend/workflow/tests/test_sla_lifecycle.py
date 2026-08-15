from datetime import timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from workflow.models import (
    BusinessCalendar,
    CalendarException,
    WeeklySchedule,
    WorkingInterval,
    Workflow,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowStepSLA,
    WorkflowMembership,
)
from workflow.sla_services import SLAService
from django.contrib.auth import get_user_model


User = get_user_model()


class SLALifecycleTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="sla_lifecycle_user",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="SLA Lifecycle Test",
            code="SLA_LIFECYCLE_TEST",
            is_active=True,
        )

        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="SLA Test Step",
            code="SLA_TEST_STEP",
            order=1,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        self.calendar = BusinessCalendar.objects.create(
            name="SLA Lifecycle Calendar",
            timezone="Asia/Tehran",
            is_active=True,
        )

        # Saturday -> Wednesday working
        for weekday in (0, 1, 2, 5, 6):
            schedule = WeeklySchedule.objects.create(
                calendar=self.calendar,
                weekday=weekday,
                is_working=True,
            )

            WorkingInterval.objects.create(
                weekly_schedule=schedule,
                start_time="08:00",
                end_time="13:00",
            )

            WorkingInterval.objects.create(
                weekly_schedule=schedule,
                start_time="13:30",
                end_time="16:30",
            )

        # Thursday / Friday non-working
        for weekday in (3, 4):
            WeeklySchedule.objects.create(
                calendar=self.calendar,
                weekday=weekday,
                is_working=False,
            )

        self.sla = WorkflowStepSLA.objects.create(
            step=self.step,
            calendar=self.calendar,
            duration=timedelta(hours=4),
            warning_before=timedelta(hours=1),
            is_active=True,
        )

        self.step_execution = WorkflowStepExecution.objects.create(
            instance=None,
            workflow_step=self.step,
            performed_by=self.user,
        )

    def make_datetime(self, year, month, day, hour, minute=0):
        return timezone.make_aware(
            timezone.datetime(
                year,
                month,
                day,
                hour,
                minute,
            ),
            ZoneInfo("Asia/Tehran"),
        )

    def test_start_sla_calculates_due_and_warning(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        self.step_execution.refresh_from_db()

        self.assertEqual(
            self.step_execution.sla_started_at,
            start,
        )

        self.assertEqual(
            self.step_execution.sla_due_at,
            self.make_datetime(
                2026,
                8,
                15,
                14,
                30,
            ),
        )

        self.assertEqual(
            self.step_execution.sla_warning_at,
            self.make_datetime(
                2026,
                8,
                15,
                13,
                30,
            ),
        )

    def test_start_sla_does_not_overwrite_existing_sla(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        first_started_at = (
            self.step_execution.sla_started_at
        )

        later = self.make_datetime(
            2026,
            8,
            16,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=later,
        )

        self.step_execution.refresh_from_db()

        self.assertEqual(
            self.step_execution.sla_started_at,
            first_started_at,
        )

    def test_check_breach_before_due(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        before_due = self.make_datetime(
            2026,
            8,
            15,
            14,
            0,
        )

        result = SLAService.check_breach(
            step_execution=self.step_execution,
            now=before_due,
        )

        self.assertFalse(result)

        self.step_execution.refresh_from_db()

        self.assertIsNone(
            self.step_execution.sla_breached_at,
        )

    def test_check_breach_after_due(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        after_due = self.make_datetime(
            2026,
            8,
            15,
            16,
            0,
        )

        result = SLAService.check_breach(
            step_execution=self.step_execution,
            now=after_due,
        )

        self.assertTrue(result)

        self.step_execution.refresh_from_db()

        self.assertIsNotNone(
            self.step_execution.sla_breached_at,
        )

    def test_check_breach_is_idempotent(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        after_due = self.make_datetime(
            2026,
            8,
            15,
            16,
        )

        SLAService.check_breach(
            step_execution=self.step_execution,
            now=after_due,
        )

        self.step_execution.refresh_from_db()

        first_breach = (
            self.step_execution.sla_breached_at
        )

        SLAService.check_breach(
            step_execution=self.step_execution,
            now=self.make_datetime(
                2026,
                8,
                16,
                10,
            ),
        )

        self.step_execution.refresh_from_db()

        self.assertEqual(
            self.step_execution.sla_breached_at,
            first_breach,
        )

    def test_is_warning_due_before_warning_time(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        result = SLAService.is_warning_due(
            step_execution=self.step_execution,
            now=self.make_datetime(
                2026,
                8,
                15,
                13,
                0,
            ),
        )

        self.assertFalse(result)

    def test_is_warning_due_at_warning_time(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        result = SLAService.is_warning_due(
            step_execution=self.step_execution,
            now=self.make_datetime(
                2026,
                8,
                15,
                14,
                30,
            ),
        )

        self.assertTrue(result)

    def test_is_warning_due_after_warning_time(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        result = SLAService.is_warning_due(
            step_execution=self.step_execution,
            now=self.make_datetime(
                2026,
                8,
                15,
                15,
            ),
        )

        self.assertTrue(result)

    def test_warning_is_not_due_after_already_sent(self):
        start = self.make_datetime(
            2026,
            8,
            15,
            10,
        )

        SLAService.start_sla(
            step_execution=self.step_execution,
            start=start,
        )

        self.step_execution.sla_warning_sent_at = (
            self.make_datetime(
                2026,
                8,
                15,
                14,
                35,
            )
        )

        self.step_execution.save(
            update_fields=["sla_warning_sent_at"]
        )

        result = SLAService.is_warning_due(
            step_execution=self.step_execution,
            now=self.make_datetime(
                2026,
                8,
                15,
                15,
            ),
        )

        self.assertFalse(result)