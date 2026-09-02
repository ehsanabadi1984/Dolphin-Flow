from datetime import timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from workflow.models import (
    BusinessCalendar,
    WeeklySchedule,
    WorkingInterval,
    Workflow,
    WorkflowStep,
    WorkflowStepSLA,
    WorkflowPermission,
    WorkflowMembership,
    WorkflowInstance,
    WorkflowStepExecution,
    WorkflowTransition,
)
from workflow.services import WorkflowExecutionService


User = get_user_model()


class SLAIntegrationTests(TestCase):

    def setUp(self):
        self.tz = ZoneInfo("Asia/Tehran")

        self.user = User.objects.create_user(
            username="sla_integration_user",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="SLA Integration Test",
            code="SLA_INTEGRATION_TEST",
            is_active=True,
        )

        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step One",
            code="SLA_INT_STEP_ONE",
            order=1,
            is_active=True,
        )

        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step Two",
            code="SLA_INT_STEP_TWO",
            order=2,
            is_active=True,
        )

        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Step One to Step Two",
            code="SLA_INT_TRANSITION",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.transition,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.calendar = BusinessCalendar.objects.create(
            name="SLA Integration Calendar",
            timezone="Asia/Tehran",
            is_active=True,
        )

        # Sat-Wed working
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

        # Thursday-Friday non-working
        for weekday in (3, 4):
            WeeklySchedule.objects.create(
                calendar=self.calendar,
                weekday=weekday,
                is_working=False,
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
            self.tz,
        )

    def test_start_workflow_starts_sla_for_first_step(self):
        WorkflowStepSLA.objects.create(
            step=self.step_one,
            calendar=self.calendar,
            duration=timedelta(hours=2),
            warning_before=timedelta(hours=1),
            is_active=True,
        )

        
        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        execution = WorkflowStepExecution.objects.get(
            instance=instance,
            workflow_step=self.step_one,
        )

        self.assertIsNotNone(
            execution.sla_started_at
        )

        self.assertIsNotNone(
            execution.sla_due_at
        )

        self.assertIsNotNone(
            execution.sla_warning_at
        )

    def test_transition_starts_sla_for_destination_step(self):
        WorkflowStepSLA.objects.create(
            step=self.step_two,
            calendar=self.calendar,
            duration=timedelta(hours=2),
            warning_before=timedelta(hours=1),
            is_active=True,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition,
            user=self.user,
        )

        execution = WorkflowStepExecution.objects.get(
            instance=instance,
            workflow_step=self.step_two,
        )

        self.assertIsNotNone(
            execution.sla_started_at
        )

        self.assertIsNotNone(
            execution.sla_due_at
        )

        self.assertIsNotNone(
            execution.sla_warning_at
        )

    def test_step_without_sla_still_executes(self):
        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        execution = WorkflowStepExecution.objects.get(
            instance=instance,
            workflow_step=self.step_one,
        )

        self.assertIsNone(
            execution.sla_started_at
        )

        self.assertIsNone(
            execution.sla_due_at
        )

        self.assertIsNone(
            execution.sla_warning_at
        )

    def test_transition_completes_sla_of_previous_step(self):
        WorkflowStepSLA.objects.create(
            step=self.step_one,
            calendar=self.calendar,
            duration=timedelta(hours=2),
            warning_before=timedelta(hours=1),
            is_active=True,
        )

        WorkflowStepSLA.objects.create(
            step=self.step_two,
            calendar=self.calendar,
            duration=timedelta(hours=2),
            warning_before=timedelta(hours=1),
            is_active=True,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition,
            user=self.user,
        )

        previous_execution = (
            WorkflowStepExecution.objects
            .filter(
                instance=instance,
                workflow_step=self.step_one,
            )
            .order_by("-performed_at")
            .first()
        )

        self.assertIsNotNone(
            previous_execution.sla_started_at
        )

        self.assertIsNotNone(
            previous_execution.sla_completed_at
        )

        self.assertIsNone(
            previous_execution.sla_breached_at
        )

        self.assertIsNone(
            previous_execution.sla_warning_sent_at
        )