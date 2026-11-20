import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from workflow.models import (
    Notification,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)
from workflow.override_services import WorkflowOverrideService
from workflow.timeline_services import build_instance_timeline_events


User = get_user_model()


class WorkflowOverrideServiceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="override_admin",
            password="test-password",
            is_active=True,
            is_staff=True,
        )
        self.operator = User.objects.create_user(
            username="override_operator",
            password="test-password",
            is_active=True,
            is_staff=False,
        )

        self.workflow = Workflow.objects.create(
            name="Override Test Workflow",
            code="OVERRIDE_TEST",
            is_active=True,
        )
        self.other_workflow = Workflow.objects.create(
            name="Other Workflow",
            code="OVERRIDE_OTHER",
            is_active=True,
        )

        self.step_a = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="A",
            order=1,
            is_active=True,
        )
        self.step_b = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="B",
            order=2,
            is_active=True,
        )
        self.step_c = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="C",
            order=3,
            is_active=True,
        )
        self.inactive_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Inactive",
            order=4,
            is_active=False,
        )
        self.other_step = WorkflowStep.objects.create(
            workflow=self.other_workflow,
            name="Other",
            order=1,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.operator,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        self.step_b.assigned_to = self.operator
        self.step_b.save(update_fields=["assigned_to"])
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_b,
            user=self.operator,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="EXECUTE",
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_c,
            started_by=self.operator,
            status=WorkflowInstance.Status.ACTIVE,
        )
        WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_a,
            performed_by=self.operator,
            is_submitted=True,
        )
        WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_b,
            performed_by=self.operator,
            is_submitted=True,
        )
        self.current_execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_c,
            performed_by=self.operator,
            is_submitted=False,
        )

    def test_override_creates_new_unsubmitted_execution(self):
        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح اشتباه مسیر",
        )

        self.instance.refresh_from_db()
        self.current_execution.refresh_from_db()
        new_execution.refresh_from_db()

        self.assertEqual(self.instance.current_step_id, self.step_b.id)
        self.assertEqual(self.instance.status, WorkflowInstance.Status.ACTIVE)
        self.assertFalse(new_execution.is_submitted)
        self.assertEqual(new_execution.workflow_step_id, self.step_b.id)
        self.assertTrue(
            new_execution.notes.startswith(
                WorkflowOverrideService.OVERRIDE_NOTE_PREFIX
            )
        )
        self.assertIn("C → B", new_execution.notes)
        self.assertIn("اصلاح اشتباه مسیر", new_execution.notes)
        self.assertTrue(self.current_execution.pk != new_execution.pk)
        self.assertFalse(self.current_execution.is_submitted)

    def test_override_audit_note_survives_step_submission(self):
        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح مسیر قبلی",
        )

        original_note = new_execution.notes
        new_execution.is_submitted = True
        new_execution.submitted_at = timezone.now()
        new_execution.data = {"history": {"fields": [], "repeatable_groups": []}}
        new_execution.save(
            update_fields=["is_submitted", "submitted_at", "data"]
        )

        new_execution.refresh_from_db()
        self.assertEqual(new_execution.notes, original_note)

    def test_completed_instance_is_reopened(self):
        self.instance.current_step = None
        self.instance.status = WorkflowInstance.Status.COMPLETED
        self.instance.completed_at = timezone.now()
        self.instance.save(update_fields=["current_step", "status", "completed_at"])

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="بازگشت برای اصلاح",
        )

        self.instance.refresh_from_db()

        self.assertEqual(self.instance.status, WorkflowInstance.Status.ACTIVE)
        self.assertIsNone(self.instance.completed_at)
        self.assertEqual(self.instance.current_step_id, self.step_b.id)
        self.assertFalse(new_execution.is_submitted)

    def test_timeline_preserves_completion_event_after_override_reopens_instance(self):
        finish_transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="تکمیل",
            code="OVERRIDE_FINISH",
            from_step=self.step_c,
            to_step=None,
        )
        finished_at = timezone.now()
        WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=finish_transition,
            performed_by=self.operator,
            status=WorkflowTransitionExecution.Status.ACCEPTED,
        )
        finish_execution = WorkflowTransitionExecution.objects.get(
            instance=self.instance,
            transition=finish_transition,
        )
        finished_at = finish_execution.performed_at
        self.instance.current_step = None
        self.instance.status = WorkflowInstance.Status.COMPLETED
        self.instance.completed_at = finished_at
        self.instance.save(
            update_fields=["current_step", "status", "completed_at"]
        )

        WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="بازگشت برای اصلاح پس از تکمیل",
        )

        self.instance.refresh_from_db()
        events = build_instance_timeline_events(self.instance)
        completion_events = [
            event for event in events if event["type"] == "instance_completed"
        ]

        self.assertEqual(self.instance.status, WorkflowInstance.Status.ACTIVE)
        self.assertIsNone(self.instance.completed_at)
        self.assertEqual(len(completion_events), 1)
        self.assertEqual(
            completion_events[0]["id"],
            f"instance-completed-transition-{finish_execution.pk}",
        )
        self.assertEqual(completion_events[0]["performed_at"], finished_at)
        self.assertEqual(completion_events[0]["user"], "override_operator")

    def test_rejects_non_admin(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.operator,
                reason="اصلاح مسیر",
            )

    def test_rejects_same_step(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_c,
                performed_by=self.admin,
                reason="اصلاح مسیر",
            )

    def test_rejects_inactive_target(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.inactive_step,
                performed_by=self.admin,
                reason="اصلاح مسیر",
            )

    def test_rejects_other_workflow(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.other_step,
                performed_by=self.admin,
                reason="اصلاح مسیر",
            )

    def test_rejects_cancelled_instance(self):
        self.instance.status = WorkflowInstance.Status.CANCELLED
        self.instance.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.admin,
                reason="اصلاح مسیر",
            )

    def test_rejects_short_reason(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.admin,
                reason="بد",
            )
    def test_override_assigns_execution_and_records_override_history(self):
        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح مسئولیت مرحله",
        )

        new_execution.refresh_from_db()
        history = WorkflowStepAssignmentHistory.objects.get(
            step_execution=new_execution
        )
        self.assertEqual(new_execution.entered_by, self.admin)
        self.assertEqual(new_execution.assigned_to, self.operator)
        self.assertIsNotNone(new_execution.assigned_at)
        self.assertEqual(history.new_assignee, self.operator)
        self.assertEqual(history.changed_by, self.admin)
        self.assertEqual(history.source, WorkflowStepAssignmentHistory.Source.OVERRIDE)
        self.assertEqual(history.reason, "اصلاح مسئولیت مرحله")

    def test_override_notification_goes_to_actual_execution_assignee(self):
        WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح مسیر و اعلان",
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.operator,
                workflow_instance=self.instance,
                workflow_step=self.step_b,
                notification_type=Notification.NotificationType.ACTION_REQUIRED,
            ).exists()
        )

    def test_previous_completer_selects_requires_admin_selection(self):
        self.step_b.assignment_policy = WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS
        self.step_b.save(update_fields=["assignment_policy"])

        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.admin,
                reason="اصلاح مسیر بدون مسئول",
            )

        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.step_b,
                entered_by=self.admin,
            ).exists()
        )

    def test_previous_completer_selects_accepts_selected_eligible_assignee(self):
        self.step_b.assignment_policy = WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS
        self.step_b.save(update_fields=["assignment_policy"])

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح مسیر با انتخاب مسئول",
            selected_assignee=self.operator,
        )

        self.assertEqual(new_execution.assigned_to, self.operator)
        self.assertEqual(
            new_execution.assignment_history.get().source,
            WorkflowStepAssignmentHistory.Source.OVERRIDE,
        )

    def test_previous_completer_selects_rejects_ineligible_assignee(self):
        ineligible = User.objects.create_user(
            username="override_ineligible",
            password="test-password",
            is_active=True,
        )
        self.step_b.assignment_policy = WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS
        self.step_b.save(update_fields=["assignment_policy"])

        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.admin,
                reason="انتخاب مسئول فاقد مجوز",
                selected_assignee=ineligible,
            )

        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.step_b,
                entered_by=self.admin,
            ).exists()
        )

    def test_override_resolves_instance_starter_policy(self):
        self.step_b.assignment_policy = WorkflowStep.AssignmentPolicy.INSTANCE_STARTER
        self.step_b.save(update_fields=["assignment_policy"])

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="تخصیص به شروع‌کننده",
        )
        self.assertEqual(new_execution.assigned_to, self.operator)

    def test_override_resolves_step_completer_policy(self):
        source_execution = self.instance.step_executions.get(workflow_step=self.step_a)
        source_execution.completed_by = self.operator
        source_execution.save(update_fields=["completed_by"])
        self.step_b.assignment_policy = WorkflowStep.AssignmentPolicy.STEP_COMPLETER
        self.step_b.assignment_source_step = self.step_a
        self.step_b.save(update_fields=["assignment_policy", "assignment_source_step"])

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="تخصیص به تکمیل‌کننده مرجع",
        )
        self.assertEqual(new_execution.assigned_to, self.operator)

    def test_override_resolves_auto_single_policy(self):
        self.step_b.assignment_policy = WorkflowStep.AssignmentPolicy.AUTO_SINGLE
        self.step_b.save(update_fields=["assignment_policy"])

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="تخصیص خودکار یگانه",
        )
        self.assertEqual(new_execution.assigned_to, self.operator)

    def test_override_rejects_manual_selection_for_other_policies(self):
        self.assertRaises(
            ValidationError,
            WorkflowOverrideService.override_instance_step,
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="انتخاب دستی غیرمجاز",
            selected_assignee=self.operator,
        )

