from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from workflow.acceptance_queue_services import PendingAcceptanceQueueService
from workflow.services import WorkflowExecutionService
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



class PendingAcceptanceEndToEndTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            username="pending_e2e_sender",
            password="test-password",
        )
        self.receiver = User.objects.create_user(
            username="pending_e2e_receiver",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Pending Acceptance E2E Workflow",
            code="PENDING_ACCEPTANCE_E2E_WORKFLOW",
            is_active=True,
        )
        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Send",
            code="PENDING_E2E_SEND",
            order=1,
            is_active=True,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Review",
            code="PENDING_E2E_REVIEW",
            order=2,
            is_active=True,
        )
        self.step_three = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Receive",
            code="PENDING_E2E_RECEIVE",
            order=3,
            is_active=True,
        )

        self.step_one_to_two = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Send to Review",
            code="PENDING_E2E_SEND_TO_REVIEW",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )
        self.step_two_to_three = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Review to Receive",
            code="PENDING_E2E_REVIEW_TO_RECEIVE",
            from_step=self.step_two,
            to_step=self.step_three,
            is_active=True,
            requires_acceptance=True,
            reject_to_step=self.step_one,
        )

        for user in (self.sender, self.receiver):
            WorkflowMembership.objects.create(
                workflow=self.workflow,
                user=user,
                role=WorkflowMembership.Role.EXECUTOR,
                is_active=True,
            )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.sender,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.step_one_to_two,
            user=self.sender,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.step_two_to_three,
            user=self.sender,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        for action_code in ("ACCEPT", "REJECT"):
            WorkflowPermission.objects.create(
                workflow=self.workflow,
                step=self.step_three,
                user=self.receiver,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code=action_code,
                effect=WorkflowPermission.Effect.ALLOW,
            )

    def _create_real_pending_execution(self):
        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.sender,
        )
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.step_one_to_two,
            user=self.sender,
        )
        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.step_two_to_three,
            user=self.sender,
        )
        return instance, transition_execution

    def test_full_accept_lifecycle(self):
        instance, transition_execution = self._create_real_pending_execution()

        instance.refresh_from_db()
        transition_execution.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_two.pk)
        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )
        self.assertEqual(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=transition_execution.pk)
            .count(),
            1,
        )

        self.client.force_login(self.receiver)
        response = self.client.post(
            reverse(
                "operator_panel:accept_pending_acceptance",
                args=[transition_execution.pk],
            )
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )

        instance.refresh_from_db()
        transition_execution.refresh_from_db()

        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.ACCEPTED,
        )
        self.assertEqual(transition_execution.accepted_by, self.receiver)
        self.assertIsNone(transition_execution.rejected_by)
        self.assertEqual(instance.current_step_id, self.step_three.pk)
        self.assertTrue(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_one,
            ).count()
            == 1
        )
        self.assertTrue(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_two,
            ).count()
            == 1
        )
        self.assertTrue(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_three,
                performed_by=self.receiver,
            ).count()
            == 1
        )
        self.assertEqual(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=transition_execution.pk)
            .count(),
            0,
        )

    def test_full_reject_lifecycle(self):
        instance, transition_execution = self._create_real_pending_execution()

        instance.refresh_from_db()
        transition_execution.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_two.pk)
        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )
        self.assertEqual(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=transition_execution.pk)
            .count(),
            1,
        )

        self.client.force_login(self.receiver)
        response = self.client.post(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[transition_execution.pk],
            )
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )

        instance.refresh_from_db()
        transition_execution.refresh_from_db()

        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.REJECTED,
        )
        self.assertEqual(transition_execution.rejected_by, self.receiver)
        self.assertIsNone(transition_execution.accepted_by)
        self.assertEqual(instance.current_step_id, self.step_one.pk)
        self.assertEqual(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_one,
            ).count(),
            2,
        )
        self.assertEqual(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_two,
            ).count(),
            1,
        )
        self.assertEqual(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_three,
            ).count(),
            0,
        )
        self.assertEqual(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=transition_execution.pk)
            .count(),
            0,
        )
