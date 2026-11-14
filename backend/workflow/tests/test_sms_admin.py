from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from workflow.admin import (
    SMSTemplateAdmin,
    WorkflowSMSSettingsAdminForm,
    dolphin_admin_site,
)
from workflow.models import (
    SMSTemplate,
    WorkflowSMSSettings,
)
from workflow.sms_provider_registry import create_provider_revision, register_provider


TEST_FERNET_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="

SMS_SETTINGS = {
    "SMS_CREDENTIALS_ENCRYPTION_KEY": TEST_FERNET_KEY,
    "MAGFA_API_BASE_URL": "https://sms.magfa.com/api/http/sms/v2",
    "MAGFA_TIMEOUT": 10,
}


@override_settings(**SMS_SETTINGS)
class WorkflowSMSSettingsAdminFormTests(TestCase):
    def form_data(self, **overrides):
        data = {
            "provider_username": "panel-user",
            "provider_password": "panel-secret",
            "provider_domain": "panel-domain",
            "provider_sender": "1000",
            "provider_api_base_url": SMS_SETTINGS["MAGFA_API_BASE_URL"],
            "provider_timeout": "10",
        }
        data.update(overrides)
        return data

    def test_first_time_configuration_requires_all_magfa_credentials(self):
        form = WorkflowSMSSettingsAdminForm(
            data=self.form_data(provider_password="")
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "برای راه‌اندازی مگفا",
            str(form.non_field_errors()),
        )

    def test_global_sms_can_be_disabled_without_provider_credentials(self):
        form = WorkflowSMSSettingsAdminForm(data={"is_enabled": ""})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form._sms_new_revision)

    def test_valid_configuration_is_prepared_for_encrypted_revision(self):
        form = WorkflowSMSSettingsAdminForm(data=self.form_data())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._sms_credentials["password"], "panel-secret")
        self.assertEqual(
            form._sms_connection_options["base_url"],
            SMS_SETTINGS["MAGFA_API_BASE_URL"],
        )
        self.assertTrue(form._sms_new_revision)

    def test_blank_password_preserves_saved_secret_and_is_never_prefilled(self):
        provider = register_provider(code="magfa", name="مگفا")
        create_provider_revision(
            provider,
            credentials={
                "username": "saved-user",
                "password": "saved-secret",
                "domain": "saved-domain",
                "sender": "1000",
            },
            connection_options={
                "base_url": SMS_SETTINGS["MAGFA_API_BASE_URL"],
                "timeout": 10,
            },
        )

        instance = WorkflowSMSSettings(pk=1)
        form = WorkflowSMSSettingsAdminForm(
            data=self.form_data(
                provider_username="saved-user",
                provider_password="",
                provider_domain="saved-domain",
                provider_sender="1000",
            ),
            instance=instance,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._sms_credentials["password"], "saved-secret")
        self.assertFalse(form._sms_new_revision)
        self.assertEqual(form["provider_password"].value(), "")

    def test_provider_settings_and_templates_are_registered_in_admin(self):
        self.assertIn(WorkflowSMSSettings, dolphin_admin_site._registry)
        self.assertIn(SMSTemplate, dolphin_admin_site._registry)
        self.assertIsInstance(
            dolphin_admin_site._registry[SMSTemplate],
            SMSTemplateAdmin,
        )


    @patch("workflow.admin.messages.success")
    def test_connection_action_does_not_activate_provider(self, mock_success):
        provider = register_provider(code="magfa", name="مگفا")
        create_provider_revision(
            provider,
            credentials={
                "username": "user",
                "password": "secret",
                "domain": "domain",
                "sender": "1000",
            },
            connection_options={
                "base_url": SMS_SETTINGS["MAGFA_API_BASE_URL"],
                "timeout": 10,
            },
        )
        request = RequestFactory().post("/", {"_test_connection": "1"})
        model_admin = dolphin_admin_site._registry[WorkflowSMSSettings]

        with patch("workflow.admin.build_provider") as build:
            build.return_value.test_connection.return_value = True
            handled = model_admin._handle_provider_action(
                request, WorkflowSMSSettings(pk=1)
            )

        provider.refresh_from_db()
        self.assertTrue(handled)
        self.assertFalse(provider.is_active)
        build.return_value.test_connection.assert_called_once_with()
        mock_success.assert_called_once()

    @patch("workflow.admin.messages.success")
    def test_activation_action_tests_connection_before_activating(self, mock_success):
        provider = register_provider(code="magfa", name="مگفا")
        create_provider_revision(
            provider,
            credentials={
                "username": "user",
                "password": "secret",
                "domain": "domain",
                "sender": "1000",
            },
            connection_options={
                "base_url": SMS_SETTINGS["MAGFA_API_BASE_URL"],
                "timeout": 10,
            },
        )
        request = RequestFactory().post("/", {"_activate_provider": "1"})
        model_admin = dolphin_admin_site._registry[WorkflowSMSSettings]

        with patch("workflow.admin.build_provider") as build, patch(
            "workflow.admin.activate_provider"
        ) as activate:
            build.return_value.test_connection.return_value = True
            handled = model_admin._handle_provider_action(
                request, WorkflowSMSSettings(pk=1)
            )

        self.assertTrue(handled)
        build.return_value.test_connection.assert_called_once_with()
        activate.assert_called_once_with(provider)
        mock_success.assert_called_once()

    @patch("workflow.admin.messages.error")
    def test_failed_connection_keeps_provider_inactive_and_global_sms_off(
        self, mock_error
    ):
        provider = register_provider(code="magfa", name="مگفا")
        create_provider_revision(
            provider,
            credentials={
                "username": "user",
                "password": "secret",
                "domain": "domain",
                "sender": "1000",
            },
            connection_options={
                "base_url": SMS_SETTINGS["MAGFA_API_BASE_URL"],
                "timeout": 10,
            },
        )
        WorkflowSMSSettings.objects.create(is_enabled=True)
        request = RequestFactory().post("/", {"_activate_provider": "1"})
        model_admin = dolphin_admin_site._registry[WorkflowSMSSettings]

        with patch("workflow.admin.build_provider") as build:
            build.return_value.test_connection.side_effect = OSError(
                "private API response"
            )
            handled = model_admin._handle_provider_action(
                request, WorkflowSMSSettings(pk=1)
            )

        provider.refresh_from_db()
        global_settings = WorkflowSMSSettings.objects.get(pk=1)
        self.assertTrue(handled)
        self.assertFalse(provider.is_active)
        self.assertFalse(global_settings.is_enabled)
        mock_error.assert_called_once()



class SMSAdminPermissionTests(SimpleTestCase):
    def test_global_sms_settings_are_superuser_only(self):
        model_admin = dolphin_admin_site._registry[WorkflowSMSSettings]
        regular_user = type(
            "UserStub",
            (),
            {"is_active": True, "is_superuser": False},
        )()
        admin_user = type(
            "UserStub",
            (),
            {"is_active": True, "is_superuser": True},
        )()

        self.assertFalse(model_admin.has_module_permission(regular_user))
        self.assertTrue(model_admin.has_module_permission(admin_user))
