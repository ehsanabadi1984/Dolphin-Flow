from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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

    def test_authenticated_activity_refreshes_session_timeout(self):
        UserPreference.objects.create(user=self.user, session_timeout=7200)
        self.client.get(reverse("accounts:settings"))

        session = self.client.session
        session.set_expiry(30)
        session.save()

        self.client.get(reverse("accounts:settings"))

        self.assertEqual(self.client.session.get_expiry_age(), 7200)

    def test_expired_session_requires_login(self):
        UserPreference.objects.create(user=self.user, session_timeout=1800)
        self.client.get(reverse("accounts:settings"))

        session = Session.objects.get(session_key=self.client.session.session_key)
        session.expire_date = timezone.now() - timedelta(seconds=1)
        session.save(update_fields=["expire_date"])

        response = self.client.get(reverse("accounts:settings"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
