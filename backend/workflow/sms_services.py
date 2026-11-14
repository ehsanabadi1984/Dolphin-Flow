import base64
import json
import math
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.template import Context, Engine, TemplateSyntaxError
from django.template.base import TextNode, VariableNode

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


class SMSProvider:
    """Contract shared by all SMS provider adapters."""

    def validate_configuration(self):
        raise NotImplementedError

    def send(self, *, recipient, message, uid):
        raise NotImplementedError

    def test_connection(self):
        raise NotImplementedError

    def get_balance(self):
        raise NotImplementedError


class MagfaSMSProvider(SMSProvider):
    """Magfa HTTP SMS API v2 adapter."""

    def validate_configuration(self):
        config = self._config()
        required = ("username", "password", "domain", "sender")
        missing = [key for key in required if not config.get(key)]
        if missing:
            raise ImproperlyConfigured(
                "Magfa configuration is incomplete: " + ", ".join(missing)
            )
        if not config["base_url"].startswith(("https://", "http://")):
            raise ImproperlyConfigured("Magfa API base URL is invalid.")
        if config["timeout"] <= 0:
            raise ImproperlyConfigured("Magfa timeout must be positive.")
        return True

    def __init__(self, credentials=None, options=None):
        self._legacy_environment_config = credentials is None
        self.credentials = credentials if credentials is not None else {}
        self.options = options or {}

    def _config(self):
        if self._legacy_environment_config:
            credentials = {
                "username": settings.MAGFA_USERNAME,
                "password": settings.MAGFA_PASSWORD,
                "domain": settings.MAGFA_DOMAIN,
                "sender": settings.MAGFA_SENDER,
            }
            options = {
                "base_url": settings.MAGFA_API_BASE_URL,
                "timeout": settings.MAGFA_TIMEOUT,
            }
        else:
            credentials = self.credentials
            options = self.options

        return {
            "username": credentials.get("username"),
            "password": credentials.get("password"),
            "domain": credentials.get("domain"),
            "sender": credentials.get("sender"),
            "base_url": (options.get("base_url") or settings.MAGFA_API_BASE_URL).rstrip("/"),
            "timeout": int(options.get("timeout") or settings.MAGFA_TIMEOUT),
        }

    def _get_balance_response(self):
        config = self._config()
        self.validate_configuration()
        token = base64.b64encode(
            f"{config['username']}/{config['domain']}:{config['password']}".encode("utf-8")
        ).decode("ascii")
        request = Request(
            f"{config['base_url']}/balance",
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=config["timeout"]) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise MagfaAPIError(f"Magfa balance check failed (HTTP {exc.code}).") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise MagfaAPIError(f"Magfa connection check failed: {exc}") from exc

        if not isinstance(result, dict) or result.get("status") != 0:
            raise MagfaAPIError("Magfa returned an unsuccessful or invalid balance response.")
        return result

    def test_connection(self):
        self._get_balance_response()
        return True

    def get_balance(self):
        result = self._get_balance_response()
        if "balance" not in result:
            raise MagfaAPIError("Magfa response did not include the account balance.")
        return result["balance"]

    def send(self, *, recipient, message, uid):
        config = self._config()
        username = config["username"]
        password = config["password"]
        domain = config["domain"]
        sender = config["sender"]

        if not all((username, password, domain, sender)):
            raise ImproperlyConfigured(
                "Magfa credentials, domain and sender must be configured."
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
            f"{config['base_url']}/send",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=config["timeout"]) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            error = f"Magfa HTTP {exc.code}: {detail[:1000]}"
            if exc.code == 408 or exc.code >= 500:
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


def validate_sms_template_source(source):
    """Compile a deliberately small SMS template language.

    Only literal text and the two notification string variables are allowed.
    Tags, attribute traversal, filters and other variables are rejected.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError("SMS template cannot be empty.")

    # Django's template parser treats some unclosed delimiters as plain
    # text, so reject unbalanced template markers before compiling.
    for opening, closing in (("{{", "}}"), ("{%", "%}"), ("{#", "#}")):
        if source.count(opening) != source.count(closing):
            raise ValueError("SMS template syntax is invalid.")

    try:
        compiled = Engine(autoescape=False).from_string(source)
    except TemplateSyntaxError as exc:
        raise ValueError("SMS template syntax is invalid.") from exc

    for node in compiled.nodelist:
        if isinstance(node, TextNode):
            continue
        if isinstance(node, VariableNode):
            expression = node.filter_expression
            variable = expression.var
            if tuple(variable.lookups) not in (("title",), ("message",)):
                raise ValueError(
                    "Only the title and message variables are allowed in SMS templates."
                )
            if expression.filters:
                raise ValueError("Filters are not allowed in SMS templates.")
            continue
        raise ValueError("Template tags and control structures are not allowed in SMS templates.")

    return compiled


def _build_sms_content(notification, template=None):
    if template is not None:
        compiled = validate_sms_template_source(template.body_template)
        rendered = compiled.render(Context({
            "title": notification.title or "",
            "message": notification.message or "",
        })).strip()
        message = rendered
        source = "TEMPLATE"
    else:
        message = "\n".join(
            part.strip()
            for part in (notification.title, notification.message)
            if part and part.strip()
        )
        source = "NOTIFICATION"

    max_segments = max(1, settings.SMS_MAX_SEGMENTS)
    if _message_parts(message) <= max_segments:
        return message, source

    fallback = settings.SMS_FALLBACK_MESSAGE.strip()
    if not fallback or _message_parts(fallback) > max_segments:
        raise ValueError(
            "Configured SMS fallback message is empty or exceeds SMS_MAX_SEGMENTS."
        )
    return fallback, "LENGTH_FALLBACK"


def build_sms_message(notification):
    message, _ = _build_sms_content(notification)
    return message


def prepare_sms_delivery_snapshot(notification, delivery):
    """Persist provider, template and rendered-message snapshots once."""
    from .models import SMSProviderConfiguration, SMSTemplate
    from .sms_provider_registry import get_active_revision

    # The caller may already hold this row lock. Nested atomic blocks are safe.
    with transaction.atomic():
        locked = SMSDelivery.objects.select_for_update().get(pk=delivery.pk)

        snapshot_ready = bool(
            locked.provider_code_snapshot
            and locked.message_source
            and locked.rendered_message
            and locked.rendered_message.strip()
        )
        if snapshot_ready:
            delivery.refresh_from_db()
            return delivery

        step = resolve_notification_step(notification)
        template = None
        if step is not None:
            template = SMSTemplate.objects.filter(
                step=step,
                notification_type=notification.notification_type,
                is_active=True,
            ).first()
        if template is None:
            template = SMSTemplate.objects.filter(
                step__isnull=True,
                notification_type=notification.notification_type,
                is_active=True,
            ).first()

        message, source = _build_sms_content(notification, template)
        if not message.strip():
            raise ValueError("Rendered SMS message is empty.")

        if SMSProviderConfiguration.objects.filter(is_active=True).exists():
            revision = get_active_revision()
            locked.provider_revision = revision
            locked.provider_code_snapshot = revision.provider.code
        else:
            # Temporary compatibility until legacy settings are migrated.
            locked.provider_code_snapshot = "legacy"

        locked.template = template
        locked.rendered_message = message
        locked.message_source = source
        locked.save(update_fields=(
            "provider_revision",
            "provider_code_snapshot",
            "template",
            "rendered_message",
            "message_source",
            "updated_at",
        ))

        delivery.refresh_from_db()
        return delivery


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

            prepare_sms_delivery_snapshot(notification, delivery)
            message = delivery.rendered_message
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
            if delivery.provider_revision_id:
                from .sms_provider_registry import build_provider
                provider = build_provider(delivery.provider_revision)
            else:
                # Temporary compatibility with the legacy environment config.
                provider_class = import_string(settings.SMS_PROVIDER_CLASS)
                provider = provider_class()

            result = provider.send(
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
        except (MagfaAPIError, ImproperlyConfigured, ImportError) as exc:
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

        if not isinstance(result, dict) or not result.get("id"):
            SMSDelivery.objects.filter(pk=delivery.pk).update(
                status=SMSDelivery.Status.UNKNOWN,
                last_error="Provider did not return a confirmed message identifier after submission.",
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


def enqueue_pending_sms_notification(notification_id, *, min_interval_seconds=0):
    """Atomically claim a PENDING outbox row for one broker enqueue attempt."""
    now = timezone.now()
    cutoff = now - timedelta(seconds=max(0, min_interval_seconds))
    eligible = SMSDelivery.objects.filter(
        notification_id=notification_id,
        status=SMSDelivery.Status.PENDING,
    ).filter(
        Q(last_queued_at__isnull=True) | Q(last_queued_at__lt=cutoff)
    )
    claimed = eligible.update(last_queued_at=now)
    if not claimed:
        return False

    from .tasks import dispatch_sms_notification
    try:
        dispatch_sms_notification.delay(notification_id)
    except Exception:
        # Keep the outbox immediately eligible when the broker rejected enqueue.
        SMSDelivery.objects.filter(
            notification_id=notification_id,
            status=SMSDelivery.Status.PENDING,
            last_queued_at=now,
        ).update(last_queued_at=None)
        raise
    return True


def schedule_sms_notification(notification_id):
    if not WorkflowSMSSettings.objects.filter(pk=1, is_enabled=True).exists():
        return False
    # Persist an outbox row before enqueueing so broker failures are recoverable.
    notification = Notification.objects.get(pk=notification_id)
    delivery, _ = SMSDelivery.objects.get_or_create(
        notification=notification,
        defaults={"status": SMSDelivery.Status.PENDING},
    )
    prepare_sms_delivery_snapshot(notification, delivery)
    return enqueue_pending_sms_notification(
        notification_id,
        min_interval_seconds=max(60, settings.SMS_PENDING_REQUEUE_AFTER),
    )
