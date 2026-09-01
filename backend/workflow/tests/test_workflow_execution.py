from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from workflow.models import (
    Notification,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)
from workflow.services import WorkflowExecutionService


User = get_user_model()


class WorkflowExecutionTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="auth_exec_user",
            password="test-password",
        )

        self.destination_user = User.objects.create_user(
            username="auth_exec_destination",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Authorization Execution Test",
            code="AUTH_EXEC_TEST",
            is_active=True,
        )

        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step One",
            code="AUTH_EXEC_STEP_ONE",
            order=1,
            is_active=True,
        )

        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step Two",
            code="AUTH_EXEC_STEP_TWO",
            order=2,
            is_active=True,
        )

        self.step_three = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step Three",
            code="AUTH_EXEC_STEP_THREE",
            order=3,
            is_active=True,
        )

        self.transition_one = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Test Transition One",
            code="AUTH_EXEC_TRANSITION_ONE",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )

        self.transition_two = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Test Transition Two",
            code="AUTH_EXEC_TRANSITION_TWO",
            from_step=self.step_two,
            to_step=self.step_three,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

    def grant_execute_permission(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def grant_transition_permission(self, transition):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=transition,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def start_instance(self):
        return WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

    def test_allow(self):
        self.grant_execute_permission()
        self.grant_transition_permission(self.transition_one)

        instance = self.start_instance()

        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        instance.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )

    def test_deny(self):
        self.grant_execute_permission()

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.transition_one,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.DENY,
        )

        instance = self.start_instance()

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_one.pk,
        )

    def test_no_permission(self):
        self.grant_execute_permission()

        instance = self.start_instance()

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_one.pk,
        )

    def test_transition_creates_notification_for_destination_executors(self):
        self.grant_execute_permission()
        self.grant_transition_permission(self.transition_one)

        # Assign destination step to a different user
        self.step_two.assigned_to = self.destination_user
        self.step_two.save(update_fields=["assigned_to"])

        instance = self.start_instance()

        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        notification = Notification.objects.get(
            recipient=self.destination_user,
            workflow_instance=instance,
            workflow_step=self.step_two,
        )

        self.assertEqual(
            notification.notification_type,
            Notification.NotificationType.ACTION_REQUIRED,
        )

        self.assertIsNotNone(
            notification.transition_execution,
        )

        self.assertFalse(
            notification.is_read,
        )