from django.db import IntegrityError, transaction
from django.test import TestCase

from workflow.models import (
    Notification,
    Workflow,
    WorkflowStep,
    WorkflowStepSMSRule,
)


class WorkflowStepSMSRuleTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(name="SMS Rule Workflow")
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Manager Approval",
            order=1,
        )
        self.other_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Finance Approval",
            order=2,
        )

    def test_rule_is_disabled_by_default(self):
        rule = WorkflowStepSMSRule.objects.create(
            step=self.step,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
        )
        self.assertFalse(rule.sms_enabled)

    def test_same_notification_type_can_have_different_rules_per_step(self):
        action = Notification.NotificationType.ACTION_REQUIRED
        first = WorkflowStepSMSRule.objects.create(
            step=self.step,
            notification_type=action,
            sms_enabled=True,
        )
        second = WorkflowStepSMSRule.objects.create(
            step=self.other_step,
            notification_type=action,
            sms_enabled=False,
        )
        self.assertTrue(first.sms_enabled)
        self.assertFalse(second.sms_enabled)

    def test_each_notification_type_is_configured_independently(self):
        action = WorkflowStepSMSRule.objects.create(
            step=self.step,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
            sms_enabled=True,
        )
        sla = WorkflowStepSMSRule.objects.create(
            step=self.step,
            notification_type=Notification.NotificationType.SLA_WARNING,
            sms_enabled=False,
        )
        self.assertTrue(action.sms_enabled)
        self.assertFalse(sla.sms_enabled)

    def test_duplicate_step_and_notification_type_is_rejected(self):
        notification_type = Notification.NotificationType.ACTION_REQUIRED
        WorkflowStepSMSRule.objects.create(
            step=self.step,
            notification_type=notification_type,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkflowStepSMSRule.objects.create(
                    step=self.step,
                    notification_type=notification_type,
                    sms_enabled=True,
                )

    def test_rules_are_scoped_to_their_step(self):
        self.assertFalse(
            WorkflowStepSMSRule.objects.filter(
                step=self.step,
                notification_type=Notification.NotificationType.SLA_BREACHED,
            ).exists()
        )
