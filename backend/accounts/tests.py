from django.test import TestCase
from django.urls import reverse

from .models import User, UserPreference


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
