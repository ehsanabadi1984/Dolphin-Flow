from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class WorkflowInstanceEventMigrationTests(TransactionTestCase):
    migrate_from = ("workflow", "0093_workflowstepassignmenthistory_rejection_source")
    migrate_to = ("workflow", "0095_workflowtransitionexecution_superseded")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        user = get_user_model().objects.create_user(
            username="workflow_event_migration",
            password="test-password",
            first_name="Migration",
            last_name="Actor",
        )
        Workflow = old_apps.get_model("workflow", "Workflow")
        WorkflowStep = old_apps.get_model("workflow", "WorkflowStep")
        WorkflowInstance = old_apps.get_model("workflow", "WorkflowInstance")
        StepExecution = old_apps.get_model("workflow", "WorkflowStepExecution")
        AssignmentHistory = old_apps.get_model(
            "workflow", "WorkflowStepAssignmentHistory"
        )

        workflow = Workflow.objects.create(
            name="Event migration workflow",
            code="EVENT_MIGRATION_TEST",
            is_active=True,
        )
        step = WorkflowStep.objects.create(
            workflow=workflow,
            name="Event migration step",
            code="EVENT_MIGRATION_STEP",
            order=1,
            is_active=True,
        )
        instance = WorkflowInstance.objects.create(
            workflow=workflow,
            current_step=step,
            started_by=user,
            status="ACTIVE",
        )

        self.override_data_execution = StepExecution.objects.create(
            instance=instance,
            workflow_step=step,
            performed_by=user,
            entered_by=user,
            assigned_to=user,
            completed_by=user,
            is_submitted=True,
            submitted_at=timezone.now(),
            notes="override stored in execution data",
            data={"override": {"reason": "legacy override"}},
        )
        self.override_history_execution = StepExecution.objects.create(
            instance=instance,
            workflow_step=step,
            performed_by=user,
            entered_by=user,
            assigned_to=user,
            is_submitted=False,
            data={},
        )
        self.regular_execution = StepExecution.objects.create(
            instance=instance,
            workflow_step=step,
            performed_by=user,
            entered_by=user,
            assigned_to=user,
            is_submitted=False,
            data={"history": [{"status": "entered"}]},
        )
        AssignmentHistory.objects.create(
            step_execution=self.override_history_execution,
            previous_assignee=user,
            new_assignee=user,
            changed_by=user,
            source="OVERRIDE",
            reason="legacy override history",
        )
        self.assignment_history = AssignmentHistory.objects.create(
            step_execution=self.regular_execution,
            previous_assignee=None,
            new_assignee=user,
            changed_by=user,
            source="POLICY",
            reason="legacy policy assignment",
        )
        self.user_id = user.pk
        self.instance_id = instance.pk

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = MigrationExecutor(connection).loader.project_state(
            [self.migrate_to]
        ).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_execution_history_is_backfilled_as_immutable_instance_events(self):
        InstanceEvent = self.apps.get_model("workflow", "WorkflowInstanceEvent")
        events = {
            event.execution_id: event
            for event in InstanceEvent.objects.filter(instance_id=self.instance_id)
        }

        self.assertEqual(len(events), 3)
        self.assertEqual(
            events[self.override_data_execution.pk].event_type,
            "OVERRIDE",
        )
        self.assertEqual(
            events[self.override_history_execution.pk].event_type,
            "OVERRIDE",
        )
        self.assertEqual(
            events[self.regular_execution.pk].event_type,
            "STEP_ENTERED",
        )

        event = events[self.override_data_execution.pk]
        self.assertEqual(event.actor_id, self.user_id)
        self.assertEqual(event.actor_label, "Migration Actor")
        self.assertEqual(event.assigned_to_id, self.user_id)
        self.assertEqual(event.assigned_to_label, "Migration Actor")
        self.assertEqual(
            event.occurred_at,
            self.override_data_execution.performed_at,
        )
        self.assertEqual(
            event.details["completed_by_id"],
            self.user_id,
        )
        self.assertEqual(
            event.details["actor_source"],
            "entered_by",
        )
        self.assertEqual(
            event.details["override"]["reason"],
            "legacy override",
        )

    def test_assignment_history_gets_instance_and_step_references(self):
        AssignmentHistory = self.apps.get_model(
            "workflow", "WorkflowStepAssignmentHistory"
        )
        history = AssignmentHistory.objects.get(
            pk=self.assignment_history.pk
        )

        self.assertEqual(history.instance_id, self.instance_id)
        self.assertEqual(
            history.workflow_step_id,
            self.regular_execution.workflow_step_id,
        )
        self.assertEqual(
            history.step_execution_id,
            self.regular_execution.pk,
        )

    def test_0095_adds_superseded_as_a_transition_status_choice(self):
        TransitionExecution = self.apps.get_model(
            "workflow", "WorkflowTransitionExecution"
        )
        choices = dict(
            TransitionExecution._meta.get_field("status").choices
        )

        self.assertIn("SUPERSEDED", choices)
        self.assertEqual(
            choices["SUPERSEDED"],
            "منسوخ‌شده بر اثر اصلاح مسیر",
        )
