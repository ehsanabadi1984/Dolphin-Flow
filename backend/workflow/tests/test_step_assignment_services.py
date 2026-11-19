from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.assignment_services import WorkflowStepAssignmentService
from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
)


User = get_user_model()


class WorkflowStepAssignmentServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(name="Assignment workflow")
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Target",
            order=1,
        )
        self.source_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Source",
            order=2,
        )
        self.other_workflow = Workflow.objects.create(name="Other workflow")
        self.other_step = WorkflowStep.objects.create(
            workflow=self.other_workflow,
            name="Other target",
            order=1,
        )
        self.starter = self.make_user("starter")
        self.candidate_a = self.make_user("candidate-a")
        self.candidate_b = self.make_user("candidate-b")
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.starter,
        )
        self.add_member(self.starter)
        self.add_member(self.candidate_a)
        self.add_member(self.candidate_b)
        self.grant_execute(self.candidate_a, self.step)
        self.grant_execute(self.candidate_b, self.step)

    def make_user(self, username, *, is_active=True):
        return User.objects.create_user(
            username=username,
            password="test-password",
            is_active=is_active,
        )

    def add_member(self, user, *, active=True):
        return WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=active,
        )

    def grant_execute(self, user, step, *, effect=WorkflowPermission.Effect.ALLOW):
        return WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=step,
            user=user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="EXECUTE",
            effect=effect,
        )

    def make_execution(self, step=None, *, completed_by=None):
        return WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=step or self.step,
            performed_by=self.starter,
            completed_by=completed_by,
            is_submitted=completed_by is not None,
        )

    def test_candidates_use_effective_step_action_execute_permission(self):
        users = WorkflowStepAssignmentService.get_eligible_assignees(
            workflow=self.workflow,
            step=self.step,
        )
        self.assertEqual(
            {user.pk for user in users},
            {self.candidate_a.pk, self.candidate_b.pk},
        )

    def test_candidates_exclude_user_denied_despite_role_allow(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="EXECUTE",
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.grant_execute(
            self.candidate_a,
            self.step,
            effect=WorkflowPermission.Effect.DENY,
        )

        users = WorkflowStepAssignmentService.get_eligible_assignees(
            workflow=self.workflow,
            step=self.step,
        )
        self.assertNotIn(self.candidate_a.pk, {user.pk for user in users})
        self.assertIn(self.candidate_b.pk, {user.pk for user in users})

    def test_candidates_reject_step_from_another_workflow(self):
        self.assertEqual(
            WorkflowStepAssignmentService.get_eligible_assignees(
                workflow=self.workflow,
                step=self.other_step,
            ),
            [],
        )

    def test_validate_rejects_inactive_user(self):
        inactive = self.make_user("inactive", is_active=False)
        self.add_member(inactive)
        self.grant_execute(inactive, self.step)
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.validate_assignee(
                workflow=self.workflow,
                step=self.step,
                assignee=inactive,
            )

    def test_validate_rejects_inactive_membership(self):
        inactive_member = self.make_user("inactive-member")
        self.add_member(inactive_member, active=False)
        self.grant_execute(inactive_member, self.step)
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.validate_assignee(
                workflow=self.workflow,
                step=self.step,
                assignee=inactive_member,
            )

    def test_validate_rejects_user_without_effective_execute(self):
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.validate_assignee(
                workflow=self.workflow,
                step=self.step,
                assignee=self.starter,
            )

    def test_validate_rejects_step_workflow_mismatch(self):
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.validate_assignee(
                workflow=self.workflow,
                step=self.other_step,
                assignee=self.candidate_a,
            )

    def test_fixed_policy_resolves_and_validates_assignee(self):
        self.step.assignment_policy = WorkflowStep.AssignmentPolicy.FIXED
        self.step.assigned_to = self.candidate_a
        self.step.save()
        resolved = WorkflowStepAssignmentService.resolve_assignee(
            workflow=self.workflow,
            step=self.step,
            instance=self.instance,
        )
        self.assertEqual(resolved.pk, self.candidate_a.pk)

    def test_instance_starter_policy_requires_eligible_starter(self):
        self.step.assignment_policy = WorkflowStep.AssignmentPolicy.INSTANCE_STARTER
        self.step.save()
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.resolve_assignee(
                workflow=self.workflow,
                step=self.step,
                instance=self.instance,
            )

        self.grant_execute(self.starter, self.step)
        resolved = WorkflowStepAssignmentService.resolve_assignee(
            workflow=self.workflow,
            step=self.step,
            instance=self.instance,
        )
        self.assertEqual(resolved.pk, self.starter.pk)

    def test_step_completer_policy_uses_latest_source_execution(self):
        self.step.assignment_policy = WorkflowStep.AssignmentPolicy.STEP_COMPLETER
        self.step.assignment_source_step = self.source_step
        self.step.save()
        source_execution = self.make_execution(
            self.source_step,
            completed_by=self.candidate_b,
        )
        resolved = WorkflowStepAssignmentService.resolve_assignee(
            workflow=self.workflow,
            step=self.step,
            instance=self.instance,
        )
        self.assertEqual(resolved.pk, self.candidate_b.pk)
        self.assertEqual(source_execution.completed_by_id, resolved.pk)

    def test_step_completer_rejects_missing_or_invalid_source_step(self):
        self.step.assignment_policy = WorkflowStep.AssignmentPolicy.STEP_COMPLETER
        self.step.assignment_source_step = None
        self.step.save()
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.resolve_assignee(
                workflow=self.workflow,
                step=self.step,
                instance=self.instance,
            )

        self.step.assignment_source_step = self.other_step
        self.step.save()
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.resolve_assignee(
                workflow=self.workflow,
                step=self.step,
                instance=self.instance,
            )

    def test_previous_completer_selects_only_an_eligible_selected_user(self):
        self.step.assignment_policy = (
            WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS
        )
        self.step.save()
        previous = self.make_execution(self.source_step, completed_by=self.starter)
        resolved = WorkflowStepAssignmentService.resolve_assignee(
            workflow=self.workflow,
            step=self.step,
            instance=self.instance,
            previous_execution=previous,
            selected_assignee=self.candidate_a,
        )
        self.assertEqual(resolved.pk, self.candidate_a.pk)

        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.resolve_assignee(
                workflow=self.workflow,
                step=self.step,
                instance=self.instance,
                previous_execution=previous,
                selected_assignee=self.starter,
            )

    def test_auto_single_requires_exactly_one_candidate(self):
        self.step.assignment_policy = WorkflowStep.AssignmentPolicy.AUTO_SINGLE
        self.step.save()
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.resolve_assignee(
                workflow=self.workflow,
                step=self.step,
                instance=self.instance,
            )

        self.grant_execute(
            self.candidate_b,
            self.step,
            effect=WorkflowPermission.Effect.DENY,
        )
        resolved = WorkflowStepAssignmentService.resolve_assignee(
            workflow=self.workflow,
            step=self.step,
            instance=self.instance,
        )
        self.assertEqual(resolved.pk, self.candidate_a.pk)

    def test_assign_execution_records_initial_history(self):
        execution = self.make_execution()
        WorkflowStepAssignmentService.assign_execution(
            execution=execution,
            assignee=self.candidate_a,
            changed_by=self.starter,
            source=WorkflowStepAssignmentHistory.Source.INITIAL,
        )
        execution.refresh_from_db()
        history = execution.assignment_history.get()
        self.assertEqual(execution.assigned_to_id, self.candidate_a.pk)
        self.assertIsNotNone(execution.assigned_at)
        self.assertIsNone(history.previous_assignee_id)
        self.assertEqual(history.new_assignee_id, self.candidate_a.pk)
        self.assertEqual(history.changed_by_id, self.starter.pk)

    def test_assign_execution_is_idempotent_for_same_assignee(self):
        execution = self.make_execution()
        for _ in range(2):
            WorkflowStepAssignmentService.assign_execution(
                execution=execution,
                assignee=self.candidate_a,
            )
        self.assertEqual(execution.assignment_history.count(), 1)

    def test_assign_execution_records_assignee_change(self):
        execution = self.make_execution()
        WorkflowStepAssignmentService.assign_execution(
            execution=execution,
            assignee=self.candidate_a,
        )
        WorkflowStepAssignmentService.assign_execution(
            execution=execution,
            assignee=self.candidate_b,
            changed_by=self.starter,
            source=WorkflowStepAssignmentHistory.Source.MANUAL,
            reason="تغییر مسئول",
        )
        history = list(execution.assignment_history.order_by("pk"))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1].previous_assignee_id, self.candidate_a.pk)
        self.assertEqual(history[1].new_assignee_id, self.candidate_b.pk)
        self.assertEqual(history[1].source, WorkflowStepAssignmentHistory.Source.MANUAL)
        self.assertEqual(history[1].reason, "تغییر مسئول")

    def test_assign_execution_rejects_invalid_assignee_without_writing_history(self):
        execution = self.make_execution()
        with self.assertRaises(ValidationError):
            WorkflowStepAssignmentService.assign_execution(
                execution=execution,
                assignee=self.starter,
            )
        self.assertFalse(execution.assignment_history.exists())
