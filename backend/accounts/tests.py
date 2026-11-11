from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from .models import User, UserPreference
from workflow.models import WorkflowSMSSettings


class UserPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="session-user",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_default_session_timeout_is_two_hours(self):
        preference = UserPreference.objects.create(user=self.user)
        self.assertEqual(preference.session_timeout, 7200)
        self.assertEqual(
            preference.get_session_timeout_display(),
            "۲ ساعت",
        )

    def test_settings_and_profile_use_the_same_preference(self):
        self.client.post(
            reverse("accounts:settings"),
            {"session_timeout": 14400},
        )
        self.assertEqual(
            UserPreference.objects.get(user=self.user).session_timeout,
            14400,
        )

        self.client.post(
            reverse("accounts:profile"),
            {"session_timeout": 1800},
        )
        self.assertEqual(
            UserPreference.objects.get(user=self.user).session_timeout,
            1800,
        )

    def test_session_timeout_is_applied_to_authenticated_session(self):
        UserPreference.objects.create(user=self.user, session_timeout=28800)
        self.client.get(reverse("accounts:settings"))
        self.assertEqual(self.client.session.get_expiry_age(), 28800)



class UserContactMethodTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="contact-user",
            password="test-password",
        )

    def test_sms_preference_is_disabled_by_default(self):
        preference = UserPreference.objects.create(user=self.user)
        self.assertFalse(preference.sms_notifications_enabled)

    def test_contact_is_unverified_by_default(self):
        from .models import UserContactMethod

        contact = UserContactMethod.objects.create(
            user=self.user,
            value="09123456789",
        )
        self.assertTrue(contact.is_active)
        self.assertFalse(contact.is_verified)
        self.assertEqual(contact.verification_attempts, 0)

    def test_only_one_contact_per_channel_is_allowed_for_a_user(self):
        from django.db import IntegrityError, transaction
        from .models import UserContactMethod

        UserContactMethod.objects.create(
            user=self.user,
            value="09123456789",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserContactMethod.objects.create(
                    user=self.user,
                    value="09129876543",
                )

    def test_invalid_mobile_number_is_rejected(self):
        from django.core.exceptions import ValidationError
        from .models import UserContactMethod

        contact = UserContactMethod(
            user=self.user,
            value="09 1234 56789",
        )
        with self.assertRaises(ValidationError):
            contact.full_clean()

    def test_changing_mobile_number_invalidates_previous_verification(self):
        from django.utils import timezone
        from .models import UserContactMethod

        contact = UserContactMethod.objects.create(
            user=self.user,
            value="09123456789",
            is_verified=True,
            verification_method=UserContactMethod.VerificationMethod.MANUAL,
        )
        self.assertIsNotNone(contact.verified_at)

        contact.value = "09129876543"
        contact.verification_code_hash = "old-hash"
        contact.verification_expires_at = timezone.now()
        contact.verification_attempts = 2
        contact.save()

        contact.refresh_from_db()
        self.assertFalse(contact.is_verified)
        self.assertEqual(contact.verification_method, "")
        self.assertIsNone(contact.verified_at)
        self.assertEqual(contact.verification_code_hash, "")
        self.assertIsNone(contact.verification_expires_at)
        self.assertEqual(contact.verification_attempts, 0)


class UserSMSSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sms-settings-user", password="test-password")
        self.client.force_login(self.user)
        WorkflowSMSSettings.objects.get_or_create(pk=1, defaults={"is_enabled": True})

    def test_settings_page_exposes_sms_controls(self):
        response = self.client.get(reverse("accounts:settings"))
        self.assertContains(response, "دریافت اعلان‌های سامانه از طریق پیامک")
        self.assertContains(response, "ثبت شماره / ارسال کد تأیید")

    def test_user_cannot_enable_sms_without_verified_active_number(self):
        self.client.post(reverse("accounts:settings"), {"sms_action": "toggle_sms", "sms_enabled": "1"})
        self.assertFalse(UserPreference.objects.get(user=self.user).sms_notifications_enabled)

    def test_user_can_disable_sms_without_contact(self):
        preference = UserPreference.objects.create(user=self.user, sms_notifications_enabled=True)
        response = self.client.post(reverse("accounts:settings"), {"sms_action": "toggle_sms"})
        self.assertRedirects(response, reverse("accounts:settings"))
        preference.refresh_from_db()
        self.assertFalse(preference.sms_notifications_enabled)

    @patch("accounts.services.import_string")
    def test_user_can_register_and_verify_phone_with_otp(self, mock_import_string):
        import re
        from django.contrib.auth.hashers import check_password
        from accounts.models import UserContactMethod
        provider = MagicMock()
        provider.return_value.send.return_value = {"id": 123, "status": 0}
        mock_import_string.return_value = provider
        response = self.client.post(reverse("accounts:settings"), {
            "sms_action": "save_phone", "phone_number": "989121234567",
        })
        self.assertRedirects(response, reverse("accounts:settings"))
        contact = UserContactMethod.objects.get(user=self.user)
        self.assertTrue(contact.is_active)
        self.assertFalse(contact.is_verified)
        sent_code = re.search(r"(?<![0-9])[0-9]{6}(?![0-9])", provider.return_value.send.call_args.kwargs["message"]).group()
        self.assertTrue(check_password(sent_code, contact.verification_code_hash))
        response = self.client.post(reverse("accounts:settings"), {
            "sms_action": "verify_phone", "verification_code": sent_code,
        })
        self.assertRedirects(response, reverse("accounts:settings"))
        contact.refresh_from_db()
        self.assertTrue(contact.is_verified)
        self.assertEqual(contact.verification_method, UserContactMethod.VerificationMethod.OTP)
        self.assertEqual(contact.verification_code_hash, "")

    @patch("accounts.services.import_string")
    def test_changing_phone_invalidates_manual_verification(self, mock_import_string):
        from accounts.models import UserContactMethod
        provider = MagicMock()
        provider.return_value.send.return_value = {"id": 456, "status": 0}
        mock_import_string.return_value = provider
        contact = UserContactMethod.objects.create(
            user=self.user, value="989121111111", is_verified=True,
            verification_method=UserContactMethod.VerificationMethod.MANUAL,
            verified_by=self.user,
        )
        self.client.post(reverse("accounts:settings"), {
            "sms_action": "save_phone", "phone_number": "989122222222",
        })
        contact.refresh_from_db()
        self.assertEqual(contact.value, "989122222222")
        self.assertFalse(contact.is_verified)
        self.assertEqual(contact.verification_method, "")
        self.assertIsNone(contact.verified_by_id)
        self.assertTrue(contact.verification_code_hash)
        self.assertIsNotNone(contact.verification_expires_at)

    @patch("accounts.services.import_string")
    def test_otp_resend_is_rate_limited(self, mock_import_string):
        from accounts.models import UserContactMethod
        provider = MagicMock()
        provider.return_value.send.return_value = {"id": 789, "status": 0}
        mock_import_string.return_value = provider
        self.client.post(reverse("accounts:settings"), {
            "sms_action": "save_phone", "phone_number": "989123333333",
        })
        self.client.post(reverse("accounts:settings"), {
            "sms_action": "save_phone", "phone_number": "989123333333",
        })
        provider.return_value.send.assert_called_once()
        self.assertEqual(UserContactMethod.objects.get(user=self.user).verification_attempts, 0)


    @patch("accounts.services.import_string")
    def test_five_wrong_otp_attempts_are_persisted_and_invalidate_code(self, mock_import_string):
        from django.core.exceptions import ValidationError
        from accounts.models import UserContactMethod
        provider = MagicMock()
        provider.return_value.send.return_value = {"id": 999, "status": 0}
        mock_import_string.return_value = provider
        self.client.post(reverse("accounts:settings"), {
            "sms_action": "save_phone", "phone_number": "989124444444",
        })
        contact = UserContactMethod.objects.get(user=self.user)
        import re
        from accounts.services import verify_sms_verification_code
        actual_code = re.search(
            r"(?<![0-9])[0-9]{6}(?![0-9])",
            provider.return_value.send.call_args.kwargs["message"],
        ).group()
        wrong_code = "000001" if actual_code != "000001" else "000002"
        for _ in range(5):
            with self.assertRaises(ValidationError):
                verify_sms_verification_code(self.user, wrong_code)
        contact.refresh_from_db()
        self.assertEqual(contact.verification_attempts, 5)
        self.assertEqual(contact.verification_code_hash, "")
        self.assertIsNone(contact.verification_expires_at)
        self.assertFalse(contact.is_verified)


    def test_user_can_enable_sms_after_phone_is_verified(self):
        from accounts.models import UserContactMethod
        UserContactMethod.objects.create(
            user=self.user,
            value="989125555555",
            is_active=True,
            is_verified=True,
            verification_method=UserContactMethod.VerificationMethod.OTP,
        )
        response = self.client.post(reverse("accounts:settings"), {
            "sms_action": "toggle_sms", "sms_enabled": "1",
        })
        self.assertRedirects(response, reverse("accounts:settings"))
        self.assertTrue(UserPreference.objects.get(user=self.user).sms_notifications_enabled)


    def test_otp_cannot_be_sent_when_global_sms_is_disabled(self):
        from django.core.exceptions import ValidationError
        from accounts.services import request_sms_verification
        WorkflowSMSSettings.objects.filter(pk=1).update(is_enabled=False)
        with self.assertRaises(ValidationError):
            request_sms_verification(self.user, "989126666666")
        self.assertFalse(self.user.contact_methods.exists())
