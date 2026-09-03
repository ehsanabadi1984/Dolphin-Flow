from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import WorkflowMembership


class WorkflowRealtimeService:
    """Broadcast workflow changes to users who may be affected by them."""

    EVENT_TYPE = "workflow.updated"

    @classmethod
    def notify_instance_changed(cls, *, instance_id, workflow_id, actor_id=None):
        """Broadcast a small invalidation event after the transaction commits."""
        recipient_ids = set()

        if actor_id:
            recipient_ids.add(actor_id)

        recipient_ids.update(
            WorkflowMembership.objects.filter(
                workflow_id=workflow_id,
                is_active=True,
            ).values_list("user_id", flat=True)
        )

        if not recipient_ids:
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        event = {
            "type": cls.EVENT_TYPE,
            "instance_id": instance_id,
            "workflow_id": workflow_id,
        }

        for user_id in recipient_ids:
            async_to_sync(channel_layer.group_send)(
                f"user_notifications_{user_id}",
                {
                    "type": "workflow_update_message",
                    "event": event,
                },
            )
