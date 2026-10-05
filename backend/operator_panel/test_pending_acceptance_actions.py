from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)


User = get_user_model()


class PendingAcceptanceActionViewTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            username="pending_action_sender",
            password="test-password",
        )
        self.receiver = User.objects.create_user(
            username="pending_action_receiver",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Pending Action Workflow",
            code="PENDING_ACTION_WORKFLOW",
            is_active=True,
        )
        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Send",
            code="PENDING_ACTION_SEND",
            order=1,
            is_active=True,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Receive",
            code="PENDING_ACTION_RECEIVE",
            order=2,
            is_active=True,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Send to Receive",
            code="PENDING_ACTION_TRANSITION",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
            requires_acceptance=True,
            reject_to_step=self.step_one,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.sender,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.receiver,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_two,
            user=self.receiver,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_two,
            user=self.receiver,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="REJECT",
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_one,
            started_by=self.sender,
            status=WorkflowInstance.Status.ACTIVE,
        )
        self.execution = WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=self.transition,
            performed_by=self.sender,
            status=WorkflowTransitionExecution.Status.PENDING,
        )

        self.client.force_login(self.receiver)

    def test_accept_endpoint_resolves_pending_execution_and_redirects_to_queue(self):
        response = self.client.post(
            reverse(
                "operator_panel:accept_pending_acceptance",
                args=[self.execution.pk],
            )
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )

        self.execution.refresh_from_db()
        self.instance.refresh_from_db()

        self.assertEqual(
            self.execution.status,
            WorkflowTransitionExecution.Status.ACCEPTED,
        )
        self.assertEqual(self.execution.accepted_by, self.receiver)
        self.assertIsNone(self.execution.rejected_by)
        self.assertEqual(self.instance.current_step, self.step_two)
        self.assertTrue(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.step_two,
                performed_by=self.receiver,
            ).exists()
        )
        self.assertFalse(
            WorkflowTransitionExecution.objects.filter(
                pk=self.execution.pk,
                status=WorkflowTransitionExecution.Status.PENDING,
            ).exists()
        )

    def test_reject_endpoint_resolves_pending_execution_and_returns_to_reject_target(self):
        response = self.client.post(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[self.execution.pk],
            )
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )

        self.execution.refresh_from_db()
        self.instance.refresh_from_db()

        self.assertEqual(
            self.execution.status,
            WorkflowTransitionExecution.Status.REJECTED,
        )
        self.assertEqual(self.execution.rejected_by, self.receiver)
        self.assertIsNone(self.execution.accepted_by)
        self.assertEqual(self.instance.current_step, self.step_one)
        self.assertTrue(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.step_one,
                performed_by=self.receiver,
            ).exists()
        )

    def test_accept_and_reject_endpoints_require_post(self):
        accept_response = self.client.get(
            reverse(
                "operator_panel:accept_pending_acceptance",
                args=[self.execution.pk],
            )
        )
        reject_response = self.client.get(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[self.execution.pk],
            )
        )

        self.assertEqual(accept_response.status_code, 405)
        self.assertEqual(reject_response.status_code, 405)

    def test_action_endpoint_denies_user_who_is_not_in_pending_queue(self):
        outsider = User.objects.create_user(
            username="pending_action_outsider",
            password="test-password",
        )
        self.client.force_login(outsider)

        response = self.client.post(
            reverse(
                "operator_panel:accept_pending_acceptance",
                args=[self.execution.pk],
            )
        )

        self.assertEqual(response.status_code, 403)
        self.execution.refresh_from_db()
        self.assertEqual(
            self.execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )

    def test_accept_endpoint_cannot_resolve_execution_twice(self):
        self.client.post(
            reverse(
                "operator_panel:accept_pending_acceptance",
                args=[self.execution.pk],
            )
        )

        response = self.client.post(
            reverse(
                "operator_panel:accept_pending_acceptance",
                args=[self.execution.pk],
            )
        )

        self.assertEqual(response.status_code, 403)
        self.execution.refresh_from_db()
        self.assertEqual(
            self.execution.status,
            WorkflowTransitionExecution.Status.ACCEPTED,
        )

