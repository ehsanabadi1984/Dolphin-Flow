from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from workflow.history_models import HistoryConfiguration, HistoryField
from workflow.models import (
    FormData,
    FormDefinition,
    FormField,
    FormSection,
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

    def grant_start_permission(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
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
        self.grant_start_permission()
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

    def test_submit_valid_form_advances_workflow_and_stores_history(self):
        self.grant_execute_permission()
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Execution Submit Form",
            is_active=True,
        )

        section = FormSection.objects.create(
            form=form,
            name="Main Section",
            code="MAIN",
            order=1,
            is_active=True,
        )

        field = FormField.objects.create(
            section=section,
            name="Customer Name",
            code="customer_name",
            field_type=FormField.FieldType.TEXT,
            label="Customer Name",
            is_required=True,
            order=1,
            is_active=True,
        )

        history_configuration = HistoryConfiguration.objects.create(
            form=form,
            name="Execution History",
            is_active=True,
        )

        HistoryField.objects.create(
            configuration=history_configuration,
            form_field=field,
            display_label="Customer Name",
            display_order=1,
            is_enabled=True,
        )

        instance = self.start_instance()

        FormData.objects.create(
            instance=instance,
            data={
                "customer_name": "Ehsan",
            },
        )

        step_execution = WorkflowStepExecution.objects.get(
            instance=instance,
            workflow_step=self.step_one,
        )

        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        instance.refresh_from_db()
        step_execution.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )

        self.assertIsNotNone(
            transition_execution,
        )

        self.assertTrue(
            step_execution.is_submitted,
        )

        self.assertIsNotNone(
            step_execution.submitted_at,
        )

        self.assertIn(
            "history",
            step_execution.data,
        )

        history = step_execution.data["history"]

        self.assertEqual(
            history["version"],
            1,
        )

        self.assertEqual(
            len(history["fields"]),
            1,
        )

        self.assertEqual(
            history["fields"][0]["code"],
            "customer_name",
        )

        self.assertEqual(
            history["fields"][0]["value"],
            "Ehsan",
        )

        self.assertTrue(
            WorkflowTransitionExecution.objects.filter(
                pk=transition_execution.pk,
                instance=instance,
                transition=self.transition_one,
            ).exists()
        )

        self.assertTrue(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_two,
            ).exists()
        )

    def test_submit_invalid_form_does_not_advance_workflow_or_store_history(self):
        self.grant_execute_permission()
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Invalid Submit Form",
            is_active=True,
        )

        section = FormSection.objects.create(
            form=form,
            name="Main Section",
            code="MAIN",
            order=1,
            is_active=True,
        )

        field = FormField.objects.create(
            section=section,
            name="Customer Name",
            code="customer_name",
            field_type=FormField.FieldType.TEXT,
            label="Customer Name",
            is_required=True,
            order=1,
            is_active=True,
        )

        instance = self.start_instance()

        FormData.objects.create(
            instance=instance,
            data={
                "customer_name": "",
            },
        )

        step_execution = WorkflowStepExecution.objects.get(
            instance=instance,
            workflow_step=self.step_one,
        )

        with self.assertRaises(ValidationError):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()
        step_execution.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_one.pk,
        )

        self.assertFalse(
            step_execution.is_submitted,
        )

        self.assertIsNone(
            step_execution.submitted_at,
        )

        self.assertNotIn(
            "history",
            step_execution.data,
        )

        self.assertFalse(
            WorkflowTransitionExecution.objects.filter(
                instance=instance,
                transition=self.transition_one,
            ).exists()
        )

        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_two,
            ).exists()
        )

    def test_deny(self):
        self.grant_execute_permission()
        self.grant_start_permission()

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
        self.grant_start_permission()

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
        self.grant_start_permission()
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
