from django.test import TestCase
from django.contrib.auth import get_user_model

from workflow.models import (
    Notification,
    Workflow,
    WorkflowInstance,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
    WorkflowTransitionNotificationIssue,
)
from workflow.notification_services import WorkflowTransitionNotificationService


class WorkflowTransitionNotificationServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.starter = User.objects.create_user(
            username="workflow-starter",
            password="test-password",
        )
        self.completer = User.objects.create_user(
            username="source-completer",
            password="test-password",
        )
        self.fixed_user = User.objects.create_user(
            username="fixed-recipient",
            password="test-password",
        )
        self.assignee = User.objects.create_user(
            username="result-assignee",
            password="test-password",
        )
        self.actor = User.objects.create_user(
            username="transition-actor",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(name="Notification Service Test")
        self.source_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Source",
            order=1,
        )
        self.destination_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Destination",
            order=2,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.source_step,
            started_by=self.starter,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.source_step,
            to_step=self.destination_step,
            name="Source to Destination",
            requires_acceptance=True,
        )
        self.transition_execution = WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=self.transition,
            performed_by=self.actor,
            status=WorkflowTransitionExecution.Status.PENDING,
        )
        self.source_execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.source_step,
            performed_by=self.completer,
            completed_by=self.completer,
            is_submitted=True,
        )
        self.result_execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.destination_step,
            performed_by=self.actor,
            assigned_to=self.assignee,
        )

    def resolve(self, outcome, policy, **kwargs):
        field = (
            "accept_notification_policy"
            if outcome == "ACCEPT"
            else "reject_notification_policy"
        )
        setattr(self.transition, field, policy)
        self.transition.save(update_fields=[field])
        return WorkflowTransitionNotificationService.resolve_recipient(
            transition=self.transition,
            instance=self.instance,
            outcome=outcome,
            source_execution=kwargs.get("source_execution", self.source_execution),
            result_execution=kwargs.get("result_execution", self.result_execution),
        )

    def test_source_completer_policy_uses_completed_by_not_transition_actor(self):
        result = self.resolve("ACCEPT", WorkflowTransition.NotificationRecipientPolicy.SOURCE_COMPLETER)

        self.assertEqual(result["recipient"], self.completer)
        self.assertNotEqual(result["recipient"], self.actor)

    def test_fixed_user_policy_uses_outcome_specific_user(self):
        self.transition.accept_notification_policy = WorkflowTransition.NotificationRecipientPolicy.FIXED_USER
        self.transition.accept_notification_user = self.fixed_user
        self.transition.save(update_fields=["accept_notification_policy", "accept_notification_user"])

        result = WorkflowTransitionNotificationService.resolve_recipient(
            transition=self.transition,
            instance=self.instance,
            outcome="ACCEPT",
            source_execution=self.source_execution,
            result_execution=self.result_execution,
        )

        self.assertEqual(result["recipient"], self.fixed_user)

    def test_return_step_assignee_uses_assignee_of_new_execution(self):
        result = self.resolve("REJECT", WorkflowTransition.NotificationRecipientPolicy.RETURN_STEP_ASSIGNEE)

        self.assertEqual(result["recipient"], self.assignee)

    def test_workflow_starter_policy_uses_instance_starter(self):
        result = self.resolve("ACCEPT", WorkflowTransition.NotificationRecipientPolicy.WORKFLOW_STARTER)

        self.assertEqual(result["recipient"], self.starter)

    def test_missing_source_completer_returns_failure_without_fallback(self):
        self.source_execution.completed_by = None
        self.source_execution.save(update_fields=["completed_by"])

        result = self.resolve("REJECT", WorkflowTransition.NotificationRecipientPolicy.SOURCE_COMPLETER)

        self.assertIsNone(result["recipient"])
        self.assertEqual(result["error_code"], "SOURCE_COMPLETER_MISSING")
        self.assertNotEqual(result["recipient"], self.actor)

    def test_missing_result_assignee_returns_failure_without_step_fallback(self):
        self.result_execution.assigned_to = None
        self.result_execution.save(update_fields=["assigned_to"])

        result = self.resolve("REJECT", WorkflowTransition.NotificationRecipientPolicy.RETURN_STEP_ASSIGNEE)

        self.assertIsNone(result["recipient"])
        self.assertEqual(result["error_code"], "RESULT_ASSIGNEE_MISSING")

    def test_inactive_fixed_user_returns_failure(self):
        self.fixed_user.is_active = False
        self.fixed_user.save(update_fields=["is_active"])
        self.transition.accept_notification_policy = WorkflowTransition.NotificationRecipientPolicy.FIXED_USER
        self.transition.accept_notification_user = self.fixed_user
        self.transition.save(update_fields=["accept_notification_policy", "accept_notification_user"])

        result = WorkflowTransitionNotificationService.resolve_recipient(
            transition=self.transition,
            instance=self.instance,
            outcome="ACCEPT",
            source_execution=self.source_execution,
            result_execution=self.result_execution,
        )

        self.assertIsNone(result["recipient"])
        self.assertEqual(result["error_code"], "RECIPIENT_INACTIVE")

    def test_missing_recipient_records_issue_and_does_not_create_notification(self):
        self.source_execution.completed_by = None
        self.source_execution.save(update_fields=["completed_by"])

        result = WorkflowTransitionNotificationService.notify_outcome(
            transition=self.transition,
            transition_execution=self.transition_execution,
            instance=self.instance,
            outcome="ACCEPT",
            source_execution=self.source_execution,
            result_execution=self.result_execution,
        )

        self.assertIsNone(result["recipient"])
        self.assertEqual(
            WorkflowTransitionNotificationIssue.objects.count(),
            1,
        )
        issue = WorkflowTransitionNotificationIssue.objects.get()
        self.assertEqual(issue.outcome, "ACCEPT")
        self.assertEqual(issue.error_code, "SOURCE_COMPLETER_MISSING")
        self.assertEqual(Notification.objects.count(), 0)

    def test_successful_resolution_creates_one_notification_for_recipient(self):
        result = WorkflowTransitionNotificationService.notify_outcome(
            transition=self.transition,
            transition_execution=self.transition_execution,
            instance=self.instance,
            outcome="ACCEPT",
            source_execution=self.source_execution,
            result_execution=self.result_execution,
        )

        self.assertEqual(result["recipient"], self.completer)
        self.assertEqual(Notification.objects.count(), 1)
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.completer)
        self.assertEqual(notification.transition_execution, self.transition_execution)
        self.assertEqual(WorkflowTransitionNotificationIssue.objects.count(), 0)


    def test_reject_fixed_user_is_independent_from_accept_fixed_user(self):
        reject_user = get_user_model().objects.create_user(
            username="reject-fixed-recipient",
            password="test-password",
        )
        self.transition.accept_notification_policy = WorkflowTransition.NotificationRecipientPolicy.FIXED_USER
        self.transition.accept_notification_user = self.fixed_user
        self.transition.reject_notification_policy = WorkflowTransition.NotificationRecipientPolicy.FIXED_USER
        self.transition.reject_notification_user = reject_user
        self.transition.save(update_fields=[
            "accept_notification_policy",
            "accept_notification_user",
            "reject_notification_policy",
            "reject_notification_user",
        ])

        result = WorkflowTransitionNotificationService.resolve_recipient(
            transition=self.transition,
            instance=self.instance,
            outcome="REJECT",
            source_execution=self.source_execution,
            result_execution=self.result_execution,
        )

        self.assertEqual(result["recipient"], reject_user)
        self.assertNotEqual(result["recipient"], self.fixed_user)

    def test_missing_source_execution_returns_failure(self):
        result = self.resolve(
            "ACCEPT",
            WorkflowTransition.NotificationRecipientPolicy.SOURCE_COMPLETER,
            source_execution=None,
        )

        self.assertIsNone(result["recipient"])
        self.assertEqual(result["error_code"], "SOURCE_EXECUTION_MISSING")

    def test_missing_result_execution_returns_failure(self):
        result = self.resolve(
            "REJECT",
            WorkflowTransition.NotificationRecipientPolicy.RETURN_STEP_ASSIGNEE,
            result_execution=None,
        )

        self.assertIsNone(result["recipient"])
        self.assertEqual(result["error_code"], "RESULT_EXECUTION_MISSING")

    def test_missing_workflow_starter_returns_failure(self):
        self.instance.started_by = None
        self.instance.save(update_fields=["started_by"])

        result = self.resolve(
            "ACCEPT",
            WorkflowTransition.NotificationRecipientPolicy.WORKFLOW_STARTER,
        )

        self.assertIsNone(result["recipient"])
        self.assertEqual(result["error_code"], "WORKFLOW_STARTER_MISSING")

    def test_invalid_outcome_is_rejected(self):
        with self.assertRaises(ValueError):
            WorkflowTransitionNotificationService.resolve_recipient(
                transition=self.transition,
                instance=self.instance,
                outcome="CANCEL",
                source_execution=self.source_execution,
                result_execution=self.result_execution,
            )
