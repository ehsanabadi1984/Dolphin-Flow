from django.db import transaction
from django.utils import timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

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
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            message=message,
            workflow_instance=workflow_instance,
            workflow_step=workflow_step,
            transition_execution=transition_execution,
        )

        notification_payload = {
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "type": notification.notification_type,
            "created_at": notification.created_at.isoformat(),
            "workflow_instance_id": (
                notification.workflow_instance_id
            ),
        }

        def publish_notification():
            channel_layer = get_channel_layer()

            async_to_sync(
                channel_layer.group_send
            )(
                f"user_notifications_{recipient.id}",
                {
                    "type": "notification_message",
                    "notification": notification_payload,
                },
            )
        transaction.on_commit(
            publish_notification
        )

        return notification

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