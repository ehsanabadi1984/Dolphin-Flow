from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Notification


def _schedule_sms_safely(notification_id):
    try:
        from .sms_services import schedule_sms_notification

        schedule_sms_notification(notification_id)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Unable to queue SMS for notification %s", notification_id
        )




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
        file_share_message=None,
    ):
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            message=message,
            workflow_instance=workflow_instance,
            workflow_step=workflow_step,
            transition_execution=transition_execution,
            file_share_message=file_share_message,
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
            "file_share_message_id": notification.file_share_message_id,
            "file_share_message_url": (
                f"{reverse('operator_panel:file_share_inbox_page')}?message_id={notification.file_share_message_id}"
                if notification.file_share_message_id else None
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
        # Queue SMS first so a later WebSocket callback failure cannot suppress it.
        # The WebSocket callback and payload remain unchanged.
        transaction.on_commit(
            lambda notification_id=notification.pk: _schedule_sms_safely(notification_id)
        )
        transaction.on_commit(publish_notification)

        # PARKED: n8n delivery is intentionally disabled.
        # if getattr(settings, "N8N_NOTIFICATION_WEBHOOK_URL", ""):
        #     from .tasks import dispatch_n8n_notification
        #
        #     transaction.on_commit(
        #         lambda: dispatch_n8n_notification.delay(notification.id)
        #     )

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
    @transaction.atomic
    def mark_instance_notifications_as_read(
        *,
        user,
        workflow_instance,
    ):
        """
        Mark unread notifications for this user and workflow instance
        as read when the instance is actually opened.
        """
        return (
            Notification.objects
            .filter(
                recipient=user,
                workflow_instance=workflow_instance,
                is_read=False,
            )
            .update(
                is_read=True,
                read_at=timezone.now(),
            )
        )

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
                "file_share_message",
                "transition_execution__transition__reject_to_step",
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

class WorkflowTransitionNotificationService:
    """
    Resolve and deliver ACCEPT/REJECT notifications independently from
    workflow-step assignment. Resolution failures are recorded, not raised.
    """

    @staticmethod
    def _failure(*, policy, error_code, details):
        return {
            "recipient": None,
            "policy": policy,
            "error_code": error_code,
            "details": details,
        }

    @classmethod
    def resolve_recipient(
        cls,
        *,
        transition,
        instance,
        outcome,
        source_execution,
        result_execution,
    ):
        from .models import WorkflowTransition

        if outcome == "ACCEPT":
            policy = transition.accept_notification_policy
            fixed_user = transition.accept_notification_user
        elif outcome == "REJECT":
            policy = transition.reject_notification_policy
            fixed_user = transition.reject_notification_user
        else:
            raise ValueError("outcome must be ACCEPT or REJECT")

        recipient = None

        if policy == WorkflowTransition.NotificationRecipientPolicy.SOURCE_COMPLETER:
            if source_execution is None:
                return cls._failure(
                    policy=policy,
                    error_code="SOURCE_EXECUTION_MISSING",
                    details="اجرای مبدأ مرتبط با این انتقال پیدا نشد.",
                )
            recipient = source_execution.completed_by
            if recipient is None:
                return cls._failure(
                    policy=policy,
                    error_code="SOURCE_COMPLETER_MISSING",
                    details="برای اجرای مبدأ، تکمیل‌کننده ثبت نشده است.",
                )

        elif policy == WorkflowTransition.NotificationRecipientPolicy.FIXED_USER:
            recipient = fixed_user
            if recipient is None:
                return cls._failure(
                    policy=policy,
                    error_code="FIXED_USER_MISSING",
                    details="کاربر ثابت برای این نتیجه تنظیم نشده است.",
                )

        elif policy == WorkflowTransition.NotificationRecipientPolicy.RETURN_STEP_ASSIGNEE:
            if result_execution is None:
                return cls._failure(
                    policy=policy,
                    error_code="RESULT_EXECUTION_MISSING",
                    details="اجرای مقصد یا بازگشت ایجاد نشده است.",
                )
            recipient = result_execution.assigned_to
            if recipient is None:
                return cls._failure(
                    policy=policy,
                    error_code="RESULT_ASSIGNEE_MISSING",
                    details="برای اجرای مقصد یا بازگشت، مسئولی تخصیص نیافته است.",
                )

        elif policy == WorkflowTransition.NotificationRecipientPolicy.WORKFLOW_STARTER:
            recipient = instance.started_by
            if recipient is None:
                return cls._failure(
                    policy=policy,
                    error_code="WORKFLOW_STARTER_MISSING",
                    details="شروع‌کننده فرآیند ثبت نشده است.",
                )

        else:
            return cls._failure(
                policy=policy,
                error_code="UNKNOWN_POLICY",
                details=f"سیاست گیرنده اعلان ناشناخته است: {policy}",
            )

        if not recipient.is_active:
            return cls._failure(
                policy=policy,
                error_code="RECIPIENT_INACTIVE",
                details="کاربر تعیین‌شده برای دریافت اعلان غیرفعال است.",
            )

        return {
            "recipient": recipient,
            "policy": policy,
            "error_code": None,
            "details": "",
        }

    @classmethod
    def notify_outcome(
        cls,
        *,
        transition,
        transition_execution,
        instance,
        outcome,
        source_execution,
        result_execution,
    ):
        from .models import (
            Notification,
            WorkflowTransitionNotificationIssue,
        )

        result = cls.resolve_recipient(
            transition=transition,
            instance=instance,
            outcome=outcome,
            source_execution=source_execution,
            result_execution=result_execution,
        )

        if result["recipient"] is None:
            WorkflowTransitionNotificationIssue.objects.create(
                transition_execution=transition_execution,
                outcome=outcome,
                policy=result["policy"],
                error_code=result["error_code"],
                details=result["details"],
            )
            return result

        recipient = result["recipient"]
        if outcome == "ACCEPT":
            title = f"فرآیند «{instance.workflow.name}» تأیید شد"
            message = (
                f"درخواست انتقال در فرآیند «{instance.workflow.name}» "
                "تأیید شد."
            )
        else:
            step_name = (
                result_execution.workflow_step.name
                if result_execution is not None else transition.from_step.name
            )
            title = f"فرآیند «{instance.workflow.name}» رد شد"
            message = (
                f"درخواست انتقال در فرآیند «{instance.workflow.name}» رد شد "
                f"و فرآیند به مرحله «{step_name}» بازگشت."
            )

        notification = NotificationService.create(
            recipient=recipient,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
            title=title,
            message=message,
            workflow_instance=instance,
            workflow_step=(
                result_execution.workflow_step
                if result_execution is not None else None
            ),
            transition_execution=transition_execution,
        )
        result["notification"] = notification
        return result
