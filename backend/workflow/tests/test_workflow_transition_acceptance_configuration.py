from django.test import TestCase

from workflow.admin import WorkflowTransitionAdminForm
from workflow.models import Workflow, WorkflowStep, WorkflowTransition


class WorkflowTransitionAcceptanceConfigurationTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Acceptance Configuration Test",
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

    def test_acceptance_is_disabled_by_default(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
        )

        self.assertFalse(transition.requires_acceptance)

    def test_acceptance_can_be_enabled_per_transition(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
            requires_acceptance=True,
        )

        self.assertTrue(transition.requires_acceptance)

    def test_acceptance_transition_can_define_reject_target(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_b,
            to_step=self.step_c,
            name="B to C",
            requires_acceptance=True,
            reject_to_step=self.step_a,
        )

        self.assertEqual(transition.reject_to_step, self.step_a)

    def test_admin_form_reject_target_requires_acceptance(self):
        form = WorkflowTransitionAdminForm(
            data={
                "workflow": self.workflow.pk,
                "from_step": self.step_b.pk,
                "to_step": self.step_c.pk,
                "name": "B to C",
                "is_active": True,
                "requires_acceptance": False,
                "reject_to_step": self.step_a.pk,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("مرحله بازگشت پس از رد", form.non_field_errors()[0])

    def test_admin_form_accepts_dynamic_reject_target(self):
        form = WorkflowTransitionAdminForm(
            data={
                "workflow": self.workflow.pk,
                "from_step": self.step_b.pk,
                "to_step": self.step_c.pk,
                "name": "B to C",
                "is_active": True,
                "requires_acceptance": True,
                "reject_to_step": self.step_a.pk,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["reject_to_step"],
            self.step_a,
        )
