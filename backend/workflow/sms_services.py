import base64
import json
import logging
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from .models import Notification, SMSDelivery, WorkflowSMSSettings, WorkflowStepSMSRule

logger = logging.getLogger(__name__)

_GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXTENDED = set("^{}\\[~]|€")


class MagfaAPIError(Exception):
    pass


class MagfaSMSProvider:
    """Stdlib-only adapter for Magfa HTTP SMS API v2."""

    def send(self, *, recipient, message, uid):
        username = settings.MAGFA_USERNAME
        password = settings.MAGFA_PASSWORD
        domain = settings.MAGFA_DOMAIN
        sender = settings.MAGFA_SENDER
        if not all((username, password, domain, sender)):
            raise ImproperlyConfigured(
                "Magfa credentials, domain and sender must be configured in the environment."
            )

        token = base64.b64encode(
            f"{username}/{domain}:{password}".encode("utf-8")
        ).decode("ascii")
        payload = {
            "senders": [sender],
            "recipients": [recipient],
            "messages": [message],
            "uids": [uid],
        }
        request = Request(
            f"{settings.MAGFA_API_BASE_URL}/send",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=settings.MAGFA_TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MagfaAPIError(f"Magfa HTTP {exc.code}: {detail[:1000]}") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise MagfaAPIError(f"Magfa connection/response error: {exc}") from exc

        if not isinstance(result, dict) or result.get("status") != 0:
            raise MagfaAPIError(f"Magfa rejected the request: {str(result)[:1000]}")
        messages = result.get("messages")
        if not isinstance(messages, list) or len(messages) != 1:
            raise MagfaAPIError("Magfa response did not contain exactly one message result.")
        item = messages[0]
        if not isinstance(item, dict) or item.get("status") != 0:
            raise MagfaAPIError(f"Magfa message was not accepted: {str(item)[:1000]}")
        return item


def _message_parts(message):
    if all(ch in _GSM_BASIC or ch in _GSM_EXTENDED for ch in message):
        units = sum(2 if ch in _GSM_EXTENDED else 1 for ch in message)
        return 1 if units <= 160 else math.ceil(units / 153)
    units = len(message.encode("utf-16-be")) // 2
    return 1 if units <= 70 else math.ceil(units / 67)


def build_sms_message(notification):
    full_message = "\n".join(
        part.strip()
        for part in (notification.title, notification.message)
        if part and part.strip()
    )
    max_segments = max(1, settings.SMS_MAX_SEGMENTS)
    if _message_parts(full_message) <= max_segments:
        return full_message

    fallback = settings.SMS_FALLBACK_MESSAGE.strip()
    if not fallback or _message_parts(fallback) > max_segments:
        raise ValueError("Configured SMS fallback message is empty or exceeds SMS_MAX_SEGMENTS.")
    return fallback


def resolve_notification_step(notification):
    if notification.workflow_step_id:
        return notification.workflow_step
    if notification.transition_execution_id:
        transition = notification.transition_execution.transition
        if transition and transition.from_step_id:
            return transition.from_step
    file_message = notification.file_share_message
    if file_message:
        if file_message.workflow_step_id:
            return file_message.workflow_step
        if file_message.transition_execution_id:
            transition = file_message.transition_execution.transition
            if transition and transition.from_step_id:
                return transition.from_step
    return None


class SMSDispatcher:
    @classmethod
    def dispatch(cls, notification_id):
        notification = (
            Notification.objects.select_related(
                "recipient",
                "workflow_step",
                "transition_execution__transition__from_step",
                "file_share_message__workflow_step",
                "file_share_message__transition_execution__transition__from_step",
            ).get(pk=notification_id)
        )
        delivery, _ = SMSDelivery.objects.get_or_create(
            notification=notification,
            defaults={"status": SMSDelivery.Status.PENDING},
        )
        if delivery.status in (SMSDelivery.Status.SENT, SMSDelivery.Status.SKIPPED):
            return delivery.status

        reason, contact = cls._eligibility(notification)
        if reason:
            delivery.status = SMSDelivery.Status.SKIPPED
            delivery.last_error = reason
            delivery.save(update_fields=("status", "last_error", "updated_at"))
            return delivery.status

        message = build_sms_message(notification)
        delivery.recipient_number = contact.value
        delivery.provider_uid = delivery.pk
        delivery.attempt_count += 1
        delivery.last_error = ""
        delivery.save(update_fields=(
            "recipient_number", "provider_uid", "attempt_count",
            "last_error", "updated_at",
        ))

        result = MagfaSMSProvider().send(
            recipient=contact.value,
            message=message,
            uid=delivery.provider_uid,
        )
        delivery.status = SMSDelivery.Status.SENT
        delivery.provider_message_id = str(result.get("id", ""))
        delivery.sent_at = timezone.now()
        delivery.last_error = ""
        delivery.save(update_fields=(
            "status", "provider_message_id", "sent_at",
            "last_error", "updated_at",
        ))
        return delivery.status

    @staticmethod
    def _eligibility(notification):
        if not WorkflowSMSSettings.objects.filter(pk=1, is_enabled=True).exists():
            return "ارسال پیامک در تنظیمات سراسری غیرفعال است.", None

        preference = getattr(notification.recipient, "preferences", None)
        if not preference or not preference.sms_notifications_enabled:
            return "دریافت پیامک برای کاربر فعال نیست.", None

        contact = notification.recipient.contact_methods.filter(
            channel_type="SMS", is_active=True, is_verified=True,
        ).first()
        if not contact:
            return "شماره پیامکی فعال و تأییدشده‌ای برای کاربر وجود ندارد.", None

        step = resolve_notification_step(notification)
        if not step:
            return "مرحله مبدأ برای ارزیابی قانون پیامک مشخص نیست.", None

        enabled = WorkflowStepSMSRule.objects.filter(
            step=step,
            notification_type=notification.notification_type,
            sms_enabled=True,
        ).exists()
        if not enabled:
            return "قانون پیامک این نوع اعلان در مرحله مبدأ فعال نیست.", None
        return "", contact


def schedule_sms_notification(notification_id):
    if not WorkflowSMSSettings.objects.filter(pk=1, is_enabled=True).exists():
        return False
    from .tasks import dispatch_sms_notification
    dispatch_sms_notification.delay(notification_id)
    return True
