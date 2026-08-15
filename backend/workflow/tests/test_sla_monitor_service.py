from datetime import datetime, timedelta
from django.contrib.auth import get_user_model

from django.test import TestCase
from django.utils import timezone

from workflow.models import (
    BusinessCalendar,
    WeeklySchedule,
    WorkingInterval,
    Workflow,
    WorkflowStep,
    WorkflowStepSLA,
    WorkflowStepExecution,
    WorkflowMembership,
    WorkflowInstance,
    Notification,
)
from workflow.sla_monitor_services import SLAMonitorService


class SLAMonitorServiceTests(TestCase):

    def setUp(self):

        User = get_user_model()

        self.user = User.objects.create_user(
            username="sla_monitor_test",
            password="test-password",
        )

        self.manager = User.objects.create_user(
            username="sla_manager",
            password="test-password",
        )

        self.executor = User.objects.create_user(
            username="sla_executor",
            password="test-password",
        )

        self.calendar = BusinessCalendar.objects.create(
            name="Monitor Test Calendar",
            timezone="Asia/Tehran",
            is_active=True,
        )

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
                    start_time=datetime.strptime(
                        "08:00", "%H:%M"
                    ).time(),
                    end_time=datetime.strptime(
                        "13:00", "%H:%M"
                    ).time(),
                )

                WorkingInterval.objects.create(
                    weekly_schedule=schedule,
                    start_time=datetime.strptime(
                        "13:30", "%H:%M"
                    ).time(),
                    end_time=datetime.strptime(
                        "16:30", "%H:%M"
                    ).time(),
                )

        self.workflow = Workflow.objects.create(
            name="Monitor Workflow",
            code="MONITOR_WORKFLOW",
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.manager,
            role=WorkflowMembership.Role.MANAGER,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.executor,
            role=WorkflowMembership.Role.EXECUTOR,
        )

        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Monitor Step",
            code="MONITOR_STEP",
            order=1,
            is_active=True,
        )

        WorkflowStepSLA.objects.create(
            step=self.step,
            calendar=self.calendar,
            duration=timedelta(hours=2),
            warning_before=timedelta(hours=1),
            is_active=True,
        )

    def make_datetime(self, hour, minute=0):
        return timezone.make_aware(
            datetime(
                2026,
                8,
                15,
                hour,
                minute,
            )
        )

    def create_execution(
        self,
        *,
        started_at,
        warning_at=None,
        due_at=None,
        completed_at=None,
        warning_sent_at=None,
        breached_at=None,
    ):

        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
            status=WorkflowInstance.Status.ACTIVE,
        )

        return WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step,
            performed_by=self.user,
            sla_started_at=started_at,
            sla_warning_at=warning_at,
            sla_due_at=due_at,
            sla_completed_at=completed_at,
            sla_warning_sent_at=warning_sent_at,
            sla_breached_at=breached_at,
        )

    def test_processes_warning(self):
        start = self.make_datetime(10)

        execution = self.create_execution(
            started_at=start,
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
        )

        result = SLAMonitorService.process_active_slas(
            now=self.make_datetime(12),
        )

        execution.refresh_from_db()

        self.assertEqual(
            result["warning_count"],
            1,
        )

        self.assertIsNotNone(
            execution.sla_warning_sent_at,
        )

        self.assertIsNone(
            execution.sla_breached_at,
        )

    def test_processes_breach(self):
        start = self.make_datetime(10)

        execution = self.create_execution(
            started_at=start,
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
        )

        result = SLAMonitorService.process_active_slas(
            now=self.make_datetime(14),
        )

        execution.refresh_from_db()

        self.assertEqual(
            result["breach_count"],
            1,
        )

        self.assertIsNotNone(
            execution.sla_breached_at,
        )

    def test_ignores_completed_execution(self):
        execution = self.create_execution(
            started_at=self.make_datetime(10),
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
            completed_at=self.make_datetime(13),
        )

        result = SLAMonitorService.process_active_slas(
            now=self.make_datetime(16),
        )

        execution.refresh_from_db()

        self.assertEqual(
            result["warning_count"],
            0,
        )

        self.assertEqual(
            result["breach_count"],
            0,
        )

        self.assertIsNone(
            execution.sla_warning_sent_at,
        )

        self.assertIsNone(
            execution.sla_breached_at,
        )

    def test_does_not_repeat_warning(self):
        execution = self.create_execution(
            started_at=self.make_datetime(10),
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
            warning_sent_at=self.make_datetime(12),
        )

        result = SLAMonitorService.process_active_slas(
            now=self.make_datetime(13),
        )

        self.assertEqual(
            result["warning_count"],
            0,
        )

    def test_does_not_create_duplicate_warning_notifications(self):
        execution = self.create_execution(
            started_at=self.make_datetime(10),
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
        )

        SLAMonitorService.process_active_slas(
            now=self.make_datetime(12),
        )

        first_count = Notification.objects.filter(
            notification_type=Notification.NotificationType.SLA_WARNING,
            workflow_step=self.step,
        ).count()

        SLAMonitorService.process_active_slas(
            now=self.make_datetime(13),
        )

        second_count = Notification.objects.filter(
            notification_type=Notification.NotificationType.SLA_WARNING,
            workflow_step=self.step,
        ).count()

        self.assertEqual(first_count, 2)
        self.assertEqual(second_count, 2)

    def test_does_not_repeat_breach(self):
        execution = self.create_execution(
            started_at=self.make_datetime(10),
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
            breached_at=self.make_datetime(14),
        )

        result = SLAMonitorService.process_active_slas(
            now=self.make_datetime(15),
        )

        self.assertEqual(
            result["breach_count"],
            0,
        )

    def test_does_not_create_duplicate_breach_notifications(self):
        execution = self.create_execution(
            started_at=self.make_datetime(10),
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
        )

        SLAMonitorService.process_active_slas(
            now=self.make_datetime(14),
        )

        first_count = Notification.objects.filter(
            notification_type=Notification.NotificationType.SLA_BREACHED,
            workflow_step=self.step,
        ).count()

        SLAMonitorService.process_active_slas(
            now=self.make_datetime(15),
        )

        second_count = Notification.objects.filter(
            notification_type=Notification.NotificationType.SLA_BREACHED,
            workflow_step=self.step,
        ).count()

        self.assertEqual(first_count, 2)
        self.assertEqual(second_count, 2)

    def test_warning_creates_notifications(self):
        start = self.make_datetime(10)

        execution = self.create_execution(
            started_at=start,
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
        )

        SLAMonitorService.process_active_slas(
            now=self.make_datetime(12),
        )

        notifications = Notification.objects.filter(
            notification_type=Notification.NotificationType.SLA_WARNING,
            workflow_instance=execution.instance,
            workflow_step=self.step,
        )

        self.assertEqual(
            notifications.count(),
            2,
        )
        self.assertSetEqual(
            set(
                notifications.values_list(
                    "recipient_id",
                    flat=True,
                )
            ),
            {
                self.manager.id,
                self.executor.id,
            },
        )

    def test_breach_creates_notifications(self):
        start = self.make_datetime(10)

        execution = self.create_execution(
            started_at=start,
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
        )

        SLAMonitorService.process_active_slas(
            now=self.make_datetime(14),
        )

        notifications = Notification.objects.filter(
            notification_type=Notification.NotificationType.SLA_BREACHED,
            workflow_instance=execution.instance,
            workflow_step=self.step,
        )

        self.assertEqual(
            notifications.count(),
            2,
        )
        self.assertSetEqual(
            set(
                notifications.values_list(
                    "recipient_id",
                    flat=True,
                )
            ),
            {
                self.manager.id,
                self.executor.id,
            },
        )

    def test_warning_notifies_only_active_executor_and_manager(self):
        viewer = get_user_model().objects.create_user(
            username="sla_viewer",
            password="test-password",
        )

        inactive_executor = get_user_model().objects.create_user(
            username="inactive_executor",
            password="test-password",
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=viewer,
            role=WorkflowMembership.Role.VIEWER,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=inactive_executor,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=False,
        )

        execution = self.create_execution(
            started_at=self.make_datetime(10),
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
        )

        SLAMonitorService.process_active_slas(
            now=self.make_datetime(12),
        )

        notifications = Notification.objects.filter(
            notification_type=Notification.NotificationType.SLA_WARNING,
            workflow_instance=execution.instance,
            workflow_step=self.step,
        )

        self.assertEqual(
            notifications.count(),
            2,
        )

        self.assertSetEqual(
            set(
                notifications.values_list(
                    "recipient_id",
                    flat=True,
                )
            ),
            {
                self.manager.id,
                self.executor.id,
            },
        )

    def test_breach_notification_has_correct_type_and_context(self):
        execution = self.create_execution(
            started_at=self.make_datetime(10),
            warning_at=self.make_datetime(12),
            due_at=self.make_datetime(14),
        )

        SLAMonitorService.process_active_slas(
            now=self.make_datetime(14),
        )

        notification = Notification.objects.get(
            notification_type=Notification.NotificationType.SLA_BREACHED,
            workflow_instance=execution.instance,
            workflow_step=self.step,
            recipient=self.manager,
        )

        self.assertEqual(
            notification.title,
            "نقض SLA",
        )

        self.assertIn(
            self.step.name,
            notification.message,
        )

        self.assertEqual(
            notification.workflow_instance_id,
            execution.instance_id,
        )

        self.assertEqual(
            notification.workflow_step_id,
            self.step.id,
        )