from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from workflow.models import (
    FieldAccess,
    FormDefinition,
    FormField,
    FormSection,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)


User = get_user_model()


class PendingRejectionAssignmentTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            username="reject_assignment_sender",
            password="test-password",
        )
        self.rejector = User.objects.create_user(
            username="reject_assignment_rejector",
            password="test-password",
        )
        self.candidate = User.objects.create_user(
            username="reject_assignment_candidate",
            password="test-password",
        )
        self.unqualified = User.objects.create_user(
            username="reject_assignment_unqualified",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Pending Rejection Assignment",
            code="PENDING_REJECTION_ASSIGNMENT",
            is_active=True,
        )
        self.source_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Review",
            code="PENDING_REJECTION_REVIEW",
            order=1,
            is_active=True,
        )
        self.destination_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Receive",
            code="PENDING_REJECTION_RECEIVE",
            order=2,
            is_active=True,
        )
        self.return_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Return",
            code="PENDING_REJECTION_RETURN",
            order=3,
            is_active=True,
            assignment_policy=WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Pending Rejection Form",
            is_active=True,
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Main",
            code="PENDING_REJECTION_SECTION",
            order=1,
        )
        self.field = FormField.objects.create(
            section=self.section,
            name="Description",
            code="description",
            label="Description",
            field_type=FormField.FieldType.TEXT,
            order=1,
            is_active=True,
        )
        FieldAccess.objects.create(
            field=self.field,
            step=self.destination_step,
            user=self.rejector,
            can_view=True,
            can_edit=False,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Review to Receive",
            code="PENDING_REJECTION_TRANSITION",
            from_step=self.source_step,
            to_step=self.destination_step,
            reject_to_step=self.return_step,
            requires_acceptance=True,
            is_active=True,
        )

        for user in (self.sender, self.rejector, self.candidate, self.unqualified):
            WorkflowMembership.objects.create(
                workflow=self.workflow,
                user=user,
                role=WorkflowMembership.Role.EXECUTOR,
                is_active=True,
            )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.destination_step,
            user=self.rejector,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="REJECT",
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.return_step,
            user=self.candidate,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.source_step,
            started_by=self.sender,
            status=WorkflowInstance.Status.ACTIVE,
        )
        self.transition_execution = WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=self.transition,
            performed_by=self.sender,
            status=WorkflowTransitionExecution.Status.PENDING,
        )
        # The REJECT-specific manual choice must not depend on a historical
        # completed_by value; it is the rejector who chooses the return owner.
        WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.source_step,
            performed_by=self.sender,
            is_submitted=True,
            submitted_at=timezone.now() - timedelta(minutes=1),
        )
        self.client.force_login(self.rejector)

    def test_pending_detail_shows_only_eligible_return_step_candidates(self):
        response = self.client.get(
            reverse(
                "operator_panel:pending_acceptance_detail",
                args=[self.transition_execution.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["pending_acceptance_reject_requires_assignee"])
        self.assertEqual(
            [user.pk for user in response.context["pending_acceptance_reject_candidates"]],
            [self.candidate.pk],
        )
        self.assertContains(response, 'name="selected_assignee"')
        self.assertContains(response, self.candidate.username)
        self.assertNotContains(response, self.unqualified.username)

    def test_reject_uses_selected_assignee_and_records_rejection_history(self):
        response = self.client.post(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[self.transition_execution.pk],
            ),
            {"selected_assignee": str(self.candidate.pk)},
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )
        self.transition_execution.refresh_from_db()
        self.instance.refresh_from_db()

        self.assertEqual(
            self.transition_execution.status,
            WorkflowTransitionExecution.Status.REJECTED,
        )
        self.assertEqual(self.transition_execution.rejected_by, self.rejector)
        self.assertEqual(self.instance.current_step_id, self.return_step.pk)

        return_execution = WorkflowStepExecution.objects.get(
            instance=self.instance,
            workflow_step=self.return_step,
            is_submitted=False,
        )
        self.assertEqual(return_execution.assigned_to_id, self.candidate.pk)
        self.assertEqual(return_execution.entered_by_id, self.rejector.pk)
        self.assertEqual(return_execution.performed_by_id, self.rejector.pk)

        history = WorkflowStepAssignmentHistory.objects.get(
            step_execution=return_execution,
        )
        self.assertEqual(history.new_assignee_id, self.candidate.pk)
        self.assertEqual(history.changed_by_id, self.rejector.pk)
        self.assertEqual(
            history.source,
            WorkflowStepAssignmentHistory.Source.REJECTION,
        )

    def test_reject_without_required_selection_keeps_pending_unchanged(self):
        response = self.client.post(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[self.transition_execution.pk],
            ),
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )
        self.transition_execution.refresh_from_db()
        self.instance.refresh_from_db()

        self.assertEqual(
            self.transition_execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )
        self.assertEqual(self.instance.current_step_id, self.source_step.pk)
        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.return_step,
            ).exists()
        )
        self.assertFalse(
            WorkflowStepAssignmentHistory.objects.filter(
                step_execution__instance=self.instance,
                step_execution__workflow_step=self.return_step,
            ).exists()
        )

    def test_reject_fails_closed_for_invalid_previous_completer_policy_configuration(self):
        self.return_step.assignment_source_step = self.source_step
        self.return_step.save(update_fields=["assignment_source_step"])

        response = self.client.post(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[self.transition_execution.pk],
            ),
            {"selected_assignee": str(self.candidate.pk)},
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )
        self.transition_execution.refresh_from_db()
        self.instance.refresh_from_db()

        self.assertEqual(
            self.transition_execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )
        self.assertEqual(self.instance.current_step_id, self.source_step.pk)
        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.return_step,
            ).exists()
        )

    def test_reject_revalidates_selected_user_execute_permission(self):
        response = self.client.post(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[self.transition_execution.pk],
            ),
            {"selected_assignee": str(self.unqualified.pk)},
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )
        self.transition_execution.refresh_from_db()
        self.instance.refresh_from_db()

        self.assertEqual(
            self.transition_execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )
        self.assertEqual(self.instance.current_step_id, self.source_step.pk)
        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.return_step,
            ).exists()
        )

    def test_non_manual_return_policy_keeps_policy_resolution_and_rejects_manual_input(self):
        self.return_step.assignment_policy = WorkflowStep.AssignmentPolicy.FIXED
        self.return_step.assigned_to = self.candidate
        self.return_step.save(update_fields=["assignment_policy", "assigned_to"])

        response = self.client.post(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[self.transition_execution.pk],
            ),
            {"selected_assignee": str(self.candidate.pk)},
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )
        self.transition_execution.refresh_from_db()
        self.instance.refresh_from_db()

        self.assertEqual(
            self.transition_execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )
        self.assertEqual(self.instance.current_step_id, self.source_step.pk)
        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.return_step,
            ).exists()
        )

    def test_non_manual_return_policy_still_uses_configured_assignee(self):
        self.return_step.assignment_policy = WorkflowStep.AssignmentPolicy.FIXED
        self.return_step.assigned_to = self.candidate
        self.return_step.save(update_fields=["assignment_policy", "assigned_to"])

        response = self.client.post(
            reverse(
                "operator_panel:reject_pending_acceptance",
                args=[self.transition_execution.pk],
            ),
        )

        self.assertRedirects(
            response,
            reverse("operator_panel:pending_acceptances"),
        )
        self.transition_execution.refresh_from_db()
        self.instance.refresh_from_db()

        self.assertEqual(
            self.transition_execution.status,
            WorkflowTransitionExecution.Status.REJECTED,
        )
        self.assertEqual(self.instance.current_step_id, self.return_step.pk)
        return_execution = WorkflowStepExecution.objects.get(
            instance=self.instance,
            workflow_step=self.return_step,
        )
        self.assertEqual(return_execution.assigned_to_id, self.candidate.pk)
        history = WorkflowStepAssignmentHistory.objects.get(
            step_execution=return_execution,
        )
        self.assertEqual(
            history.source,
            WorkflowStepAssignmentHistory.Source.REJECTION,
        )
