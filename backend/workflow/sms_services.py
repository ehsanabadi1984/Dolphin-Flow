import base64
import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
from django.db import transaction
from django.utils import timezone

from accounts.models import UserContactMethod
from .models import Notification, SMSDelivery, WorkflowSMSSettings, WorkflowStepSMSRule

_GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXTENDED = set("^{}\\[~]|€")


class MagfaAPIError(Exception):
    """A definitive error response from Magfa."""


class MagfaUncertainDeliveryError(MagfaAPIError):
    """The request may have reached Magfa, but acceptance could not be confirmed."""


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
            error = f"Magfa HTTP {exc.code}: {detail[:1000]}"
            if exc.code >= 500:
                raise MagfaUncertainDeliveryError(error) from exc
            raise MagfaAPIError(error) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise MagfaUncertainDeliveryError(
                f"Magfa delivery outcome is unknown: {exc}"
            ) from exc

        if not isinstance(result, dict):
            raise MagfaUncertainDeliveryError("Magfa returned an unreadable response.")
        if result.get("status") != 0:
            raise MagfaAPIError(f"Magfa rejected the request: {str(result)[:1000]}")
        messages = result.get("messages")
        if not isinstance(messages, list) or len(messages) != 1:
            raise MagfaUncertainDeliveryError(
                "Magfa response did not contain exactly one message result."
            )
        item = messages[0]
        if not isinstance(item, dict):
            raise MagfaUncertainDeliveryError("Magfa returned an unreadable message result.")
        if item.get("status") != 0:
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

        # Claim the delivery in a short transaction. The row lock serializes
        # concurrent workers; SENDING is committed before the network call so
        # a worker crash cannot cause an automatic duplicate submission.
        with transaction.atomic():
            delivery = SMSDelivery.objects.select_for_update().get(pk=delivery.pk)
            if delivery.status in (
                SMSDelivery.Status.SENT,
                SMSDelivery.Status.SKIPPED,
                SMSDelivery.Status.SENDING,
                SMSDelivery.Status.UNKNOWN,
            ):
                return delivery.status

            reason, contact = cls._eligibility(notification)
            if reason:
                delivery.status = SMSDelivery.Status.SKIPPED
                delivery.last_error = reason
                delivery.save(update_fields=("status", "last_error", "updated_at"))
                return delivery.status

            message = build_sms_message(notification)
            if delivery.provider_uid is None:
                delivery.provider_uid = delivery.pk
            delivery.status = SMSDelivery.Status.SENDING
            delivery.attempt_count += 1
            delivery.last_error = ""
            delivery.save(update_fields=(
                "status", "provider_uid", "attempt_count",
                "last_error", "updated_at",
            ))
            provider_uid = delivery.provider_uid

        try:
            provider_class = import_string(settings.SMS_PROVIDER_CLASS)
            result = provider_class().send(
                recipient=contact.value,
                message=message,
                uid=provider_uid,
            )
        except MagfaUncertainDeliveryError as exc:
            SMSDelivery.objects.filter(pk=delivery.pk).update(
                status=SMSDelivery.Status.UNKNOWN,
                last_error=str(exc)[:4000],
                updated_at=timezone.now(),
            )
            return SMSDelivery.Status.UNKNOWN
        except (MagfaAPIError, ImproperlyConfigured) as exc:
            SMSDelivery.objects.filter(pk=delivery.pk).update(
                status=SMSDelivery.Status.FAILED,
                last_error=str(exc)[:4000],
                updated_at=timezone.now(),
            )
            raise
        except Exception as exc:
            # An unclassified provider exception may happen after acceptance.
            # Mark it UNKNOWN rather than allowing an unsafe automatic resend.
            SMSDelivery.objects.filter(pk=delivery.pk).update(
                status=SMSDelivery.Status.UNKNOWN,
                last_error=str(exc)[:4000],
                updated_at=timezone.now(),
            )
            return SMSDelivery.Status.UNKNOWN

        if not isinstance(result, dict):
            SMSDelivery.objects.filter(pk=delivery.pk).update(
                status=SMSDelivery.Status.UNKNOWN,
                last_error="Provider returned an invalid result after submission.",
                updated_at=timezone.now(),
            )
            return SMSDelivery.Status.UNKNOWN

        SMSDelivery.objects.filter(pk=delivery.pk).update(
            status=SMSDelivery.Status.SENT,
            provider_message_id=str(result.get("id", "")),
            sent_at=timezone.now(),
            last_error="",
            updated_at=timezone.now(),
        )
        return SMSDelivery.Status.SENT

    @staticmethod
    def _eligibility(notification):
        if not WorkflowSMSSettings.objects.filter(pk=1, is_enabled=True).exists():
            return "ارسال پیامک در تنظیمات سراسری غیرفعال است.", None

        preference = getattr(notification.recipient, "preferences", None)
        if not preference or not preference.sms_notifications_enabled:
            return "دریافت پیامک برای کاربر فعال نیست.", None

        contact = notification.recipient.contact_methods.filter(
            channel_type=UserContactMethod.ChannelType.SMS,
            is_active=True,
            is_verified=True,
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
    # Persist an outbox row before enqueueing so broker failures are recoverable.
    notification = Notification.objects.get(pk=notification_id)
    SMSDelivery.objects.get_or_create(
        notification=notification,
        defaults={"status": SMSDelivery.Status.PENDING},
    )
    from .tasks import dispatch_sms_notification
    dispatch_sms_notification.delay(notification_id)
    return True
