import base64
import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from accounts.models import User, UserContactMethod, UserPreference
from workflow.models import (
    Notification, SMSDelivery, Workflow, WorkflowInstance, WorkflowSMSSettings,
    WorkflowStep, WorkflowStepSMSRule, WorkflowTransition,
    WorkflowTransitionExecution,
)
from workflow.sms_services import (
    MagfaSMSProvider, SMSDispatcher, build_sms_message,
    resolve_notification_step,
)


class SMSDispatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sms-recipient", password="test")
        UserPreference.objects.create(user=self.user, sms_notifications_enabled=True)
        self.contact = UserContactMethod.objects.create(
            user=self.user,
            value="09120000000",
            is_active=True,
            is_verified=True,
            verification_method=UserContactMethod.VerificationMethod.MANUAL,
        )
        workflow = Workflow.objects.create(name="Dynamic workflow")
        self.step = WorkflowStep.objects.create(
            workflow=workflow, name="Dynamic step", order=1,
        )
        self.notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
            title="اقدام لازم",
            message="لطفاً فرآیند را بررسی کنید.",
            workflow_step=self.step,
        )
        WorkflowSMSSettings.objects.create(is_enabled=True)
        WorkflowStepSMSRule.objects.create(
            step=self.step,
            notification_type=self.notification.notification_type,
            sms_enabled=True,
        )

    def test_workflow_completed_uses_transition_origin_step(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.step.workflow, current_step=None, started_by=self.user,
            status=WorkflowInstance.Status.COMPLETED,
        )
        transition = WorkflowTransition.objects.create(
            workflow=self.step.workflow, from_step=self.step,
            to_step=None, name="Complete dynamically",
        )
        execution = WorkflowTransitionExecution.objects.create(
            instance=instance, transition=transition, performed_by=self.user,
        )
        completed = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.WORKFLOW_COMPLETED,
            title="فرآیند تکمیل شد", message="فرآیند پایان یافت.",
            workflow_instance=instance, transition_execution=execution,
        )
        WorkflowStepSMSRule.objects.create(
            step=self.step,
            notification_type=Notification.NotificationType.WORKFLOW_COMPLETED,
            sms_enabled=True,
        )
        self.assertEqual(resolve_notification_step(completed), self.step)
        with patch("workflow.sms_services.MagfaSMSProvider.send") as mock_send:
            mock_send.return_value = {"id": 123, "status": 0}
            self.assertEqual(
                SMSDispatcher.dispatch(completed.pk), SMSDelivery.Status.SENT
            )
        mock_send.assert_called_once()

    @patch("workflow.sms_services.MagfaSMSProvider.send")
    def test_uncertain_provider_result_is_not_retried_automatically(self, mock_send):
        from workflow.sms_services import MagfaUncertainDeliveryError
        mock_send.side_effect = MagfaUncertainDeliveryError("read timeout")
        self.assertEqual(
            SMSDispatcher.dispatch(self.notification.pk), SMSDelivery.Status.UNKNOWN
        )
        self.assertEqual(
            SMSDispatcher.dispatch(self.notification.pk), SMSDelivery.Status.UNKNOWN
        )
        mock_send.assert_called_once()

    def test_global_switch_must_be_enabled(self):
        WorkflowSMSSettings.objects.filter(pk=1).update(is_enabled=False)
        self.assertEqual(
            SMSDispatcher.dispatch(self.notification.pk),
            SMSDelivery.Status.SKIPPED,
        )

    def test_missing_step_rule_is_disabled(self):
        WorkflowStepSMSRule.objects.filter(step=self.step).delete()
        self.assertEqual(
            SMSDispatcher.dispatch(self.notification.pk),
            SMSDelivery.Status.SKIPPED,
        )

    def test_user_preference_must_be_enabled(self):
        UserPreference.objects.filter(user=self.user).update(sms_notifications_enabled=False)
        self.assertEqual(
            SMSDispatcher.dispatch(self.notification.pk),
            SMSDelivery.Status.SKIPPED,
        )

    def test_contact_must_be_verified_and_active(self):
        self.contact.is_verified = False
        self.contact.save()
        self.assertEqual(
            SMSDispatcher.dispatch(self.notification.pk),
            SMSDelivery.Status.SKIPPED,
        )

    @override_settings(
        SMS_MAX_SEGMENTS=1,
        SMS_FALLBACK_MESSAGE="اعلان جدید؛ برای مشاهده وارد سامانه شوید.",
    )
    def test_long_notification_uses_short_fallback(self):
        self.notification.message = "متن فارسی بسیار طولانی " * 30
        self.assertEqual(
            build_sms_message(self.notification),
            "اعلان جدید؛ برای مشاهده وارد سامانه شوید.",
        )

    @patch("workflow.sms_services.MagfaSMSProvider.send")
    def test_successful_delivery_is_not_sent_twice(self, mock_send):
        mock_send.return_value = {"id": 9876, "status": 0}
        first = SMSDispatcher.dispatch(self.notification.pk)
        second = SMSDispatcher.dispatch(self.notification.pk)

        self.assertEqual(first, SMSDelivery.Status.SENT)
        self.assertEqual(second, SMSDelivery.Status.SENT)
        mock_send.assert_called_once()
        delivery = SMSDelivery.objects.get(notification=self.notification)
        self.assertEqual(delivery.provider_message_id, "9876")
        self.assertEqual(delivery.attempt_count, 1)

    @patch("workflow.sms_services.urlopen")
    @override_settings(
        MAGFA_USERNAME="account", MAGFA_PASSWORD="secret",
        MAGFA_DOMAIN="domain", MAGFA_SENDER="3000",
        MAGFA_API_BASE_URL="https://sms.magfa.com/api/http/sms/v2",
        MAGFA_TIMEOUT=7,
    )
    def test_magfa_adapter_sends_authenticated_json_with_uid(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "status": 0, "messages": [{"status": 0, "id": 12345}],
        }).encode()
        mock_urlopen.return_value = response

        result = MagfaSMSProvider().send(
            recipient="09120000000", message="متن آزمایشی", uid=77,
        )
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode())
        token = base64.b64encode(b"account/domain:secret").decode()
        self.assertEqual(request.get_header("Authorization"), f"Basic {token}")
        self.assertEqual(payload["recipients"], ["09120000000"])
        self.assertEqual(payload["messages"], ["متن آزمایشی"])
        self.assertEqual(payload["uids"], [77])
        self.assertEqual(result["id"], 12345)
