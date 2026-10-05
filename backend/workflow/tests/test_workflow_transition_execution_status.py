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
        self.accepted_by = get_user_model().objects.create_user(
            username="transition-accepted-by",
        )
        self.rejected_by = get_user_model().objects.create_user(
            username="transition-rejected-by",
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

    def test_acceptance_actors_are_stored_independently(self):
        execution = self._create_execution(
            WorkflowTransitionExecution.Status.ACCEPTED,
        )
        execution.accepted_by = self.accepted_by
        execution.save(update_fields=["accepted_by"])

        execution.rejected_by = None
        execution.save(update_fields=["rejected_by"])

        execution.refresh_from_db()

        self.assertEqual(execution.accepted_by_id, self.accepted_by.pk)
        self.assertIsNone(execution.rejected_by_id)

    def test_rejection_actor_is_stored_independently(self):
        execution = self._create_execution(
            WorkflowTransitionExecution.Status.REJECTED,
        )
        execution.rejected_by = self.rejected_by
        execution.save(update_fields=["rejected_by"])

        execution.accepted_by = None
        execution.save(update_fields=["accepted_by"])

        execution.refresh_from_db()

        self.assertEqual(execution.rejected_by_id, self.rejected_by.pk)
        self.assertIsNone(execution.accepted_by_id)
