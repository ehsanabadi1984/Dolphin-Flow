from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from workflow.models import SMSProviderConfiguration
from workflow.sms_provider_registry import (
    activate_provider,
    build_provider,
    create_provider_revision,
    register_provider,
)
from workflow.sms_security import encrypt_credentials
from workflow.sms_services import MagfaSMSProvider


class Command(BaseCommand):
    help = (
        "Import Magfa credentials from environment settings into the encrypted "
        "SMS provider registry. Existing current revisions are preserved."
    )
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Test the Magfa balance endpoint and activate the provider.",
        )

    def handle(self, *args, **options):
        credentials = {
            "username": settings.MAGFA_USERNAME,
            "password": settings.MAGFA_PASSWORD,
            "domain": settings.MAGFA_DOMAIN,
            "sender": settings.MAGFA_SENDER,
        }
        missing = [key for key, value in credentials.items() if not value]
        if missing:
            raise CommandError(
                "Missing required Magfa environment settings: "
                + ", ".join(missing)
            )

        connection_options = {
            "base_url": settings.MAGFA_API_BASE_URL,
            "timeout": settings.MAGFA_TIMEOUT,
        }

        try:
            MagfaSMSProvider(
                credentials=credentials,
                options=connection_options,
            ).validate_configuration()
            # Validate the encryption key before writing any registry records.
            encrypt_credentials(credentials)
        except (ImproperlyConfigured, ValueError, TypeError) as exc:
            raise CommandError(
                "Magfa configuration or SMS encryption key is invalid. "
                "Check the environment settings; secret values are not displayed."
            ) from exc

        try:
            with transaction.atomic():
                provider = register_provider(code="magfa", name="مگفا")
                provider = SMSProviderConfiguration.objects.select_for_update().get(
                    pk=provider.pk
                )
                revision = provider.revisions.filter(is_current=True).first()
                created = revision is None
                if created:
                    revision = create_provider_revision(
                        provider,
                        credentials=credentials,
                        connection_options=connection_options,
                    )
        except ValidationError as exc:
            raise CommandError(
                "Could not initialize the Magfa provider registry."
            ) from exc

        if options["activate"]:
            try:
                adapter = build_provider(revision)
                adapter.test_connection()
                activate_provider(provider)
            except Exception as exc:
                # Do not expose provider responses or credentials in command output.
                raise CommandError(
                    "Magfa connection check failed; the provider was not activated."
                ) from exc
            self.stdout.write(
                self.style.SUCCESS("Magfa provider configuration is ready and active.")
            )
            return

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    "Magfa provider and encrypted configuration revision created. "
                    "The provider remains inactive."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Magfa already has a current revision; existing credentials "
                    "were preserved."
                )
            )
