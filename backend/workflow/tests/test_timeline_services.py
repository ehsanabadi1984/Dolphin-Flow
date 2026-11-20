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

    def test_assignment_history_is_a_separate_timeline_event(self):
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_one,
            performed_by=self.starter,
            assigned_to=self.assignee,
        )
        assignment = WorkflowStepAssignmentHistory.objects.create(
            step_execution=execution,
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

    def test_rejects_non_instance_argument(self):
        with self.assertRaises(TypeError):
            build_instance_timeline_events(None)
