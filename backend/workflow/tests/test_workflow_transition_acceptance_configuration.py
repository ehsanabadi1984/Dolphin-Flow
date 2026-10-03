from django.test import TestCase

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
