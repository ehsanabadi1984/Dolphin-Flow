from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from workflow.sms_security import (
    SMSCredentialEncryptionError,
    decrypt_sms_credentials,
    encrypt_sms_credentials,
)


@override_settings(
    SMS_CREDENTIALS_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii")
)
class SMSCredentialEncryptionTests(SimpleTestCase):
    def test_credentials_round_trip(self):
        credentials = {
            "username": "gateway-user",
            "password": "private-password",
            "domain": "sample-domain",
        }

        encrypted = encrypt_sms_credentials(credentials)

        self.assertIsInstance(encrypted, str)
        self.assertNotIn("private-password", encrypted)
        self.assertEqual(decrypt_sms_credentials(encrypted), credentials)

    def test_ciphertext_cannot_be_decrypted_with_another_key(self):
        encrypted = encrypt_sms_credentials({"password": "private-password"})
        another_key = Fernet.generate_key().decode("ascii")

        with override_settings(SMS_CREDENTIALS_ENCRYPTION_KEY=another_key):
            with self.assertRaises(SMSCredentialEncryptionError):
                decrypt_sms_credentials(encrypted)

    def test_missing_key_fails_closed(self):
        with override_settings(SMS_CREDENTIALS_ENCRYPTION_KEY=""):
            with self.assertRaises(ImproperlyConfigured):
                encrypt_sms_credentials({"password": "secret"})

    def test_malformed_key_fails_closed(self):
        with override_settings(SMS_CREDENTIALS_ENCRYPTION_KEY="not-a-fernet-key"):
            with self.assertRaises(ImproperlyConfigured):
                encrypt_sms_credentials({"password": "secret"})

    def test_credentials_must_be_a_mapping(self):
        with self.assertRaises(TypeError):
            encrypt_sms_credentials(["not", "a", "mapping"])

    def test_decrypted_payload_must_be_a_json_object(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        token = Fernet(key).encrypt(b'["not", "an", "object"]').decode("ascii")

        with override_settings(
            SMS_CREDENTIALS_ENCRYPTION_KEY=key.decode("ascii")
        ):
            with self.assertRaises(SMSCredentialEncryptionError):
                decrypt_sms_credentials(token)

    def test_empty_ciphertext_is_rejected(self):
        with self.assertRaises(SMSCredentialEncryptionError):
            decrypt_sms_credentials("")
