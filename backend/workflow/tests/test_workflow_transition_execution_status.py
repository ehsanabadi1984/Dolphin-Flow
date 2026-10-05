from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.models import (
    Workflow,
    WorkflowStep,
    WorkflowTransition,
    WorkflowTransitionExecution,
    WorkflowInstance,
)


class WorkflowTransitionExecutionStatusTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="transition-status-user",
        )
        self.workflow = Workflow.objects.create(
            name="Transition Execution Status Test",
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
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_a,
            started_by=self.user,
        )

    def _create_execution(self, status):
        return WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=self.transition,
            performed_by=self.user,
            status=status,
        )

    def test_default_status_is_accepted_for_existing_normal_transitions(self):
        execution = WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=self.transition,
            performed_by=self.user,
        )

        self.assertEqual(
            execution.status,
            WorkflowTransitionExecution.Status.ACCEPTED,
        )

    def test_pending_accepted_and_rejected_are_distinct_states(self):
        statuses = {
            self._create_execution(
                WorkflowTransitionExecution.Status.PENDING,
            ).status,
            self._create_execution(
                WorkflowTransitionExecution.Status.ACCEPTED,
            ).status,
            self._create_execution(
                WorkflowTransitionExecution.Status.REJECTED,
            ).status,
        }

        self.assertEqual(
            statuses,
            {
                WorkflowTransitionExecution.Status.PENDING,
                WorkflowTransitionExecution.Status.ACCEPTED,
                WorkflowTransitionExecution.Status.REJECTED,
            },
        )

    def test_status_choices_are_explicit(self):
        self.assertEqual(
            set(WorkflowTransitionExecution.Status.values),
            {"PENDING", "ACCEPTED", "REJECTED"},
        )
