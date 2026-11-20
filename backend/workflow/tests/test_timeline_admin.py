from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from workflow.admin import WorkflowInstanceAdmin, dolphin_admin_site
from workflow.form_file_models import SharedFileAsset
from workflow.models import (
    FileShareMessage,
    FileShareMessageEvent,
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


User = get_user_model()


class WorkflowInstanceTimelineAdminSetup:
    def setUp(self):
        self.viewer = User.objects.create_user(
            username="timeline-admin-viewer",
            password="test-password",
            is_staff=True,
        )
        self.starter = User.objects.create_user(
            username="timeline-admin-starter",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="Timeline admin workflow",
            code="TIMELINE_ADMIN_TEST",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="مرحله اول",
            code="TIMELINE_ADMIN_STEP",
            order=1,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.viewer,
            role=WorkflowMembership.Role.VIEWER,
            is_active=True,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.starter,
        )

        content_type = ContentType.objects.get_for_model(WorkflowInstance)
        view_permission = Permission.objects.get(
            content_type=content_type,
            codename="view_workflowinstance",
        )
        self.viewer.user_permissions.add(view_permission)

        self.factory = RequestFactory()
        self.model_admin = WorkflowInstanceAdmin(
            WorkflowInstance,
            dolphin_admin_site,
        )

    def grant_workflow_view(self, effect=WorkflowPermission.Effect.ALLOW):
        return WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.viewer,
            action=WorkflowPermission.Action.VIEW,
            effect=effect,
        )

    def get_request(self):
        request = self.factory.get(
            f"/admin/workflow/workflowinstance/{self.instance.pk}/timeline/"
        )
        request.user = self.viewer
        return request

class WorkflowInstanceTimelineAdminTests(WorkflowInstanceTimelineAdminSetup, TestCase):
    def test_timeline_uses_aggregated_service_for_authorized_user(self):
        self.grant_workflow_view()

        response = self.model_admin.timeline_view(
            self.get_request(),
            str(self.instance.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event["type"] for event in response.context_data["events"]],
            ["start"],
        )

    def test_timeline_denies_user_without_workflow_view_permission(self):
        with self.assertRaises(PermissionDenied):
            self.model_admin.timeline_view(
                self.get_request(),
                str(self.instance.pk),
            )

    def test_explicit_workflow_deny_blocks_timeline(self):
        self.grant_workflow_view()
        self.grant_workflow_view(effect=WorkflowPermission.Effect.DENY)

        with self.assertRaises(PermissionDenied):
            self.model_admin.timeline_view(
                self.get_request(),
                str(self.instance.pk),
            )

    def test_admin_model_view_permission_is_also_required(self):
        self.grant_workflow_view()
        self.viewer.user_permissions.clear()

        with self.assertRaises(PermissionDenied):
            self.model_admin.timeline_view(
                self.get_request(),
                str(self.instance.pk),
            )


class WorkflowInstanceTimelineHttpTests(WorkflowInstanceTimelineAdminSetup, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.viewer)
        self.timeline_url = reverse(
            "admin:workflow_workflowinstance_timeline",
            args=[self.instance.pk],
        )

    def test_authorized_user_can_open_timeline_through_admin_url(self):
        self.grant_workflow_view()

        response = self.client.get(self.timeline_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تاریخچه اجرای")

    def test_user_without_workflow_view_gets_forbidden_over_http(self):
        response = self.client.get(self.timeline_url)

        self.assertEqual(response.status_code, 403)

    def test_user_without_admin_model_view_gets_forbidden_over_http(self):
        self.grant_workflow_view()
        self.viewer.user_permissions.clear()

        response = self.client.get(self.timeline_url)

        self.assertEqual(response.status_code, 403)

    def test_instance_starter_implicit_view_is_limited_to_that_instance(self):
        self.instance.started_by = self.viewer
        self.instance.save(update_fields=["started_by"])

        own_response = self.client.get(self.timeline_url)
        self.assertEqual(own_response.status_code, 200)

        other_instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.starter,
        )
        other_url = reverse(
            "admin:workflow_workflowinstance_timeline",
            args=[other_instance.pk],
        )

        other_response = self.client.get(other_url)

        self.assertEqual(other_response.status_code, 403)
 
    def test_superuser_can_view_timeline_without_workflow_membership(self):
        superuser = User.objects.create_superuser(
            username="timeline-superuser",
            password="test-password",
        )
        WorkflowMembership.objects.filter(
            workflow=self.workflow,
            user=superuser,
        ).delete()
        client = Client()
        client.force_login(superuser)

        response = client.get(self.timeline_url)

        self.assertEqual(response.status_code, 200)


    def test_group_permission_grants_global_timeline_access(self):
        from django.contrib.auth.models import Group

        permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(WorkflowInstance),
            codename="view_all_workflowinstance_timelines",
        )
        group = Group.objects.create(name="Timeline auditors")
        group.permissions.add(permission)
        self.viewer.groups.add(group)
        WorkflowMembership.objects.filter(
            workflow=self.workflow,
            user=self.viewer,
        ).delete()

        response = self.client.get(self.timeline_url)

        self.assertEqual(response.status_code, 200)


    def test_global_timeline_permission_can_be_assigned_directly(self):
        permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(WorkflowInstance),
            codename="view_all_workflowinstance_timelines",
        )
        self.viewer.user_permissions.add(permission)
        WorkflowMembership.objects.filter(
            workflow=self.workflow,
            user=self.viewer,
        ).delete()

        response = self.client.get(self.timeline_url)

        self.assertEqual(response.status_code, 200)

    def test_timeline_renders_dedicated_details_for_step_transition_resolution_and_file_share(self):
        self.grant_workflow_view()
        assigned_at = timezone.now() - timedelta(minutes=10)
        submitted_at = timezone.now()
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.viewer,
            entered_by=self.viewer,
            assigned_to=self.starter,
            assigned_at=assigned_at,
            completed_by=self.starter,
            is_submitted=True,
            submitted_at=submitted_at,
        )
        WorkflowStepAssignmentHistory.objects.create(
            step_execution=execution,
            previous_assignee=None,
            new_assignee=self.starter,
            changed_by=self.viewer,
            source=WorkflowStepAssignmentHistory.Source.MANUAL,
            reason="تخصیص برای بررسی",
        )
        target_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="مرحله مقصد",
            code="TIMELINE_RENDER_TARGET",
            order=2,
        )
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="ارسال برای بررسی",
            code="TIMELINE_RENDER_TRANSITION",
            from_step=self.step,
            to_step=target_step,
        )
        WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=transition,
            performed_by=self.viewer,
            status=WorkflowTransitionExecution.Status.ACCEPTED,
            accepted_by=self.starter,
            resolved_at=submitted_at,
            notes="یادداشت تصمیم انتقال",
        )
        finish_transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="تکمیل فرآیند",
            code="TIMELINE_RENDER_FINISH",
            from_step=target_step,
            to_step=None,
        )
        WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=finish_transition,
            performed_by=self.viewer,
            status=WorkflowTransitionExecution.Status.ACCEPTED,
        )
        asset = SharedFileAsset.objects.create(
            storage_name="timeline/render-test.pdf",
            original_name="render-test.pdf",
            file_size=100,
            content_type="application/pdf",
        )
        message = FileShareMessage.objects.create(
            asset=asset,
            sender=self.viewer,
            recipient=self.starter,
            workflow_instance=self.instance,
            workflow_step=self.step,
            interaction_type=FileShareMessage.InteractionType.REVIEW,
            subject="مدرک بررسی",
        )
        FileShareMessageEvent.objects.create(
            message=message,
            event_type=FileShareMessageEvent.EventType.SENT,
            actor=self.viewer,
            details={"note": "ارسال برای بررسی"},
        )

        response = self.client.get(self.timeline_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اجرای مرحله")
        self.assertContains(response, "مسئول اجرا")
        self.assertContains(response, "زمان تخصیص")
        self.assertContains(response, "تکمیل‌کننده")
        self.assertContains(response, "زمان ثبت نهایی")
        self.assertContains(response, "انتقال مرحله")
        self.assertContains(response, "وضعیت انتقال")
        self.assertContains(response, "یادداشت انتقال")
        self.assertContains(response, "تعیین تکلیف انتقال")
        self.assertContains(response, "تصمیم‌گیرنده")
        self.assertContains(response, "رویداد اشتراک فایل")
        self.assertContains(response, "نوع تعامل")
        self.assertContains(response, "وضعیت پیام")
        self.assertContains(response, "مدرک بررسی")
        self.assertContains(response, "تکمیل فرآیند")
        self.assertContains(response, "انجام‌دهنده تکمیل")
        self.assertContains(response, "تغییر مسئول")

    def test_override_is_distinct_and_null_resolution_timestamp_does_not_break_timeline(self):
        self.grant_workflow_view()
        target_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="مرحله دوم",
            code="TIMELINE_ADMIN_STEP_2",
            order=2,
        )
        override_time = timezone.now()
        execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=target_step,
            performed_by=self.viewer,
            entered_by=self.viewer,
            assigned_to=self.starter,
            performed_at=override_time,
            notes=(
                "اصلاح مسیر فرآیند: مرحله اول → مرحله دوم | "
                "دلیل: اصلاح آزمایشی مسیر"
            ),
        )
        WorkflowStepAssignmentHistory.objects.create(
            step_execution=execution,
            previous_assignee=None,
            new_assignee=self.starter,
            changed_by=self.viewer,
            source=WorkflowStepAssignmentHistory.Source.OVERRIDE,
            reason="اصلاح آزمایشی مسیر",
        )
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="انتقال نیازمند تعیین تکلیف",
            code="TIMELINE_PENDING_RESOLUTION",
            from_step=self.step,
            to_step=target_step,
        )
        WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=transition,
            performed_by=self.viewer,
            status=WorkflowTransitionExecution.Status.ACCEPTED,
            accepted_by=self.viewer,
            resolved_at=None,
        )

        response = self.client.get(self.timeline_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اصلاح مدیریتی مسیر")
        self.assertContains(response, "مرحله مبدأ")
        self.assertContains(response, "مرحله مقصد")
        self.assertContains(response, "مسئول مرحله مقصد")
        self.assertContains(response, "اصلاح آزمایشی مسیر")
        self.assertContains(response, "تغییر مسئول")
        self.assertContains(response, "مسئول جدید")
        self.assertContains(response, "زمان دقیق ثبت نشده است")
