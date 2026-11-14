from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.db.models import Max

from .sms_security import decrypt_credentials, encrypt_credentials
from .models import allow_sms_revision_mutation


PROVIDER_ADAPTERS = {
    "magfa": "workflow.sms_services.MagfaSMSProvider",
}


def get_active_revision():
    from .models import SMSProviderConfiguration

    provider = (
        SMSProviderConfiguration.objects
        .filter(is_active=True)
        .first()
    )
    if not provider:
        raise ImproperlyConfigured("No active SMS provider is configured.")

    revision = provider.revisions.filter(is_current=True).first()
    if not revision:
        raise ImproperlyConfigured(
            f"Active SMS provider '{provider.code}' has no current configuration."
        )
    return revision


def build_provider(revision=None):
    from django.utils.module_loading import import_string

    if revision is None:
        revision = get_active_revision()

    adapter_path = PROVIDER_ADAPTERS.get(revision.provider.code)
    if not adapter_path:
        raise ImproperlyConfigured(
            f"Unsupported SMS provider: {revision.provider.code}"
        )

    credentials = decrypt_credentials(revision.credentials_ciphertext)
    adapter_class = import_string(adapter_path)
    return adapter_class(
        credentials=credentials,
        options=revision.connection_options or {},
    )


def get_active_provider():
    revision = get_active_revision()
    return build_provider(revision), revision


def get_provider_for_delivery(delivery):
    if delivery.provider_revision_id:
        return build_provider(delivery.provider_revision)
    return get_active_provider()[0]


def register_provider(*, code, name):
    from .models import SMSProviderConfiguration

    if code not in PROVIDER_ADAPTERS:
        raise ValidationError({"code": "این اپراتور در Registry پشتیبانی نمی‌شود."})
    if not name or not name.strip():
        raise ValidationError({"name": "نام اپراتور الزامی است."})

    provider, _ = SMSProviderConfiguration.objects.get_or_create(
        code=code,
        defaults={"name": name.strip()},
    )
    return provider


@transaction.atomic
def create_provider_revision(
    provider, *, credentials, connection_options=None, created_by=None
):
    from .models import SMSProviderConfigRevision, SMSProviderConfiguration

    if provider.code not in PROVIDER_ADAPTERS:
        raise ValidationError("اپراتور انتخاب‌شده پشتیبانی نمی‌شود.")
    if not isinstance(credentials, dict) or not credentials:
        raise ValidationError("اعتبارنامه‌های اپراتور باید یک دیکشنری غیرخالی باشند.")
    if connection_options is not None and not isinstance(connection_options, dict):
        raise ValidationError("تنظیمات اتصال باید یک دیکشنری باشند.")

    locked_provider = SMSProviderConfiguration.objects.select_for_update().get(
        pk=provider.pk
    )
    latest_version = (
        SMSProviderConfigRevision.objects
        .filter(provider=locked_provider)
        .aggregate(value=Max("version"))["value"] or 0
    )

    current = (
        SMSProviderConfigRevision.objects
        .select_for_update()
        .filter(provider=locked_provider, is_current=True)
        .first()
    )
    if current:
        current.is_current = False
        with allow_sms_revision_mutation():
            current.save(update_fields=("is_current",))

    with allow_sms_revision_mutation():
        return SMSProviderConfigRevision.objects.create(
            provider=locked_provider,
            version=latest_version + 1,
            credentials_ciphertext=encrypt_credentials(credentials),
            connection_options=connection_options or {},
            is_current=True,
            created_by=created_by,
        )


@transaction.atomic
def activate_provider(provider):
    from .models import SMSProviderConfiguration

    providers = list(
        SMSProviderConfiguration.objects
        .select_for_update()
        .order_by("pk")
    )
    target = next((item for item in providers if item.pk == provider.pk), None)
    if target is None:
        raise ValidationError("اپراتور موردنظر ثبت نشده است.")
    if target.code not in PROVIDER_ADAPTERS:
        raise ValidationError("اپراتور انتخاب‌شده پشتیبانی نمی‌شود.")

    revision = target.revisions.filter(is_current=True).first()
    if revision is None:
        raise ValidationError("برای این اپراتور نسخه تنظیمات جاری ثبت نشده است.")

    # Fail closed before changing the active provider.
    adapter = build_provider(revision)
    adapter.validate_configuration()

    for item in providers:
        if item.is_active:
            item.is_active = False
            item.save(update_fields=("is_active", "updated_at"))

    target.is_active = True
    target.save(update_fields=("is_active", "updated_at"))
    return target
