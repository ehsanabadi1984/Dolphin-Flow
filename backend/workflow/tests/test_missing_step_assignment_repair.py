import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

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


class RepairMissingStepAssignmentsCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="repair_fixed_assignee",
            password="test-password",
            is_active=True,
        )
        self.workflow = Workflow.objects.create(
            name="Repair command test workflow",
            code="REPAIR_COMMAND_TEST",
            is_active=True,
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Fixed step",
            code="REPAIR_FIXED_STEP",
            order=1,
            is_active=True,
            assignment_policy=WorkflowStep.AssignmentPolicy.FIXED,
            assigned_to=self.user,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
            status=WorkflowInstance.Status.ACTIVE,
        )
        self.execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
            assigned_to=None,
            is_submitted=False,
        )

    def _write_plan(self):
        handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        handle.close()
        Path(handle.name).unlink()
        call_command(
            "repair_missing_step_assignments",
            plan_out=handle.name,
            stdout=open(Path(handle.name + ".log"), "w", encoding="utf-8"),
        )
        return Path(handle.name)

    def test_dry_run_does_not_change_execution_or_create_history(self):
        output = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        output.close()
        Path(output.name).unlink()
        try:
            call_command(
                "repair_missing_step_assignments",
                plan_out=output.name,
            )
            self.execution.refresh_from_db()
            self.assertIsNone(self.execution.assigned_to_id)
            self.assertEqual(
                WorkflowStepAssignmentHistory.objects.filter(
                    step_execution=self.execution
                ).count(),
                0,
            )
            plan = json.loads(Path(output.name).read_text(encoding="utf-8"))
            self.assertEqual(len(plan["items"]), 1)
            self.assertEqual(plan["items"][0]["status"], "ELIGIBLE")
        finally:
            Path(output.name).unlink(missing_ok=True)

    def test_apply_uses_assignment_service_and_writes_audit_history(self):
        output = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        output.close()
        Path(output.name).unlink()
        try:
            call_command(
                "repair_missing_step_assignments",
                plan_out=output.name,
            )
            call_command(
                "repair_missing_step_assignments",
                apply=True,
                plan_file=output.name,
            )
            self.execution.refresh_from_db()
            self.assertEqual(self.execution.assigned_to_id, self.user.pk)
            history = WorkflowStepAssignmentHistory.objects.get(
                step_execution=self.execution
            )
            self.assertEqual(history.new_assignee_id, self.user.pk)
            self.assertIsNone(history.previous_assignee_id)
            self.assertIsNone(history.changed_by_id)
            self.assertEqual(
                history.source,
                WorkflowStepAssignmentHistory.Source.POLICY,
            )
            self.assertIn("repair_missing_step_assignments", history.reason)
        finally:
            Path(output.name).unlink(missing_ok=True)

    def test_apply_skips_candidate_if_instance_moved_after_dry_run(self):
        other_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Next step",
            code="REPAIR_NEXT_STEP",
            order=2,
            is_active=True,
        )
        output = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        output.close()
        Path(output.name).unlink()
        try:
            call_command(
                "repair_missing_step_assignments",
                plan_out=output.name,
            )
            WorkflowInstance.objects.filter(pk=self.instance.pk).update(
                current_step=other_step
            )
            call_command(
                "repair_missing_step_assignments",
                apply=True,
                plan_file=output.name,
            )
            self.execution.refresh_from_db()
            self.assertIsNone(self.execution.assigned_to_id)
            self.assertFalse(
                WorkflowStepAssignmentHistory.objects.filter(
                    step_execution=self.execution
                ).exists()
            )
        finally:
            Path(output.name).unlink(missing_ok=True)

    def test_duplicate_open_executions_are_reported_and_never_repaired(self):
        duplicate = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
            assigned_to=None,
            is_submitted=False,
        )
        output = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        output.close()
        Path(output.name).unlink()
        try:
            call_command(
                "repair_missing_step_assignments",
                plan_out=output.name,
            )
            plan = json.loads(Path(output.name).read_text(encoding="utf-8"))
            self.assertEqual(len(plan["items"]), 2)
            self.assertTrue(all(item["status"] == "SKIP" for item in plan["items"]))
            call_command(
                "repair_missing_step_assignments",
                apply=True,
                plan_file=output.name,
            )
            self.execution.refresh_from_db()
            duplicate.refresh_from_db()
            self.assertIsNone(self.execution.assigned_to_id)
            self.assertIsNone(duplicate.assigned_to_id)
            self.assertEqual(WorkflowStepAssignmentHistory.objects.count(), 0)
        finally:
            Path(output.name).unlink(missing_ok=True)

    def test_apply_rejects_modified_plan_file(self):
        output = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        output.close()
        Path(output.name).unlink()
        try:
            call_command(
                "repair_missing_step_assignments",
                plan_out=output.name,
            )
            plan = json.loads(Path(output.name).read_text(encoding="utf-8"))
            plan["items"][0]["assignee_id"] = self.user.pk + 1000
            Path(output.name).write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(Exception):
                call_command(
                    "repair_missing_step_assignments",
                    apply=True,
                    plan_file=output.name,
                )
            self.execution.refresh_from_db()
            self.assertIsNone(self.execution.assigned_to_id)
        finally:
            Path(output.name).unlink(missing_ok=True)
