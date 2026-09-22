from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
    WorkflowStepExecution,
)


User = get_user_model()


class PermissionIntegrationTests(TestCase):
    """HTTP-level integration tests for the workflow permission contract."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="permission-integration-user",
            password="test-password",
        )
        self.other_user = User.objects.create_user(
            username="permission-integration-other",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Permission Integration Workflow",
            code="PERMISSION_INTEGRATION_WF",
            is_active=True,
        )
        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Integration Step One",
            code="PERMISSION_INTEGRATION_STEP_ONE",
            order=1,
            is_active=True,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Integration Step Two",
            code="PERMISSION_INTEGRATION_STEP_TWO",
            order=2,
            is_active=True,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Integration Transition",
            code="PERMISSION_INTEGRATION_TRANSITION",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.other_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

    def grant_permission(self, *, user, action, transition=None):
        return WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=user,
            transition=transition,
            action=action,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def create_instance(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_one,
            started_by=self.other_user,
            status=WorkflowInstance.Status.ACTIVE,
        )
        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step_one,
            performed_by=self.other_user,
        )
        return instance

    def test_instance_endpoint_enforces_view_permission(self):
        instance = self.create_instance()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[instance.pk],
            ),
        )

        self.assertEqual(response.status_code, 403)

        self.grant_permission(
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
        )

        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[instance.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)

    def test_transition_endpoint_rejects_execute_without_transition_permission(self):
        instance = self.create_instance()
        self.client.force_login(self.user)

        self.grant_permission(
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
        )
        self.grant_permission(
            user=self.user,
            action=WorkflowPermission.Action.EXECUTE,
        )

        response = self.client.post(
            reverse(
                "operator_panel:execute_transition",
                args=[instance.pk, self.transition.pk],
            ),
        )

        self.assertEqual(response.status_code, 403)

        instance.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_one.pk)

    def test_transition_endpoint_advances_instance_with_transition_permission(self):
        instance = self.create_instance()
        self.client.force_login(self.user)

        self.grant_permission(
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
        )
        self.grant_permission(
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            transition=self.transition,
        )

        response = self.client.post(
            reverse(
                "operator_panel:execute_transition",
                args=[instance.pk, self.transition.pk],
            ),
        )

        self.assertEqual(response.status_code, 302)

        instance.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_two.pk)
