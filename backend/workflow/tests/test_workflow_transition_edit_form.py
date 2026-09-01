"""
Regression tests for WorkflowTransition edit form behavior.

Verifies that when editing an existing WorkflowTransition, the from_step
and to_step fields correctly show the saved values.

Root cause of previous bug: The workflow-admin.js populateField() function
cleared and rebuilt the select fields via AJAX on page load, but never
preserved the currently selected value. Django rendered the correct initial
HTML, but JavaScript replaced innerHTML without marking the saved option
as selected.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory

from workflow.admin import WorkflowTransitionAdminForm
from workflow.models import (
    Workflow,
    WorkflowStep,
    WorkflowTransition,
)

User = get_user_model()


class WorkflowTransitionEditFormTest(TestCase):
    """Verify the admin form correctly handles existing transitions."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testadmin",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="Edit Test Workflow",
            code="EDIT_TEST",
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
        self.step_c = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step C",
            order=3,
        )

        # Normal transition: A → B
        self.normal_transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
        )
        # Finish transition: C → NULL
        self.finish_transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_c,
            to_step=None,
            name="Finish",
        )

    def test_edit_normal_transition_from_step_in_queryset(self):
        """When editing a normal transition, from_step must appear in the
        form's queryset so Django renders it as selected."""
        form = WorkflowTransitionAdminForm(
            instance=self.normal_transition,
        )
        # The queryset must contain the saved step
        from_step_qs = form.fields["from_step"].queryset
        self.assertIn(self.step_a, from_step_qs)

    def test_edit_normal_transition_to_step_in_queryset(self):
        """When editing a normal transition, to_step must appear in the
        form's queryset so Django renders it as selected."""
        form = WorkflowTransitionAdminForm(
            instance=self.normal_transition,
        )
        to_step_qs = form.fields["to_step"].queryset
        self.assertIn(self.step_b, to_step_qs)

    def test_edit_normal_transition_initial_values(self):
        """The form's initial from_step and to_step match the saved values."""
        form = WorkflowTransitionAdminForm(
            instance=self.normal_transition,
        )
        self.assertEqual(form.initial.get("from_step"), self.step_a.pk)
        self.assertEqual(form.initial.get("to_step"), self.step_b.pk)

    def test_edit_finish_transition_to_step_queryset_empty(self):
        """For a Finish transition (to_step=None), the to_step queryset
        must be populated so the blank/empty option renders correctly."""
        form = WorkflowTransitionAdminForm(
            instance=self.finish_transition,
        )
        # to_step queryset should contain steps from the workflow
        to_step_qs = form.fields["to_step"].queryset
        self.assertIn(self.step_c, to_step_qs)
        # But the initial value should be None (no step selected)
        self.assertIsNone(form.initial.get("to_step"))

    def test_edit_finish_transition_from_step_in_queryset(self):
        """The from_step of a Finish transition must be in the queryset."""
        form = WorkflowTransitionAdminForm(
            instance=self.finish_transition,
        )
        from_step_qs = form.fields["from_step"].queryset
        self.assertIn(self.step_c, from_step_qs)

    def test_form_workflow_queryset_filtering(self):
        """Both from_step and to_step querysets should only contain
        active steps from the correct workflow."""
        form = WorkflowTransitionAdminForm(
            instance=self.normal_transition,
        )
        for step in form.fields["from_step"].queryset:
            self.assertEqual(step.workflow, self.workflow)
            self.assertTrue(step.is_active)
        for step in form.fields["to_step"].queryset:
            self.assertEqual(step.workflow, self.workflow)
            self.assertTrue(step.is_active)

    def test_inactive_step_not_in_queryset(self):
        """An inactive step should not appear in the form queryset,
        even if it was the saved from_step or to_step."""
        self.step_b.is_active = False
        self.step_b.save(update_fields=["is_active"])

        form = WorkflowTransitionAdminForm(
            instance=self.normal_transition,
        )
        # step_b is inactive so it should NOT be in the queryset
        self.assertNotIn(
            self.step_b,
            form.fields["to_step"].queryset,
        )

    def test_post_data_overrides_workflow(self):
        """When POST data contains a different workflow_id, the form
        should use that for queryset filtering."""
        other_workflow = Workflow.objects.create(
            name="Other WF", code="OTHER_WF", is_active=True
        )
        other_step = WorkflowStep.objects.create(
            workflow=other_workflow,
            name="Other Step",
            order=1,
        )
        form = WorkflowTransitionAdminForm(
            data={"workflow": other_workflow.pk},
            instance=self.normal_transition,
        )
        # Should show steps from the POST workflow, not instance workflow
        self.assertIn(
            other_step,
            form.fields["from_step"].queryset,
        )
        # Should NOT contain instance workflow's steps
        self.assertNotIn(
            self.step_a,
            form.fields["from_step"].queryset,
        )
