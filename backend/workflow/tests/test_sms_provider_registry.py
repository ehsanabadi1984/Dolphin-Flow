from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import TestCase, override_settings
from unittest.mock import patch

from workflow.models import SMSProviderConfigRevision, SMSProviderConfiguration
from workflow.sms_provider_registry import (
    activate_provider,
    create_provider_revision,
    get_active_revision,
    register_provider,
)


TEST_FERNET_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


@override_settings(SMS_CREDENTIALS_ENCRYPTION_KEY=TEST_FERNET_KEY)
class SMSProviderRegistryTests(TestCase):
    def setUp(self):
        self.provider = register_provider(code="magfa", name="مگفا")

    def test_register_rejects_unsupported_provider(self):
        with self.assertRaises(ValidationError):
            register_provider(code="arbitrary", name="Unknown")

    def test_revision_credentials_are_encrypted_and_versioned(self):
        first = create_provider_revision(
            self.provider,
            credentials={"username": "user", "password": "secret"},
        )
        second = create_provider_revision(
            self.provider,
            credentials={"username": "user2", "password": "secret2"},
        )

        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        self.assertNotIn("secret2", second.credentials_ciphertext)
        first.refresh_from_db()
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)

    def test_revision_direct_edit_is_rejected(self):
        revision = create_provider_revision(
            self.provider,
            credentials={"username": "user", "password": "secret"},
        )
        revision.connection_options = {"timeout": 10}
        with self.assertRaises(ValidationError):
            revision.save()

    def test_revision_queryset_update_is_rejected(self):
        revision = create_provider_revision(
            self.provider,
            credentials={"username": "user", "password": "secret"},
        )
        with self.assertRaises(ValidationError):
            SMSProviderConfigRevision.objects.filter(pk=revision.pk).update(
                is_current=False
            )

    def test_revision_bulk_create_is_rejected(self):
        revision = SMSProviderConfigRevision(
            provider=self.provider,
            version=99,
            credentials_ciphertext="ciphertext",
        )
        with self.assertRaises(ValidationError):
            SMSProviderConfigRevision.objects.bulk_create([revision])

    def test_revision_bulk_update_is_rejected(self):
        revision = create_provider_revision(
            self.provider,
            credentials={"username": "user", "password": "secret"},
        )
        revision.is_current = False
        with self.assertRaises(ValidationError):
            SMSProviderConfigRevision.objects.bulk_update(
                [revision], ["is_current"]
            )

    def test_revision_delete_is_rejected(self):
        revision = create_provider_revision(
            self.provider,
            credentials={"username": "user", "password": "secret"},
        )
        with self.assertRaises(ValidationError):
            revision.delete()
        with self.assertRaises(ValidationError):
            SMSProviderConfigRevision.objects.filter(pk=revision.pk).delete()

    def test_provider_cannot_be_activated_without_current_revision(self):
        with self.assertRaises(ValidationError):
            activate_provider(self.provider)

        self.provider.refresh_from_db()
        self.assertFalse(self.provider.is_active)

    def test_activation_requires_decryptable_credentials(self):
        revision = create_provider_revision(
            self.provider,
            credentials={"username": "user", "password": "secret"},
        )
        from django.db import connection
        table = connection.ops.quote_name(
            SMSProviderConfigRevision._meta.db_table
        )
        column = connection.ops.quote_name("credentials_ciphertext")
        pk_column = connection.ops.quote_name(
            SMSProviderConfigRevision._meta.pk.column
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET {column} = %s WHERE {pk_column} = %s",
                ["invalid-ciphertext", revision.pk],
            )

        with self.assertRaises(ImproperlyConfigured):
            activate_provider(self.provider)

        self.provider.refresh_from_db()
        self.assertFalse(self.provider.is_active)

    def test_failed_activation_keeps_previous_provider_active(self):
        create_provider_revision(
            self.provider,
            credentials={
                "username": "user",
                "password": "secret",
                "domain": "test",
                "sender": "1000",
            },
        )
        activate_provider(self.provider)

        with patch.dict(
            "workflow.sms_provider_registry.PROVIDER_ADAPTERS",
            {"test-provider": "workflow.sms_services.MagfaSMSProvider"},
        ):
            other = register_provider(
                code="test-provider",
                name="اپراتور آزمایشی",
            )
            create_provider_revision(
                other,
                credentials={"username": "other", "password": "secret"},
            )

            with self.assertRaises(ImproperlyConfigured):
                activate_provider(other)

        self.provider.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(self.provider.is_active)
        self.assertFalse(other.is_active)

    def test_activation_selects_exactly_one_provider(self):
        create_provider_revision(
            self.provider,
            credentials={"username": "user", "password": "secret", "domain": "test", "sender": "1000"},
        )

        with patch.dict(
            "workflow.sms_provider_registry.PROVIDER_ADAPTERS",
            {"test-provider": "workflow.sms_services.MagfaSMSProvider"},
        ):
            other = register_provider(
                code="test-provider",
                name="اپراتور آزمایشی",
            )
            create_provider_revision(
                other,
                credentials={"username": "other", "password": "secret", "domain": "test", "sender": "1000"},
            )

            activate_provider(self.provider)
            activate_provider(other)

        self.provider.refresh_from_db()
        other.refresh_from_db()
        self.assertFalse(self.provider.is_active)
        self.assertTrue(other.is_active)
        self.assertEqual(get_active_revision().provider_id, other.pk)
