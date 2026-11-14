from types import SimpleNamespace

from django.test import SimpleTestCase

from workflow.admin import SMSTemplateAdmin
from workflow.models import Notification
from workflow.sms_services import SMS_TEMPLATE_VARIABLES_BY_TYPE


class SMSTemplateAdminPreviewTests(SimpleTestCase):
    def test_preview_uses_the_selected_notification_type_for_every_type(self):
        for notification_type in Notification.NotificationType.values:
            with self.subTest(notification_type=notification_type):
                variables = SMS_TEMPLATE_VARIABLES_BY_TYPE[notification_type]
                template = SimpleNamespace(
                    title_template="عنوان {{ recipient_name }}",
                    body_template="؛ ".join(
                        "{{ " + variable + " }}" for variable in variables
                    ),
                    notification_type=notification_type,
                    legacy_format=False,
                )

                preview = str(
                    SMSTemplateAdmin.template_preview(None, template)
                )

                self.assertNotIn("خطای قالب:", preview)
                self.assertNotIn("قالب معتبر نیست", preview)
                self.assertIn("کاربر نمونه", preview)
                if "workflow_name" in variables:
                    self.assertIn("فرآیند نمونه", preview)
                else:
                    self.assertNotIn("فرآیند نمونه", preview)
                if "step_name" in variables:
                    self.assertIn("مرحله نمونه", preview)
                else:
                    self.assertNotIn("مرحله نمونه", preview)
