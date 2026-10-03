from django.conf import settings

import requests


class N8NNotificationDispatcher:
    """Dispatch persisted Dolphin notifications to an n8n webhook."""

    @staticmethod
    def dispatch(notification_id):
        webhook_url = getattr(settings, "N8N_NOTIFICATION_WEBHOOK_URL", "")
        if not webhook_url:
            return False

        from .models import Notification

        notification = (
            Notification.objects
            .select_related(
                "recipient",
                "workflow_instance__workflow",
                "workflow_step",
            )
            .get(pk=notification_id)
        )

        payload = {
            "event": "notification.created",
            "notification": {
                "id": notification.id,
                "type": notification.notification_type,
                "title": notification.title,
                "message": notification.message,
                "created_at": notification.created_at.isoformat(),
            },
            "recipient": {
                "user_id": notification.recipient_id,
            },
            "workflow": {
                "instance_id": notification.workflow_instance_id,
                "workflow_id": (
                    notification.workflow_instance.workflow_id
                    if notification.workflow_instance_id
                    else None
                ),
                "workflow_name": (
                    notification.workflow_instance.workflow.name
                    if notification.workflow_instance_id
                    else None
                ),
            },
            "step": {
                "id": notification.workflow_step_id,
                "name": (
                    notification.workflow_step.name
                    if notification.workflow_step_id
                    else None
                ),
            },
        }

        headers = {
            "Content-Type": "application/json",
        }
        secret = getattr(settings, "N8N_NOTIFICATION_WEBHOOK_SECRET", "")
        if secret:
            headers["Authorization"] = f"Bearer {secret}"

        response = requests.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return True
