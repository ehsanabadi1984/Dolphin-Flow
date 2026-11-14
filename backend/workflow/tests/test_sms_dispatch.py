import base64
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User, UserContactMethod, UserPreference
from workflow.models import (
    Notification, SMSDelivery, SMSTemplate, SMSProviderConfiguration, SMSProviderConfigRevision, Workflow, WorkflowInstance, WorkflowSMSSettings,
    WorkflowStep, WorkflowStepSMSRule, WorkflowTransition,
    WorkflowTransitionExecution,
)
from workflow.sms_services import (
    MagfaSMSProvider, SMSDispatcher, build_sms_message,
    prepare_sms_delivery_snapshot, resolve_notification_step, _message_parts,
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

    def test_sms_template_renders_notification_variables(self):
        template = SMSTemplate.objects.create(
            step=self.step,
            notification_type=self.notification.notification_type,
            body_template="{{ title }} - {{ message }}",
        )
        from workflow.sms_services import _build_sms_content

        message, source = _build_sms_content(self.notification, template)

        self.assertEqual(
            message,
            "اقدام لازم - لطفاً فرآیند را بررسی کنید.",
        )
        self.assertEqual(source, "TEMPLATE")

    def test_sms_template_rejects_unapproved_variables_filters_and_tags(self):
        invalid_sources = (
            "{{ recipient.password }}",
            "{{ title|safe }}",
            "{% if title %}{{ title }}{% endif %}",
            "{{ unknown }}",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                template = SMSTemplate(
                    step=self.step,
                    notification_type=self.notification.notification_type,
                    body_template=source,
                )
                with self.assertRaises(ValidationError):
                    template.full_clean()

    def test_sms_template_runtime_validation_blocks_direct_database_bypass(self):
        template = SMSTemplate.objects.create(
            step=self.step,
            notification_type=self.notification.notification_type,
            body_template="{{ title|safe }}",
        )
        from workflow.sms_services import _build_sms_content

        with self.assertRaises(ValueError):
            _build_sms_content(self.notification, template)

    def test_sms_template_rejects_blank_or_malformed_source(self):
        from workflow.sms_services import validate_sms_template_source

        for source in ("", "   ", "{{ title"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    validate_sms_template_source(source)

    def test_sms_segment_count_respects_gsm_and_unicode_boundaries(self):
        # GSM basic alphabet: one septet per character.
        self.assertEqual(_message_parts("A" * 160), 1)
        self.assertEqual(_message_parts("A" * 161), 2)
        # GSM extension characters consume two septets each.
        self.assertEqual(_message_parts("^" * 80), 1)
        self.assertEqual(_message_parts("^" * 81), 2)
        # Persian text uses UCS-2: 70 units in one segment, then 67 per part.
        self.assertEqual(_message_parts("ا" * 70), 1)
        self.assertEqual(_message_parts("ا" * 71), 2)
        self.assertEqual(_message_parts("ا" * 138), 3)
        # Supplementary Unicode characters occupy two UTF-16 code units.
        self.assertEqual(_message_parts("😀" * 35), 1)
        self.assertEqual(_message_parts("😀" * 36), 2)

    def test_delivery_snapshot_does_not_change_after_source_updates(self):
        template = SMSTemplate.objects.create(
            step=self.step,
            notification_type=self.notification.notification_type,
            body_template="اعلان: {{ title }}",
        )
        delivery = SMSDelivery.objects.create(
            notification=self.notification,
            status=SMSDelivery.Status.PENDING,
        )
        prepare_sms_delivery_snapshot(self.notification, delivery)
        delivery.refresh_from_db()
        original_message = delivery.rendered_message
        original_template_id = delivery.template_id
        original_source = delivery.message_source

        self.notification.title = "عنوان جدید"
        self.notification.message = "متن جدید"
        self.notification.save(update_fields=("title", "message"))
        template.body_template = "تغییر قالب: {{ message }}"
        template.save(update_fields=("body_template",))

        prepare_sms_delivery_snapshot(self.notification, delivery)
        delivery.refresh_from_db()
        self.assertEqual(delivery.rendered_message, original_message)
        self.assertEqual(delivery.template_id, original_template_id)
        self.assertEqual(delivery.message_source, original_source)

    def test_incomplete_snapshot_is_rebuilt(self):
        delivery = SMSDelivery.objects.create(
            notification=self.notification,
            status=SMSDelivery.Status.PENDING,
            provider_code_snapshot="legacy",
            message_source="NOTIFICATION",
            rendered_message="",
        )
        prepare_sms_delivery_snapshot(self.notification, delivery)
        delivery.refresh_from_db()
        self.assertEqual(delivery.rendered_message, "اقدام لازم\\nلطفاً فرآیند را بررسی کنید.")

    def test_delivery_snapshot_keeps_rendered_template_message(self):
        SMSTemplate.objects.create(
            step=self.step,
            notification_type=self.notification.notification_type,
            body_template="اعلان: {{ title }}",
        )
        delivery = SMSDelivery.objects.create(
            notification=self.notification,
            status=SMSDelivery.Status.PENDING,
        )

        prepare_sms_delivery_snapshot(self.notification, delivery)

        delivery.refresh_from_db()
        self.assertEqual(delivery.rendered_message, "اعلان: اقدام لازم")
        self.assertEqual(delivery.message_source, "TEMPLATE")
        self.assertEqual(delivery.template.step, self.step)

    @override_settings(SMS_CREDENTIALS_ENCRYPTION_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    def test_delivery_snapshot_preserves_provider_revision(self):
        from workflow.sms_provider_registry import (
            activate_provider,
            create_provider_revision,
            register_provider,
        )

        provider = register_provider(code="magfa", name="Magfa")
        revision = create_provider_revision(
            provider,
            credentials={
                "username": "test", "password": "test",
                "domain": "test", "sender": "1000",
            },
        )
        activate_provider(provider)
        delivery = SMSDelivery.objects.create(
            notification=self.notification,
            status=SMSDelivery.Status.PENDING,
        )

        prepare_sms_delivery_snapshot(self.notification, delivery)
        delivery.refresh_from_db()

        self.assertEqual(delivery.provider_revision_id, revision.pk)
        self.assertEqual(delivery.provider_code_snapshot, "magfa")

        provider.is_active = False
        provider.save(update_fields=("is_active",))
        prepare_sms_delivery_snapshot(self.notification, delivery)
        delivery.refresh_from_db()

        self.assertEqual(delivery.provider_revision_id, revision.pk)

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
    def test_magfa_http_408_is_an_uncertain_delivery(self, mock_urlopen):
        from urllib.error import HTTPError
        from workflow.sms_services import MagfaUncertainDeliveryError

        mock_urlopen.side_effect = HTTPError(
            "https://sms.magfa.com/api/http/sms/v2/send",
            408, "Request Timeout", {}, None,
        )
        with self.assertRaises(MagfaUncertainDeliveryError):
            MagfaSMSProvider().send(
                recipient="09120000000", message="متن آزمایشی", uid=78,
            )

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


class SMSRecoveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sms-recovery", password="test")
        self.notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
            title="Recovery test",
            message="Recovery test",
        )
        self.delivery = SMSDelivery.objects.create(
            notification=self.notification,
            status=SMSDelivery.Status.SENDING,
        )

    @override_settings(SMS_DELIVERY_STALE_AFTER=600)
    def test_abandoned_sending_delivery_becomes_unknown_without_resend(self):
        from workflow.tasks import reconcile_stale_sms_deliveries
        SMSDelivery.objects.filter(pk=self.delivery.pk).update(
            updated_at=timezone.now() - timedelta(minutes=11),
        )
        self.assertEqual(reconcile_stale_sms_deliveries(), 1)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, SMSDelivery.Status.UNKNOWN)

    def test_unexpected_error_after_send_claim_becomes_unknown(self):
        from workflow.tasks import dispatch_sms_notification
        with patch("workflow.sms_services.SMSDispatcher.dispatch", side_effect=RuntimeError("provider result persistence failed")):
            result = dispatch_sms_notification.run(self.notification.pk)
        self.assertEqual(result, SMSDelivery.Status.UNKNOWN)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, SMSDelivery.Status.UNKNOWN)


    @override_settings(SMS_PENDING_REQUEUE_AFTER=60)
    def test_pending_outbox_is_not_enqueued_repeatedly(self):
        from workflow.tasks import requeue_pending_sms_deliveries

        SMSDelivery.objects.filter(pk=self.delivery.pk).update(
            status=SMSDelivery.Status.PENDING,
            last_queued_at=timezone.now() - timedelta(minutes=2),
        )
        with patch("workflow.tasks.dispatch_sms_notification.delay") as mock_delay:
            self.assertEqual(requeue_pending_sms_deliveries(), 1)
            self.assertEqual(requeue_pending_sms_deliveries(), 0)

        mock_delay.assert_called_once_with(self.notification.pk)
        self.delivery.refresh_from_db()
        self.assertGreater(self.delivery.last_queued_at, timezone.now() - timedelta(seconds=10))

    @override_settings(SMS_PENDING_REQUEUE_AFTER=60)
    def test_failed_broker_enqueue_releases_outbox_claim(self):
        from workflow.tasks import requeue_pending_sms_deliveries

        SMSDelivery.objects.filter(pk=self.delivery.pk).update(
            status=SMSDelivery.Status.PENDING,
            last_queued_at=None,
        )
        with patch(
            "workflow.tasks.dispatch_sms_notification.delay",
            side_effect=RuntimeError("broker unavailable"),
        ):
            self.assertEqual(requeue_pending_sms_deliveries(), 0)

        self.delivery.refresh_from_db()
        self.assertIsNone(self.delivery.last_queued_at)
