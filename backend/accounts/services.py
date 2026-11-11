import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from .models import SMSVerificationRequest, UserContactMethod

logger = logging.getLogger(__name__)
OTP_LENGTH = max(4, min(8, settings.SMS_OTP_LENGTH))
OTP_TTL = timedelta(seconds=max(60, settings.SMS_OTP_TTL_SECONDS))
OTP_RESEND_COOLDOWN = timedelta(seconds=max(30, settings.SMS_OTP_RESEND_COOLDOWN_SECONDS))
OTP_MAX_ATTEMPTS = max(3, min(10, settings.SMS_OTP_MAX_ATTEMPTS))
OTP_DAILY_USER_LIMIT = max(1, settings.SMS_OTP_DAILY_USER_LIMIT)
OTP_DAILY_PHONE_LIMIT = max(1, settings.SMS_OTP_DAILY_PHONE_LIMIT)
OTP_RATE_WINDOW = timedelta(seconds=max(3600, settings.SMS_OTP_RATE_WINDOW_SECONDS))
OTP_REQUEST_LOG_RETENTION = timedelta(days=max(1, settings.SMS_OTP_REQUEST_LOG_RETENTION_DAYS))


def _phone_fingerprint(phone_number):
    secret = str(settings.SECRET_KEY).encode("utf-8")
    return hmac.new(secret, phone_number.encode("utf-8"), hashlib.sha256).hexdigest()


def request_sms_verification(user, phone_number):
    from workflow.models import WorkflowSMSSettings

    now = timezone.now()
    phone_fingerprint = _phone_fingerprint(phone_number)
    phone_changed = False
    with transaction.atomic():
        # Serialize OTP requests globally against the singleton SMS setting.
        # This makes both per-user and per-number quotas race-safe, including
        # requests for the same number made by different accounts.
        sms_settings = WorkflowSMSSettings.objects.select_for_update().filter(pk=1).first()
        if not sms_settings or not sms_settings.is_enabled:
            raise ValidationError("ارسال پیامک از طرف مدیر سامانه غیرفعال است.")

        contact = UserContactMethod.objects.select_for_update().filter(
            user=user, channel_type=UserContactMethod.ChannelType.SMS,
        ).first()
        if contact is None:
            contact = UserContactMethod(
                user=user, channel_type=UserContactMethod.ChannelType.SMS,
                value=phone_number, is_active=True,
            )
        elif contact.value != phone_number:
            # A self-service number change must never inherit manual verification.
            phone_changed = True
            contact.value = phone_number
            contact.is_active = True
            contact.is_verified = False
            contact.verification_method = ""
            contact.verified_at = None
            contact.verified_by = None
            contact.verification_code_hash = ""
            contact.verification_expires_at = None
            contact.verification_sent_at = None
            contact.verification_attempts = 0
        elif not contact.is_active:
            raise ValidationError("این شماره توسط مدیر سامانه غیرفعال شده است.")

        if contact.is_verified and contact.is_active:
            return False
        if contact.verification_sent_at and now - contact.verification_sent_at < OTP_RESEND_COOLDOWN:
            raise ValidationError("برای درخواست کد جدید، حداقل یک دقیقه صبر کنید.")

        window_start = now - OTP_RATE_WINDOW
        SMSVerificationRequest.objects.filter(created_at__lt=now - OTP_REQUEST_LOG_RETENTION).delete()
        user_requests = SMSVerificationRequest.objects.filter(
            user=user, created_at__gte=window_start,
        ).count()
        phone_requests = SMSVerificationRequest.objects.filter(
            phone_fingerprint=phone_fingerprint, created_at__gte=window_start,
        ).count()
        if user_requests >= OTP_DAILY_USER_LIMIT:
            raise ValidationError(
                "سقف درخواست روزانه کد تأیید برای حساب شما به پایان رسیده است."
            )
        if phone_requests >= OTP_DAILY_PHONE_LIMIT:
            raise ValidationError(
                "برای این شماره، سقف درخواست روزانه کد تأیید به پایان رسیده است."
            )

        if phone_changed:
            # Let the model invalidate the previous verification before storing
            # the newly generated OTP fields.
            contact.save()

        code = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
        contact.is_active = True
        contact.is_verified = False
        contact.verification_method = ""
        contact.verified_at = None
        contact.verified_by = None
        contact.verification_code_hash = make_password(code)
        contact.verification_expires_at = now + OTP_TTL
        contact.verification_sent_at = now
        contact.verification_attempts = 0
        contact.save()
        # Count every accepted request, including provider failures, to prevent
        # repeated attempts from bypassing quotas when the gateway is unhealthy.
        SMSVerificationRequest.objects.create(
            user=user, phone_fingerprint=phone_fingerprint,
        )

    try:
        provider_class = import_string(settings.SMS_PROVIDER_CLASS)
        provider_class().send(
            recipient=phone_number,
            message=f"کد تأیید شماره موبایل شما در Dolphin-Flow: {code}",
            uid=secrets.randbelow(2_000_000_000) + 1,
        )
    except Exception as exc:
        logger.exception("SMS verification send failed for user %s", user.pk)
        raise ValidationError("ارسال کد تأیید با مشکل مواجه شد. کمی بعد دوباره تلاش کنید.") from exc
    return True


def verify_sms_verification_code(user, code):
    now = timezone.now()
    error_message = None
    verified_contact = None

    with transaction.atomic():
        contact = UserContactMethod.objects.select_for_update().filter(
            user=user, channel_type=UserContactMethod.ChannelType.SMS,
        ).first()
        if not contact or not contact.is_active:
            error_message = "شماره فعالی برای تأیید وجود ندارد."
        elif not contact.verification_code_hash:
            error_message = "ابتدا برای شماره خود کد تأیید درخواست کنید."
        elif contact.verification_expires_at is None or contact.verification_expires_at <= now:
            contact.verification_code_hash = ""
            contact.verification_expires_at = None
            contact.save(update_fields=(
                "verification_code_hash", "verification_expires_at", "updated_at",
            ))
            error_message = "مهلت کد تأیید به پایان رسیده است. کد جدید درخواست کنید."
        elif contact.verification_attempts >= OTP_MAX_ATTEMPTS:
            error_message = "تعداد تلاش‌های تأیید بیش از حد مجاز است. کد جدید درخواست کنید."
        else:
            contact.verification_attempts += 1
            if not check_password(code, contact.verification_code_hash):
                if contact.verification_attempts >= OTP_MAX_ATTEMPTS:
                    contact.verification_code_hash = ""
                    contact.verification_expires_at = None
                contact.save(update_fields=(
                    "verification_attempts", "verification_code_hash",
                    "verification_expires_at", "updated_at",
                ))
                error_message = "کد تأیید نادرست است."
            else:
                contact.is_verified = True
                contact.verification_method = UserContactMethod.VerificationMethod.OTP
                contact.verified_at = now
                contact.verified_by = None
                contact.verification_code_hash = ""
                contact.verification_expires_at = None
                contact.save(update_fields=(
                    "is_verified", "verification_method", "verified_at", "verified_by",
                    "verification_code_hash", "verification_expires_at",
                    "verification_attempts", "updated_at",
                ))
                verified_contact = contact

    # Raise only after the atomic block so failed attempts and expiry cleanup persist.
    if error_message:
        raise ValidationError(error_message)
    return verified_contact
