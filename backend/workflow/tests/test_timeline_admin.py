from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from workflow.admin import WorkflowInstanceAdmin, dolphin_admin_site
from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
)


User = get_user_model()


class WorkflowInstanceTimelineAdminTests(TestCase):
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


class WorkflowInstanceTimelineHttpTests(WorkflowInstanceTimelineAdminTests):
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
