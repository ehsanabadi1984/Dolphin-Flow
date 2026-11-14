from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from workflow.admin import (
    SMSTemplateAdmin,
    SMSTemplateAdminForm,
    WorkflowSMSSettingsAdminForm,
    dolphin_admin_site,
)
from workflow.models import (
    SMSTemplate,
    WorkflowSMSSettings,
    SMSDelivery,
    SMSProviderConfiguration,
)
from workflow.sms_provider_registry import create_provider_revision, register_provider


TEST_FERNET_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

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

    def test_global_settings_admin_exposes_channel_and_delivery_health(self):
        model_admin = dolphin_admin_site._registry[WorkflowSMSSettings]
        settings_obj = WorkflowSMSSettings(is_enabled=True)

        self.assertEqual(model_admin.global_sms_status(settings_obj), "فعال")
        self.assertIn("کل:", model_admin.delivery_overview(settings_obj))
        self.assertEqual(
            model_admin.latest_delivery_status(settings_obj),
            "هنوز سابقه ارسالی ثبت نشده است.",
        )
        self.assertIn("delivery_overview", model_admin.readonly_fields)
        self.assertIn("latest_delivery_status", model_admin.readonly_fields)

    def test_provider_connection_test_result_is_visible_on_settings_page(self):
        provider = register_provider(code="magfa", name="مگفا")
        provider.last_connection_test_at = timezone.now()
        provider.last_connection_test_success = False
        provider.last_connection_test_message = "برقراری ارتباط با سرویس‌دهنده ممکن نشد."
        provider.save(update_fields=(
            "last_connection_test_at",
            "last_connection_test_success",
            "last_connection_test_message",
            "updated_at",
        ))
        model_admin = dolphin_admin_site._registry[WorkflowSMSSettings]

        self.assertIn("ناموفق", model_admin.last_connection_test_result(
            WorkflowSMSSettings(pk=1)
        ))
        self.assertIn("برقراری ارتباط", model_admin.last_connection_test_message(
            WorkflowSMSSettings(pk=1)
        ))

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
        self.assertTrue(provider.last_connection_test_success)
        self.assertIsNotNone(provider.last_connection_test_at)
        self.assertIn("اتصال برقرار شد", provider.last_connection_test_message)
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

        provider.refresh_from_db()
        self.assertTrue(handled)
        self.assertTrue(provider.last_connection_test_success)
        self.assertIsNotNone(provider.last_connection_test_at)
        build.return_value.test_connection.assert_called_once_with()
        activate.assert_called_once_with(provider)
        mock_success.assert_called_once()

    @patch("workflow.admin.messages.success")
    def test_deactivation_action_disables_provider_and_global_sms(self, mock_success):
        provider = register_provider(code="magfa", name="مگفا")
        provider.is_active = True
        provider.save(update_fields=("is_active", "updated_at"))
        WorkflowSMSSettings.objects.create(is_enabled=True)
        request = RequestFactory().post("/", {"_deactivate_provider": "1"})
        model_admin = dolphin_admin_site._registry[WorkflowSMSSettings]

        handled = model_admin._handle_provider_action(
            request, WorkflowSMSSettings(pk=1)
        )

        provider.refresh_from_db()
        global_settings = WorkflowSMSSettings.objects.get(pk=1)
        self.assertTrue(handled)
        self.assertFalse(provider.is_active)
        self.assertFalse(global_settings.is_enabled)
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
        self.assertFalse(provider.last_connection_test_success)
        self.assertIsNotNone(provider.last_connection_test_at)
        self.assertIn("برقراری ارتباط", provider.last_connection_test_message)
        self.assertNotIn("private API response", provider.last_connection_test_message)
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

        request = RequestFactory().get("/")
        request.user = regular_user
        self.assertFalse(model_admin.has_module_permission(request))
        request.user = admin_user
        self.assertTrue(model_admin.has_module_permission(request))



class SMSDeliveryAdminTests(SimpleTestCase):
    def test_delivery_admin_is_a_read_only_monitor_with_operational_filters(self):
        model_admin = dolphin_admin_site._registry[SMSDelivery]

        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertEqual(model_admin.date_hierarchy, "created_at")
        self.assertIn("status", model_admin.list_filter)
        self.assertIn("provider_code_snapshot", model_admin.list_filter)
        self.assertIn("message_source", model_admin.list_filter)
        self.assertIn("recipient", model_admin.list_display)
        self.assertIn("has_error", model_admin.list_display)

    def test_delivery_monitor_shows_recipient_without_exposing_error_text(self):
        model_admin = dolphin_admin_site._registry[SMSDelivery]
        delivery = MagicMock()
        delivery.notification.recipient.get_full_name.return_value = "کاربر آزمایشی"
        delivery.notification.recipient.get_username.return_value = "tester"
        delivery.last_error = "sensitive provider response"

        self.assertEqual(model_admin.recipient(delivery), "کاربر آزمایشی")
        self.assertTrue(model_admin.has_error(delivery))
        self.assertNotIn("sensitive", str(model_admin.has_error(delivery)))



class SMSTemplateAdminPreviewTests(SimpleTestCase):
    def test_template_form_explains_only_supported_variables(self):
        form = SMSTemplateAdminForm()
        help_text = form.fields["body_template"].help_text

        self.assertIn("{{ title }}", help_text)
        self.assertIn("{{ message }}", help_text)
        self.assertIn("فیلتر", help_text)

    def test_template_preview_renders_safe_sample_content(self):
        model_admin = dolphin_admin_site._registry[SMSTemplate]
        template = SMSTemplate(
            body_template="عنوان: {{ title }}\n{{ message }}"
        )

        preview = str(model_admin.template_preview(template))

        self.assertIn("عنوان نمونه اعلان", preview)
        self.assertIn("متن نمونه", preview)
        self.assertIn("<pre", preview)

    def test_invalid_template_preview_shows_guidance_instead_of_crashing(self):
        model_admin = dolphin_admin_site._registry[SMSTemplate]
        template = SMSTemplate(body_template="{{ recipient.phone }}")

        preview = str(model_admin.template_preview(template))

        self.assertIn("قالب معتبر نیست", preview)
