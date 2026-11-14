from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from workflow.models import SMSProviderConfigRevision, SMSProviderConfiguration


TEST_FERNET_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
MAGFA_SETTINGS = {
    "SMS_CREDENTIALS_ENCRYPTION_KEY": TEST_FERNET_KEY,
    "MAGFA_USERNAME": "bootstrap-user",
    "MAGFA_PASSWORD": "bootstrap-secret",
    "MAGFA_DOMAIN": "bootstrap-domain",
    "MAGFA_SENDER": "1000",
    "MAGFA_API_BASE_URL": "https://sms.magfa.com/api/http/sms/v2",
    "MAGFA_TIMEOUT": 7,
}


@override_settings(**MAGFA_SETTINGS)
class BootstrapSMSProviderCommandTests(TestCase):
    def test_bootstrap_imports_credentials_as_encrypted_revision(self):
        output = StringIO()
        call_command("bootstrap_sms_provider", stdout=output)

        provider = SMSProviderConfiguration.objects.get(code="magfa")
        revision = provider.revisions.get(is_current=True)

        self.assertEqual(revision.version, 1)
        self.assertNotIn("bootstrap-secret", revision.credentials_ciphertext)
        self.assertEqual(
            revision.connection_options,
            {
                "base_url": MAGFA_SETTINGS["MAGFA_API_BASE_URL"],
                "timeout": MAGFA_SETTINGS["MAGFA_TIMEOUT"],
            },
        )
        self.assertFalse(provider.is_active)
        self.assertNotIn("bootstrap-secret", output.getvalue())

    def test_bootstrap_is_idempotent_and_does_not_rotate_existing_credentials(self):
        call_command("bootstrap_sms_provider")
        first_ciphertext = SMSProviderConfigRevision.objects.get().credentials_ciphertext

        with override_settings(MAGFA_PASSWORD="changed-secret"):
            output = StringIO()
            call_command("bootstrap_sms_provider", stdout=output)

        self.assertEqual(SMSProviderConfigRevision.objects.count(), 1)
        revision = SMSProviderConfigRevision.objects.get()
        self.assertEqual(revision.credentials_ciphertext, first_ciphertext)
        self.assertIn("preserved", output.getvalue())
        self.assertNotIn("changed-secret", output.getvalue())

    def test_missing_environment_credentials_fail_before_database_writes(self):
        with override_settings(MAGFA_PASSWORD=""):
            with self.assertRaises(CommandError):
                call_command("bootstrap_sms_provider")

        self.assertFalse(SMSProviderConfiguration.objects.exists())
        self.assertFalse(SMSProviderConfigRevision.objects.exists())

    def test_missing_encryption_key_fails_before_database_writes(self):
        with override_settings(SMS_CREDENTIALS_ENCRYPTION_KEY=""):
            with self.assertRaises(CommandError):
                call_command("bootstrap_sms_provider")

        self.assertFalse(SMSProviderConfiguration.objects.exists())

    @patch("workflow.sms_services.urlopen")
    def test_activate_checks_connection_before_activation(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"status": 0, "balance": 500}'
        )
        mock_urlopen.return_value = response

        call_command("bootstrap_sms_provider", activate=True)

        provider = SMSProviderConfiguration.objects.get(code="magfa")
        self.assertTrue(provider.is_active)
        self.assertEqual(
            mock_urlopen.call_args.args[0].full_url,
            f'{MAGFA_SETTINGS["MAGFA_API_BASE_URL"]}/balance',
        )

    @patch("workflow.sms_services.urlopen")
    def test_failed_connection_does_not_activate_provider(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("network unavailable")

        with self.assertRaises(CommandError):
            call_command("bootstrap_sms_provider", activate=True)

        provider = SMSProviderConfiguration.objects.get(code="magfa")
        self.assertFalse(provider.is_active)
        self.assertEqual(provider.revisions.count(), 1)
