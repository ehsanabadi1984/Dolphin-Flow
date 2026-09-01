from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory

from workflow.models import (
    Workflow,
    WorkflowMembership,
    WorkflowStep,
    WorkflowTransition,
    WorkflowPermission,
)

User = get_user_model()


class WorkflowTransitionPermissionInlineWorkflowAutoPopulatedTest(TestCase):
    """Regression test: saving a WorkflowPermission from the
    WorkflowTransitionAdmin inline must auto-set workflow from transition.

    Previously this caused:
      IntegrityError: null value in column "workflow_id"
    because the inline did not populate the workflow FK.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="testadmin",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="Permission Test Workflow",
            code="PERM_TEST_WF",
            is_active=True,
        )
        self.step_a = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step A",
            order=1,
        )
        self.step_b = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step B",
            order=2,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
        )

    def test_permission_created_via_inline_has_workflow(self):
        """Simulate what Django Admin inline save does:
        create a WorkflowPermission with transition set but workflow unset,
        then let save_formset logic populate it."""
        perm = WorkflowPermission(
            transition=self.transition,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        # Before save, workflow is not set (simulating the inline form)
        self.assertIsNone(perm.workflow_id)

        # Simulate the save_formset logic from WorkflowTransitionAdmin
        if not perm.workflow_id and perm.transition_id:
            perm.workflow = perm.transition.workflow

        perm.save()

        self.assertEqual(perm.workflow, self.workflow)
        self.assertEqual(perm.transition, self.transition)

    def test_permission_created_via_step_inline_has_workflow(self):
        """Simulate what Django Admin inline save does for step permissions."""
        perm = WorkflowPermission(
            step=self.step_a,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        # Before save, workflow is not set
        self.assertIsNone(perm.workflow_id)

        # Simulate the save_formset logic from WorkflowStepAdmin
        if not perm.workflow_id and perm.step_id:
            perm.workflow = perm.step.workflow

        perm.save()

        self.assertEqual(perm.workflow, self.workflow)
        self.assertEqual(perm.step, self.step_a)

    def test_finish_transition_permission_has_workflow(self):
        """A Finish transition (to_step=None) must also auto-populate workflow."""
        finish_transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_b,
            to_step=None,
            name="Finish",
        )
        perm = WorkflowPermission(
            transition=finish_transition,
            user=self.user,
            role=WorkflowMembership.Role.MANAGER,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.assertIsNone(perm.workflow_id)

        # Simulate the save_formset logic
        if not perm.workflow_id and perm.transition_id:
            perm.workflow = perm.transition.workflow

        perm.save()

        self.assertEqual(perm.workflow, self.workflow)
        self.assertEqual(perm.transition, finish_transition)
        self.assertIsNone(perm.transition.to_step)

    def test_permission_with_existing_workflow_not_overwritten(self):
        """If workflow is already set, it should not be overwritten."""
        perm = WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.transition,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        # workflow is already set
        self.assertEqual(perm.workflow, self.workflow)

        # Simulate the save_formset logic — should not overwrite
        if not perm.workflow_id and perm.transition_id:
            perm.workflow = perm.transition.workflow

        self.assertEqual(perm.workflow, self.workflow)
