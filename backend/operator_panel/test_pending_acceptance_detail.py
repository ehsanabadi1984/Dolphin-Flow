from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormSection,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
    WorkflowTransitionExecution,
)
from workflow.form_file_models import FormFile


User = get_user_model()


class PendingAcceptanceDetailViewTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            username="pending_detail_sender",
            password="test-password",
        )
        self.receiver = User.objects.create_user(
            username="pending_detail_receiver",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Pending Detail Workflow",
            code="PENDING_DETAIL_WORKFLOW",
            is_active=True,
        )
        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Send",
            code="PENDING_DETAIL_SEND",
            order=1,
            is_active=True,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Receive",
            code="PENDING_DETAIL_RECEIVE",
            order=2,
            is_active=True,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Send to Receive",
            code="PENDING_DETAIL_TRANSITION",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
            requires_acceptance=True,
            reject_to_step=self.step_one,
        )

        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Pending Detail Form",
            is_active=True,
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Main",
            code="PENDING_DETAIL_SECTION",
            order=1,
        )
        self.field = FormField.objects.create(
            section=self.section,
            name="Customer Name",
            code="customer_name",
            label="Customer Name",
            field_type=FormField.FieldType.TEXT,
            order=1,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.sender,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.receiver,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_one,
            started_by=self.sender,
            status=WorkflowInstance.Status.ACTIVE,
        )
        WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=self.transition,
            performed_by=self.sender,
            status=WorkflowTransitionExecution.Status.PENDING,
        )
        FormData.objects.create(
            instance=self.instance,
            data={"customer_name": "Customer One"},
        )
        FieldAccess.objects.create(
            field=self.field,
            step=self.step_one,
            user=self.receiver,
            can_view=True,
            can_edit=False,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_two,
            user=self.receiver,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.client.force_login(self.receiver)

    def test_pending_detail_is_visible_without_general_view_permission(self):
        execution = WorkflowTransitionExecution.objects.get(instance=self.instance)

        response = self.client.get(
            reverse(
                "operator_panel:pending_acceptance_detail",
                args=[execution.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customer One")
        self.assertContains(
            response,
            "این فرآیند در انتظار تأیید دریافت است.",
        )
        self.assertFalse(
            response.context["edit_mode"]
        )

    def test_pending_detail_does_not_grant_access_without_accept_or_reject(self):
        WorkflowPermission.objects.filter(
            workflow=self.workflow,
            step=self.step_two,
            user=self.receiver,
        ).delete()

        execution = self.instance.transition_executions.get()

        response = self.client.get(
            reverse(
                "operator_panel:pending_acceptance_detail",
                args=[execution.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_normal_workflow_instance_still_requires_view_permission(self):
        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_pending_detail_is_read_only_and_has_no_normal_transition_actions(self):
        execution = self.instance.transition_executions.get()

        response = self.client.get(
            reverse(
                "operator_panel:pending_acceptance_detail",
                args=[execution.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "ویرایش اطلاعات")
        self.assertNotContains(response, "ذخیره")
        self.assertNotContains(response, "عملیات فرآیند")
        self.assertContains(response, "تأیید دریافت")


    def test_pending_acceptance_file_is_downloadable_without_general_view(self):
        execution = self.instance.transition_executions.get()
        form_file = FormFile.objects.create(
            form_data=self.instance.form_data,
            field=self.field,
            row_id="",
            file=SimpleUploadedFile(
                "pending.txt",
                b"pending acceptance file",
                content_type="text/plain",
            ),
            original_name="pending.txt",
            file_size=22,
            content_type="text/plain",
            uploaded_by=self.sender,
        )

        response = self.client.get(
            reverse(
                "operator_panel:download_pending_acceptance_file",
                args=[execution.pk, form_file.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"pending acceptance file")

    def test_pending_acceptance_file_cannot_use_another_instance_file(self):
        other_instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_one,
            started_by=self.sender,
            status=WorkflowInstance.Status.ACTIVE,
        )
        other_form_data = FormData.objects.create(
            instance=other_instance,
            data={"customer_name": "Other Customer"},
        )
        form_file = FormFile.objects.create(
            form_data=other_form_data,
            field=self.field,
            row_id="",
            file=SimpleUploadedFile(
                "other.txt",
                b"other instance file",
                content_type="text/plain",
            ),
            original_name="other.txt",
            file_size=18,
            content_type="text/plain",
            uploaded_by=self.sender,
        )
        execution = self.instance.transition_executions.get()

        response = self.client.get(
            reverse(
                "operator_panel:download_pending_acceptance_file",
                args=[execution.pk, form_file.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_pending_acceptance_file_requires_field_view_permission(self):
        execution = self.instance.transition_executions.get()
        form_file = FormFile.objects.create(
            form_data=self.instance.form_data,
            field=self.field,
            row_id="",
            file=SimpleUploadedFile(
                "hidden.txt",
                b"hidden file",
                content_type="text/plain",
            ),
            original_name="hidden.txt",
            file_size=11,
            content_type="text/plain",
            uploaded_by=self.sender,
        )
        FieldAccess.objects.filter(
            field=self.field,
            step=self.step_one,
            user=self.receiver,
        ).update(can_view=False)

        response = self.client.get(
            reverse(
                "operator_panel:download_pending_acceptance_file",
                args=[execution.pk, form_file.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_pending_acceptance_file_metadata_uses_scoped_download_url(self):
        execution = self.instance.transition_executions.get()
        form_file = FormFile.objects.create(
            form_data=self.instance.form_data,
            field=self.field,
            row_id="",
            file=SimpleUploadedFile(
                "pending.txt",
                b"pending acceptance file",
                content_type="text/plain",
            ),
            original_name="pending.txt",
            file_size=22,
            content_type="text/plain",
            uploaded_by=self.sender,
        )

        response = self.client.get(
            reverse("operator_panel:file_field_definitions", args=[self.instance.pk]),
            {"pending_acceptance_id": execution.pk},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["fields"][0]["file"]["url"],
            reverse(
                "operator_panel:download_pending_acceptance_file",
                args=[execution.pk, form_file.pk],
            ),
        )
