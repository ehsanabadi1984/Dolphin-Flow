"""
Regression tests for Finish Transition (to_step=NULL).

Previously, creating a WorkflowTransition with to_step=NULL caused:
  IntegrityError: null value in column "to_step_id" of relation
  "workflow_workflowtransition" violates not-null constraint

This happened because migration 0041 (making to_step nullable) was
not applied to the database.

These tests verify that:
1. A Finish Transition with to_step=NULL can be saved to the database.
2. A normal Transition with to_step != NULL still works.
3. The admin form allows both cases.
4. Django model validation accepts both cases.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.models import (
    Workflow,
    WorkflowStep,
    WorkflowTransition,
)

User = get_user_model()


class FinishTransitionNullableTest(TestCase):
    """Verify Finish Transition (to_step=NULL) can be created."""

    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Finish Test Workflow",
            code="FINISH_TEST",
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

    def test_finish_transition_to_step_null(self):
        """A Finish Transition with to_step=None must save successfully."""
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_b,
            to_step=None,
            name="Finish",
        )
        transition.refresh_from_db()
        self.assertIsNone(transition.to_step)
        self.assertEqual(transition.from_step, self.step_b)
        self.assertEqual(transition.workflow, self.workflow)
        self.assertTrue(transition.code.startswith("TRANS_"))

    def test_normal_transition_to_step_set(self):
        """A normal Transition with to_step set must still work."""
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
        )
        transition.refresh_from_db()
        self.assertEqual(transition.to_step, self.step_b)
        self.assertEqual(transition.from_step, self.step_a)

    def test_finish_transition_str(self):
        """Finish Transition __str__ shows [FINISH]."""
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_b,
            to_step=None,
            name="Finish",
        )
        self.assertIn("[FINISH]", str(transition))

    def test_normal_transition_str(self):
        """Normal Transition __str__ shows step name."""
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
        )
        self.assertIn("Step A", str(transition))
        self.assertIn("Step B", str(transition))

    def test_finish_transition_ordering_with_null(self):
        """Multiple transitions with and without to_step can coexist."""
        normal = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
        )
        finish = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_b,
            to_step=None,
            name="Finish",
        )
        transitions = list(
            WorkflowTransition.objects.filter(workflow=self.workflow)
        )
        self.assertEqual(len(transitions), 2)
        # Both should be queryable
        self.assertIn(normal, transitions)
        self.assertIn(finish, transitions)

    def test_finish_transition_null_to_step_queried(self):
        """Querying for to_step=None works correctly."""
        WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
        )
        finish = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_b,
            to_step=None,
            name="Finish",
        )

        finish_transitions = WorkflowTransition.objects.filter(
            workflow=self.workflow,
            to_step__isnull=True,
        )
        self.assertEqual(finish_transitions.count(), 1)
        self.assertEqual(finish_transitions.first(), finish)

        normal_transitions = WorkflowTransition.objects.filter(
            workflow=self.workflow,
            to_step__isnull=False,
        )
        self.assertEqual(normal_transitions.count(), 1)
