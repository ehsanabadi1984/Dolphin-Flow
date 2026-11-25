import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from workflow.models import (
    Notification,
    SMSDelivery,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
    WorkflowInstanceEvent,
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
            action=WorkflowPermission.Action.EXECUTE,
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
            assigned_to=self.operator,
            assigned_at=timezone.now(),
            is_submitted=True,
            submitted_at=timezone.now(),
        )
        self.current_execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_c,
            performed_by=self.operator,
            is_submitted=False,
        )

    def test_override_creates_new_unsubmitted_execution(self):
        self.current_execution.assigned_to = self.operator
        self.current_execution.assigned_at = timezone.now()
        self.current_execution.sla_started_at = timezone.now() - timedelta(hours=1)
        self.current_execution.sla_due_at = timezone.now() + timedelta(hours=1)
        self.current_execution.save(update_fields=[
            "assigned_to", "assigned_at", "sla_started_at", "sla_due_at",
        ])
        old_assignment = WorkflowStepAssignmentHistory.objects.create(
            step_execution=self.current_execution,
            instance=self.instance,
            workflow_step=self.step_c,
            new_assignee=self.operator,
            changed_by=self.operator,
            source=WorkflowStepAssignmentHistory.Source.POLICY,
            reason="تخصیص پیش از اصلاح مسیر",
        )

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح اشتباه مسیر",
        )

        self.instance.refresh_from_db()
        new_execution.refresh_from_db()

        self.assertFalse(
            WorkflowStepExecution.objects.filter(pk=self.current_execution.pk).exists()
        )
        preserved_event = WorkflowInstanceEvent.objects.get(
            instance=self.instance,
            execution_id=self.current_execution.pk,
        )
        self.assertEqual(preserved_event.workflow_step_id, self.step_c.pk)
        self.assertFalse(preserved_event.details["is_submitted"])
        self.assertEqual(preserved_event.assigned_to_id, self.operator.pk)
        self.assertEqual(
            preserved_event.details["sla_stop_reason"],
            "OVERRIDE",
        )
        self.assertIn("sla_stopped_at", preserved_event.details)
        self.assertIsNone(preserved_event.details["sla_completed_at"])
        old_assignment.refresh_from_db()
        self.assertIsNone(old_assignment.step_execution_id)
        self.assertEqual(old_assignment.instance_id, self.instance.pk)
        self.assertEqual(old_assignment.workflow_step_id, self.step_c.pk)

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
        self.assertEqual(
            new_execution.data["override"],
            {
                "version": 1,
                "from_step_id": self.step_c.pk,
                "from_step_name": "C",
                "to_step_id": self.step_b.pk,
                "to_step_name": "B",
                "reason": "اصلاح اشتباه مسیر",
            },
        )
        self.assertNotEqual(self.current_execution.pk, new_execution.pk)


    def test_override_supersedes_pending_transition_and_closes_its_action_notification(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Pending route",
            code="OVERRIDE_PENDING_ROUTE",
            from_step=self.step_c,
            to_step=self.step_b,
            requires_acceptance=True,
        )
        pending = WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=transition,
            performed_by=self.operator,
            status=WorkflowTransitionExecution.Status.PENDING,
        )
        notification = Notification.objects.create(
            recipient=self.operator,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
            title="Pending acceptance",
            message="Please decide",
            workflow_instance=self.instance,
            workflow_step=self.step_b,
            transition_execution=pending,
        )
        delivery = SMSDelivery.objects.create(
            notification=notification,
            status=SMSDelivery.Status.PENDING,
        )

        WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح مسیر در انتظار پذیرش",
        )

        pending.refresh_from_db()
        notification.refresh_from_db()
        self.assertEqual(
            pending.status,
            WorkflowTransitionExecution.Status.SUPERSEDED,
        )
        self.assertIsNotNone(pending.resolved_at)
        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, SMSDelivery.Status.SKIPPED)
        self.assertIn("منسوخ", delivery.last_error)

    def test_override_skips_pending_sms_for_action_notification_on_departed_step(self):
        notification = Notification.objects.create(
            recipient=self.operator,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
            title="اقدام مرحله جاری",
            message="لطفاً مرحله را انجام دهید.",
            workflow_instance=self.instance,
            workflow_step=self.step_c,
        )
        delivery = SMSDelivery.objects.create(
            notification=notification,
            status=SMSDelivery.Status.PENDING,
        )
        in_flight_notification = Notification.objects.create(
            recipient=self.operator,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
            title="پیامک در حال ارسال",
            message="ارسال آن قبلاً آغاز شده است.",
            workflow_instance=self.instance,
            workflow_step=self.step_c,
        )
        in_flight_delivery = SMSDelivery.objects.create(
            notification=in_flight_notification,
            status=SMSDelivery.Status.SENDING,
        )

        WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح مسیر مرحله",
        )

        notification.refresh_from_db()
        delivery.refresh_from_db()
        in_flight_delivery.refresh_from_db()
        self.assertTrue(notification.is_read)
        self.assertEqual(delivery.status, SMSDelivery.Status.SKIPPED)
        self.assertIn("منسوخ", delivery.last_error)
        self.assertEqual(in_flight_delivery.status, SMSDelivery.Status.SENDING)

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

    def test_previous_completer_policy_reuses_valid_historical_assignee(self):
        self.step_b.assignment_policy = WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS
        self.step_b.save(update_fields=["assignment_policy"])

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="حفظ مسئول تاریخی با سیاست انتخابی",
        )

        self.assertEqual(new_execution.assigned_to, self.operator)

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
        policy_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Starter policy",
            order=8,
            assignment_policy=WorkflowStep.AssignmentPolicy.INSTANCE_STARTER,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=policy_step,
            user=self.operator,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=policy_step,
            performed_by=self.admin,
            reason="تخصیص به شروع‌کننده",
        )
        self.assertEqual(new_execution.assigned_to, self.operator)

    def test_override_resolves_step_completer_policy(self):
        source_execution = self.instance.step_executions.get(workflow_step=self.step_a)
        source_execution.completed_by = self.operator
        source_execution.is_submitted = True
        source_execution.submitted_at = timezone.now()
        source_execution.save(
            update_fields=["completed_by", "is_submitted", "submitted_at"]
        )
        policy_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step completer policy",
            order=9,
            assignment_policy=WorkflowStep.AssignmentPolicy.STEP_COMPLETER,
            assignment_source_step=self.step_a,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=policy_step,
            user=self.operator,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=policy_step,
            performed_by=self.admin,
            reason="تخصیص به تکمیل‌کننده مرجع",
        )
        self.assertEqual(new_execution.assigned_to, self.operator)

    def test_override_resolves_auto_single_policy(self):
        policy_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Auto single policy",
            order=10,
            assignment_policy=WorkflowStep.AssignmentPolicy.AUTO_SINGLE,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=policy_step,
            user=self.operator,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=policy_step,
            performed_by=self.admin,
            reason="تخصیص خودکار یگانه",
        )
        self.assertEqual(new_execution.assigned_to, self.operator)

    def test_override_rejects_changing_a_valid_historical_assignee(self):
        other_user = User.objects.create_user(
            username="override_other_candidate",
            password="test-password",
            is_active=True,
        )
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.admin,
                reason="تغییر مسئول تاریخی",
                selected_assignee=other_user,
            )



    def test_override_reuses_latest_historical_assignee_instead_of_step_default(self):
        self.step_b.assigned_to = None
        self.step_b.save(update_fields=["assigned_to"])

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="بازگشت با مسئول تاریخی",
        )

        self.assertEqual(new_execution.assigned_to_id, self.operator.pk)

    def test_override_requires_selection_when_historical_assignee_is_no_longer_eligible(self):
        replacement = User.objects.create_user(
            username="override_replacement",
            password="test-password",
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=replacement,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_b,
            user=replacement,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowMembership.objects.filter(
            workflow=self.workflow,
            user=self.operator,
        ).update(is_active=False)

        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.admin,
                reason="مسئول قبلی دیگر مجاز نیست",
            )

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="انتخاب مسئول جایگزین",
            selected_assignee=replacement,
        )
        self.assertEqual(new_execution.assigned_to_id, replacement.pk)

    def test_override_requires_selection_for_legacy_entry_without_assignee(self):
        legacy_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Legacy without assignee",
            order=5,
            is_active=True,
            assignment_policy=WorkflowStep.AssignmentPolicy.FIXED,
            assigned_to=self.operator,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=legacy_step,
            user=self.operator,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=legacy_step,
            performed_by=self.operator,
            is_submitted=True,
        )

        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=legacy_step,
                performed_by=self.admin,
                reason="ورود تاریخی بدون مسئول",
            )

        selected_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=legacy_step,
            performed_by=self.admin,
            reason="تعیین صریح مسئول",
            selected_assignee=self.operator,
        )
        self.assertEqual(selected_execution.assigned_to_id, self.operator.pk)

    def test_first_override_entry_uses_unambiguous_assignment_policy(self):
        first_entry_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="First entry",
            order=6,
            is_active=True,
            assignment_policy=WorkflowStep.AssignmentPolicy.FIXED,
            assigned_to=self.operator,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=first_entry_step,
            user=self.operator,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=first_entry_step,
            performed_by=self.admin,
            reason="ورود نخست با سیاست ثابت",
        )
        self.assertEqual(new_execution.assigned_to_id, self.operator.pk)

    def test_first_override_entry_requires_selection_for_ambiguous_auto_single(self):
        second_operator = User.objects.create_user(
            username="override_second_operator",
            password="test-password",
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=second_operator,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        ambiguous_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Ambiguous auto",
            order=7,
            is_active=True,
            assignment_policy=WorkflowStep.AssignmentPolicy.AUTO_SINGLE,
        )
        for user in (self.operator, second_operator):
            WorkflowPermission.objects.create(
                workflow=self.workflow,
                step=ambiguous_step,
                user=user,
                action=WorkflowPermission.Action.EXECUTE,
                effect=WorkflowPermission.Effect.ALLOW,
            )

        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=ambiguous_step,
                performed_by=self.admin,
                reason="سیاست خودکار مبهم",
            )

        selected_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=ambiguous_step,
            performed_by=self.admin,
            reason="انتخاب مدیر برای سیاست مبهم",
            selected_assignee=second_operator,
        )
        self.assertEqual(selected_execution.assigned_to_id, second_operator.pk)


    def test_returning_to_deleted_execution_reuses_independent_entry_event_assignee(self):
        first_entry = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="ورود نخست به مرحله مقصد",
        )
        first_entry_id = first_entry.pk

        intermediate_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Intermediate",
            order=11,
            assignment_policy=WorkflowStep.AssignmentPolicy.FIXED,
            assigned_to=self.operator,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=intermediate_step,
            user=self.operator,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=intermediate_step,
            performed_by=self.admin,
            reason="خروج از مرحله مقصد",
        )

        self.assertFalse(
            WorkflowStepExecution.objects.filter(pk=first_entry_id).exists()
        )
        preserved_event = WorkflowInstanceEvent.objects.get(
            instance=self.instance,
            execution_id=first_entry_id,
        )
        self.assertEqual(preserved_event.assigned_to_id, self.operator.pk)

        returned_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="بازگشت به مرحله قبلی",
        )
        self.assertEqual(returned_execution.assigned_to_id, self.operator.pk)


    def test_override_uses_latest_assignment_history_after_entry_event(self):
        replacement = User.objects.create_user(
            username="override_reassigned_operator",
            password="test-password",
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=replacement,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_b,
            user=replacement,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        event_time = timezone.now() - timedelta(minutes=5)
        WorkflowInstanceEvent.objects.create(
            instance=self.instance,
            workflow_step=self.step_b,
            event_type=WorkflowInstanceEvent.EventType.STEP_ENTERED,
            actor=self.operator,
            actor_label=self.operator.username,
            assigned_to=self.operator,
            assigned_to_label=self.operator.username,
            occurred_at=event_time,
            details={},
        )
        WorkflowStepAssignmentHistory.objects.create(
            instance=self.instance,
            workflow_step=self.step_b,
            previous_assignee=self.operator,
            new_assignee=replacement,
            changed_by=self.admin,
            source=WorkflowStepAssignmentHistory.Source.MANUAL,
            reason="تغییر مسئول پس از ورود",
        )

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="بازگشت با آخرین تخصیص",
        )
        self.assertEqual(new_execution.assigned_to_id, replacement.pk)
