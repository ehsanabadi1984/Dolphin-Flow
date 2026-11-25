from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from workflow.form_file_models import SharedFileAsset
from workflow.models import (
    FileShareMessage,
    FileShareMessageEvent,
    Workflow,
    WorkflowInstance,
    WorkflowStep,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)
from workflow.timeline_services import build_instance_timeline_events
from workflow.instance_event_services import WorkflowInstanceEventService


User = get_user_model()


class WorkflowInstanceTimelineServiceTests(TestCase):
    def setUp(self):
        self.starter = User.objects.create_user(
            username="timeline-starter",
            first_name="Sara",
            last_name="Ahmadi",
            password="test-password",
        )
        self.assignee = User.objects.create_user(
            username="timeline-assignee",
            first_name="Ali",
            last_name="Rezaei",
            password="test-password",
        )
        self.reviewer = User.objects.create_user(
            username="timeline-reviewer",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="Timeline workflow",
            code="TIMELINE_TEST",
        )
        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="مرحله اول",
            code="TIMELINE_STEP_1",
            order=1,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="مرحله دوم",
            code="TIMELINE_STEP_2",
            order=2,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_one,
            started_by=self.starter,
        )

    def test_includes_instance_start_and_completion_events(self):
        completed_at = timezone.now()
        self.instance.completed_at = completed_at
        self.instance.save(update_fields=["completed_at"])

        events = build_instance_timeline_events(self.instance)

        self.assertEqual(
            [event["type"] for event in events],
            ["start", "instance_completed"],
        )
        self.assertEqual(events[0]["user"], "Sara Ahmadi")
        self.assertEqual(events[0]["title"], "شروع فرآیند")
        self.assertEqual(events[1]["performed_at"], completed_at)

    def test_step_event_exposes_execution_roles_submit_and_sla_timestamps(self):
        now = timezone.now()
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_one,
            performed_by=self.starter,
            entered_by=self.reviewer,
            assigned_to=self.assignee,
            assigned_at=now - timedelta(minutes=5),
            completed_by=self.assignee,
            is_submitted=True,
            submitted_at=now,
            sla_started_at=now - timedelta(hours=1),
            sla_due_at=now + timedelta(hours=1),
            sla_warning_at=now - timedelta(minutes=10),
            sla_warning_sent_at=now - timedelta(minutes=8),
            sla_completed_at=now,
            notes="یادداشت مرحله",
        )

        events = build_instance_timeline_events(self.instance)
        step_event = next(event for event in events if event["type"] == "step")

        self.assertEqual(step_event["execution_id"], execution.pk)
        self.assertEqual(step_event["user"], "timeline-reviewer")
        self.assertEqual(step_event["entered_by"], "timeline-reviewer")
        self.assertEqual(step_event["assigned_to"], "Ali Rezaei")
        self.assertEqual(step_event["completed_by"], "Ali Rezaei")
        self.assertEqual(step_event["assigned_at"], execution.assigned_at)
        self.assertEqual(step_event["submitted_at"], now)
        self.assertTrue(step_event["is_submitted"])
        self.assertEqual(step_event["sla_warning_sent_at"], execution.sla_warning_sent_at)
        self.assertTrue(step_event["sla_completed"])

    def test_entry_and_assignment_history_survive_deleting_unsubmitted_execution(self):
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_one,
            performed_by=self.starter,
            entered_by=self.starter,
            assigned_to=self.assignee,
        )
        assignment = WorkflowStepAssignmentHistory.objects.create(
            step_execution=execution,
            instance=self.instance,
            workflow_step=self.step_one,
            previous_assignee=None,
            new_assignee=self.assignee,
            changed_by=self.reviewer,
            source=WorkflowStepAssignmentHistory.Source.INITIAL,
            reason="تخصیص اولیه",
        )
        audit_event = WorkflowInstanceEventService.record_step_entry(
            execution=execution,
            actor=self.starter,
        )

        execution_id = execution.pk
        execution.delete()

        audit_event.refresh_from_db()
        assignment.refresh_from_db()
        self.assertIsNone(assignment.step_execution_id)
        self.assertEqual(audit_event.execution_id, execution_id)

        events = build_instance_timeline_events(self.instance)
        step_event = next(event for event in events if event["type"] == "step")
        assignment_event = next(
            event for event in events if event["type"] == "assignment"
        )
        self.assertEqual(step_event["execution_id"], execution_id)
        self.assertEqual(step_event["user"], "Sara Ahmadi")
        self.assertEqual(step_event["assigned_to"], "Ali Rezaei")
        self.assertFalse(step_event["is_submitted"])
        self.assertEqual(assignment_event["id"], f"assignment-{assignment.pk}")
        self.assertEqual(assignment_event["description"], "تخصیص اولیه")

    def test_assignment_history_is_a_separate_timeline_event(self):
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_one,
            performed_by=self.starter,
            assigned_to=self.assignee,
        )
        assignment = WorkflowStepAssignmentHistory.objects.create(
            step_execution=execution,
            instance=self.instance,
            workflow_step=execution.workflow_step,
            previous_assignee=None,
            new_assignee=self.assignee,
            changed_by=self.reviewer,
            source=WorkflowStepAssignmentHistory.Source.MANUAL,
            reason="تخصیص دستی",
        )

        events = build_instance_timeline_events(self.instance)
        assignment_event = next(
            event for event in events if event["type"] == "assignment"
        )

        self.assertEqual(assignment_event["id"], f"assignment-{assignment.pk}")
        self.assertEqual(assignment_event["user"], "timeline-reviewer")
        self.assertEqual(assignment_event["new_assignee"], "Ali Rezaei")
        self.assertEqual(assignment_event["assignment_source_code"], "MANUAL")
        self.assertEqual(assignment_event["description"], "تخصیص دستی")

    def test_transition_request_and_resolution_are_separate_events(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="ارسال برای بررسی",
            code="TIMELINE_TRANSITION",
            from_step=self.step_one,
            to_step=self.step_two,
            requires_acceptance=True,
        )
        resolved_at = timezone.now()
        transition_execution = WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=transition,
            performed_by=self.starter,
            status=WorkflowTransitionExecution.Status.ACCEPTED,
            accepted_by=self.reviewer,
            resolved_at=resolved_at,
            notes="تأیید شد",
        )

        events = build_instance_timeline_events(self.instance)
        request_event = next(
            event for event in events if event["type"] == "transition"
        )
        resolution_event = next(
            event for event in events if event["type"] == "transition_resolution"
        )

        self.assertEqual(
            request_event["id"], f"transition-{transition_execution.pk}"
        )
        self.assertEqual(request_event["from_step"], "مرحله اول")
        self.assertEqual(request_event["to_step"], "مرحله دوم")
        self.assertEqual(request_event["transition_status_code"], "ACCEPTED")
        self.assertEqual(
            resolution_event["id"],
            f"transition-resolution-{transition_execution.pk}",
        )
        self.assertEqual(resolution_event["performed_at"], resolved_at)
        self.assertEqual(resolution_event["user"], "timeline-reviewer")

    def test_file_share_event_is_included_with_sender_recipient_and_actor(self):
        asset = SharedFileAsset.objects.create(
            storage_name="timeline/test.pdf",
            original_name="test.pdf",
            file_size=100,
            content_type="application/pdf",
        )
        message = FileShareMessage.objects.create(
            asset=asset,
            sender=self.starter,
            recipient=self.assignee,
            workflow_instance=self.instance,
            workflow_step=self.step_one,
            interaction_type=FileShareMessage.InteractionType.REVIEW,
            subject="بررسی فایل",
        )
        share_event = FileShareMessageEvent.objects.create(
            message=message,
            event_type=FileShareMessageEvent.EventType.SENT,
            actor=self.starter,
            details={"source": "test"},
        )

        events = build_instance_timeline_events(self.instance)
        event = next(item for item in events if item["type"] == "file_share")

        self.assertEqual(event["id"], f"file-share-{share_event.pk}")
        self.assertEqual(event["sender"], "Sara Ahmadi")
        self.assertEqual(event["recipient"], "Ali Rezaei")
        self.assertEqual(event["user"], "Sara Ahmadi")
        self.assertEqual(event["interaction_type"], "درخواست بررسی یا تأیید فایل")
        self.assertEqual(event["details"], {"source": "test"})

    def test_events_are_chronological_and_exclude_other_instances(self):
        other_instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_one,
            started_by=self.assignee,
        )
        own_execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_one,
            performed_by=self.starter,
        )
        WorkflowStepExecution.objects.create(
            instance=other_instance,
            workflow_step=self.step_two,
            performed_by=self.assignee,
        )

        base_time = timezone.now()
        WorkflowInstance.objects.filter(pk=self.instance.pk).update(
            started_at=base_time - timedelta(hours=2)
        )
        WorkflowStepExecution.objects.filter(pk=own_execution.pk).update(
            performed_at=base_time - timedelta(hours=1)
        )
        self.instance.refresh_from_db()

        events = build_instance_timeline_events(self.instance)

        self.assertEqual([event["type"] for event in events], ["start", "step"])
        self.assertEqual(events[0]["performed_at"], base_time - timedelta(hours=2))
        self.assertEqual(events[1]["execution_id"], own_execution.pk)

    def test_override_event_uses_structured_metadata_and_assignment_history(self):
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_two,
            performed_by=self.reviewer,
            entered_by=self.reviewer,
            notes="متن یادداشت می‌تواند هر چیزی باشد.",
            data={
                "history": {"fields": ["preserve-me"]},
                "override": {
                    "version": 1,
                    "from_step_id": self.step_one.pk,
                    "from_step_name": self.step_one.name,
                    "to_step_id": self.step_two.pk,
                    "to_step_name": self.step_two.name,
                    "reason": "اصلاح ساختاری مسیر",
                },
            },
        )
        WorkflowStepAssignmentHistory.objects.create(
            step_execution=execution,
            instance=self.instance,
            workflow_step=execution.workflow_step,
            previous_assignee=None,
            new_assignee=self.assignee,
            changed_by=self.reviewer,
            source=WorkflowStepAssignmentHistory.Source.OVERRIDE,
            reason="اصلاح ساختاری مسیر",
        )

        event = next(
            item for item in build_instance_timeline_events(self.instance)
            if item["id"] == f"step-{execution.pk}"
        )

        self.assertEqual(event["type"], "override")
        self.assertEqual(event["title"], "اصلاح مسیر فرآیند")
        self.assertEqual(event["override_from_step"], "مرحله اول")
        self.assertEqual(event["override_to_step"], "مرحله دوم")
        self.assertEqual(event["override_reason"], "اصلاح ساختاری مسیر")
        self.assertEqual(event["description"], "")
        self.assertEqual(event["history"], {"fields": ["preserve-me"]})

    def test_legacy_override_is_detected_from_assignment_history_without_note_prefix(self):
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_two,
            performed_by=self.reviewer,
            notes="یادداشت قدیمی یا تغییر یافته",
        )
        WorkflowStepAssignmentHistory.objects.create(
            step_execution=execution,
            instance=self.instance,
            workflow_step=execution.workflow_step,
            previous_assignee=None,
            new_assignee=self.assignee,
            changed_by=self.reviewer,
            source=WorkflowStepAssignmentHistory.Source.OVERRIDE,
            reason="دلیل ثبت‌شده در سابقه تخصیص",
        )

        event = next(
            item for item in build_instance_timeline_events(self.instance)
            if item["id"] == f"step-{execution.pk}"
        )

        self.assertEqual(event["type"], "override")
        self.assertEqual(event["override_from_step"], "—")
        self.assertEqual(event["override_to_step"], "مرحله دوم")
        self.assertEqual(event["override_reason"], "دلیل ثبت‌شده در سابقه تخصیص")

    def test_equal_timestamp_step_events_use_numeric_id_order(self):
        timestamp = timezone.now()
        executions = [
            WorkflowStepExecution.objects.create(
                instance=self.instance,
                workflow_step=self.step_one,
                performed_by=self.starter,
            )
            for _ in range(12)
        ]
        WorkflowStepExecution.objects.filter(
            pk__in=[item.pk for item in executions]
        ).update(performed_at=timestamp)
        WorkflowInstance.objects.filter(pk=self.instance.pk).update(
            started_at=timestamp - timedelta(minutes=1)
        )
        self.instance.refresh_from_db()

        events = build_instance_timeline_events(self.instance)
        step_ids = [
            int(event["id"].rsplit("-", 1)[-1])
            for event in events
            if event["type"] == "step"
        ]

        self.assertEqual(step_ids, sorted(step_ids))

    def test_accepted_transition_without_acceptance_does_not_create_resolution_event(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow, name="انتقال عادی",
            code="TIMELINE_NO_ACCEPTANCE", from_step=self.step_one,
            to_step=self.step_two, requires_acceptance=False,
        )
        WorkflowTransitionExecution.objects.create(
            instance=self.instance, transition=transition,
            performed_by=self.starter,
            status=WorkflowTransitionExecution.Status.ACCEPTED,
            accepted_by=self.reviewer, resolved_at=timezone.now(),
        )
        events = build_instance_timeline_events(self.instance)
        self.assertEqual([event["type"] for event in events], ["start", "transition"])

    def test_rejected_transition_uses_return_step_and_exposes_proposed_assignee(self):
        return_step = WorkflowStep.objects.create(
            workflow=self.workflow, name="مرحله بازگشت",
            code="TIMELINE_RETURN_STEP", order=3,
        )
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow, name="ارسال برای تأیید",
            code="TIMELINE_REJECT_ROUTE", from_step=self.step_one,
            to_step=self.step_two, reject_to_step=return_step,
            requires_acceptance=True,
        )
        execution = WorkflowTransitionExecution.objects.create(
            instance=self.instance, transition=transition,
            performed_by=self.starter,
            status=WorkflowTransitionExecution.Status.REJECTED,
            rejected_by=self.reviewer, proposed_assignee=self.assignee,
            resolved_at=None,
        )
        events = build_instance_timeline_events(self.instance)
        request_event = next(e for e in events if e["type"] == "transition")
        resolution_event = next(e for e in events if e["type"] == "transition_resolution")
        self.assertEqual(request_event["to_step"], "مرحله بازگشت")
        self.assertEqual(request_event["proposed_assignee"], "Ali Rezaei")
        self.assertEqual(resolution_event["to_step"], "مرحله بازگشت")
        self.assertEqual(resolution_event["proposed_assignee"], "Ali Rezaei")
        self.assertIsNone(resolution_event["performed_at"])
        self.assertTrue(resolution_event["timestamp_missing"])
        self.assertEqual(resolution_event["id"], f"transition-resolution-{execution.pk}")

    def test_legacy_step_actor_is_explicitly_labeled_and_not_misidentified_as_completer(self):
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance, workflow_step=self.step_one,
            performed_by=self.reviewer, entered_by=None, completed_by=None,
        )
        event = next(e for e in build_instance_timeline_events(self.instance)
                     if e["id"] == f"step-{execution.pk}")
        self.assertEqual(event["user"], "timeline-reviewer")
        self.assertEqual(event["user_source"], "performed_by_legacy")
        self.assertIn("Legacy", event["user_role_label"])
        self.assertEqual(event["completed_by"], "—")

    def test_rejects_non_instance_argument(self):
        with self.assertRaises(TypeError):
            build_instance_timeline_events(None)
