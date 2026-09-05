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
