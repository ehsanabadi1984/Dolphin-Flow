"""Application services for internal file-share message lifecycle."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import FileShareMessage, FileShareMessageEvent


class FileShareMessageService:
    """Serialize and audit every supported message status transition."""

    ALLOWED_TRANSITIONS = {
        FileShareMessage.Status.PENDING: {
            FileShareMessage.Status.READ,
            FileShareMessage.Status.CANCELLED,
            FileShareMessage.Status.EXPIRED,
        },
        FileShareMessage.Status.READ: {
            FileShareMessage.Status.RESPONDED,
            FileShareMessage.Status.CANCELLED,
            FileShareMessage.Status.EXPIRED,
        },
        FileShareMessage.Status.RESPONDED: {
            FileShareMessage.Status.COMPLETED,
            FileShareMessage.Status.CANCELLED,
            FileShareMessage.Status.EXPIRED,
        },
        FileShareMessage.Status.COMPLETED: set(),
        FileShareMessage.Status.CANCELLED: set(),
        FileShareMessage.Status.EXPIRED: set(),
    }

    STATUS_METADATA = {
        FileShareMessage.Status.READ: (
            "read_at",
            FileShareMessageEvent.EventType.READ,
        ),
        FileShareMessage.Status.RESPONDED: (
            "responded_at",
            FileShareMessageEvent.EventType.RESPONDED,
        ),
        FileShareMessage.Status.COMPLETED: (
            "completed_at",
            FileShareMessageEvent.EventType.COMPLETED,
        ),
        FileShareMessage.Status.CANCELLED: (
            "cancelled_at",
            FileShareMessageEvent.EventType.CANCELLED,
        ),
        FileShareMessage.Status.EXPIRED: (
            None,
            FileShareMessageEvent.EventType.EXPIRED,
        ),
    }

    @classmethod
    @transaction.atomic
    def transition_status(
        cls,
        *,
        message,
        to_status,
        actor=None,
        details=None,
        at=None,
    ):
        """Transition one message, update its timestamp, and append an event."""
        message_id = message.pk if isinstance(message, FileShareMessage) else message
        if not message_id:
            raise ValidationError("پیام اشتراک‌گذاری معتبر نیست.")

        locked_message = (
            FileShareMessage.objects.select_for_update()
            .get(pk=message_id)
        )
        allowed = cls.ALLOWED_TRANSITIONS.get(locked_message.status)
        if allowed is None or to_status not in allowed:
            raise ValidationError(
                "تغییر وضعیت پیام اشتراک‌گذاری مجاز نیست."
            )

        event_at = at or timezone.now()
        timestamp_field, event_type = cls.STATUS_METADATA[to_status]
        locked_message.status = to_status
        update_fields = ["status", "updated_at"]
        if timestamp_field:
            setattr(locked_message, timestamp_field, event_at)
            update_fields.append(timestamp_field)

        locked_message.save(update_fields=update_fields)
        event = FileShareMessageEvent.objects.create(
            message=locked_message,
            event_type=event_type,
            actor=actor,
            details=details or {},
        )
        return locked_message, event
