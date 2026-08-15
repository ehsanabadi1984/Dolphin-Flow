from django.db import transaction
from django.utils import timezone

from .models import Notification


class NotificationService:

    @staticmethod
    @transaction.atomic
    def create(
        *,
        recipient,
        notification_type,
        title,
        message,
        workflow_instance=None,
        workflow_step=None,
        transition_execution=None,
    ):
        return Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            message=message,
            workflow_instance=workflow_instance,
            workflow_step=workflow_step,
            transition_execution=transition_execution,
        )

    @staticmethod
    def mark_as_read(
        *,
        notification,
        user,
    ):
        if notification.recipient_id != user.id:
            return False

        if notification.is_read:
            return True

        notification.is_read = True
        notification.read_at = timezone.now()

        notification.save(
            update_fields=[
                "is_read",
                "read_at",
            ]
        )

        return True

    @staticmethod
    def get_unread(
        *,
        user,
    ):
        return (
            Notification.objects
            .filter(
                recipient=user,
                is_read=False,
            )
            .select_related(
                "workflow_instance",
                "workflow_step",
            )
            .order_by("-created_at")
        )

    @staticmethod
    def get_all(
        *,
        user,
    ):
        return (
            Notification.objects
            .filter(
                recipient=user,
            )
            .select_related(
                "workflow_instance",
                "workflow_step",
            )
            .order_by("-created_at")
        )