from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.models import (
    Notification,
    Workflow,
    WorkflowInstance,
    WorkflowStep,
)
from workflow.notification_services import NotificationService


User = get_user_model()


class NotificationServiceTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="notification_user",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Notification Test Workflow",
            code="NOTIFICATION_TEST",
            is_active=True,
        )

        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step",
            code="NOTIFICATION_STEP",
            order=1,
            is_active=True,
        )

        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
            status=WorkflowInstance.Status.ACTIVE,
        )

    def test_create_notification(self):
        notification = NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.STEP_ENTERED
            ),
            title="ورود به مرحله",
            message="فرآیند وارد مرحله جدید شد.",
            workflow_instance=self.instance,
            workflow_step=self.step,
        )

        self.assertEqual(
            notification.recipient,
            self.user,
        )

        self.assertEqual(
            notification.workflow_instance,
            self.instance,
        )

        self.assertFalse(
            notification.is_read,
        )

    def test_mark_as_read(self):
        notification = NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.ACTION_REQUIRED
            ),
            title="نیاز به اقدام",
            message="نیاز به اقدام شما وجود دارد.",
        )

        result = NotificationService.mark_as_read(
            notification=notification,
            user=self.user,
        )

        self.assertTrue(result)

        notification.refresh_from_db()

        self.assertTrue(
            notification.is_read,
        )

        self.assertIsNotNone(
            notification.read_at,
        )

    def test_mark_as_read_is_idempotent(self):
        notification = NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.ACTION_REQUIRED
            ),
            title="Test",
            message="Test notification",
        )

        first_result = NotificationService.mark_as_read(
            notification=notification,
            user=self.user,
        )

        notification.refresh_from_db()
        first_read_at = notification.read_at

        second_result = NotificationService.mark_as_read(
            notification=notification,
            user=self.user,
        )

        notification.refresh_from_db()

        self.assertTrue(first_result)
        self.assertTrue(second_result)
        self.assertTrue(notification.is_read)
        self.assertEqual(notification.read_at, first_read_at)

    def test_user_cannot_mark_other_users_notification_as_read(self):
        other_user = User.objects.create_user(
            username="other_notification_user",
            password="test-password",
        )

        notification = NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.ACTION_REQUIRED
            ),
            title="Test",
            message="Test",
        )

        result = NotificationService.mark_as_read(
            notification=notification,
            user=other_user,
        )

        self.assertFalse(result)

        notification.refresh_from_db()

        self.assertFalse(
            notification.is_read,
        )

    def test_get_unread_notifications(self):
        NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.STEP_ENTERED
            ),
            title="Unread",
            message="Unread notification",
        )

        notification = NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.ACTION_REQUIRED
            ),
            title="Read",
            message="Read notification",
        )

        NotificationService.mark_as_read(
            notification=notification,
            user=self.user,
        )

        unread = NotificationService.get_unread(
            user=self.user,
        )

        self.assertEqual(
            unread.count(),
            1,
        )

        self.assertEqual(
            unread.first().title,
            "Unread",
        )

    def test_get_unread_notifications_only_returns_users_notifications(self):
        other_user = User.objects.create_user(
            username="another_notification_user",
            password="test-password",
        )

        NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.STEP_ENTERED
            ),
            title="My Notification",
            message="My notification",
        )

        NotificationService.create(
            recipient=other_user,
            notification_type=(
                Notification.NotificationType.STEP_ENTERED
            ),
            title="Other Notification",
            message="Other notification",
        )

        unread = NotificationService.get_unread(
            user=self.user,
        )

        self.assertEqual(unread.count(), 1)
        self.assertEqual(
            unread.first().recipient,
            self.user,
        )
        self.assertEqual(
            unread.first().title,
            "My Notification",
        )

    def test_get_all_notifications(self):
        NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.STEP_ENTERED
            ),
            title="Unread",
            message="Unread notification",
        )

        notification = NotificationService.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.ACTION_REQUIRED
            ),
            title="Read",
            message="Read notification",
        )

        NotificationService.mark_as_read(
            notification=notification,
            user=self.user,
        )

        notifications = NotificationService.get_all(
            user=self.user,
        )

        self.assertEqual(
            notifications.count(),
            2,
        )

        self.assertEqual(
            set(
                notifications.values_list(
                    "recipient_id",
                    flat=True,
                )
            ),
            {self.user.id},
        )