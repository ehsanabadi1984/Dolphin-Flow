import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from workflow.form_file_models import FormFile, SharedFileAsset
from workflow.file_share_services import FileShareMessageService
from workflow.models import (
    FileShareMessage,
    FileShareMessageEvent,
    FormData,
    FormDefinition,
    FormField,
    FormSection,
    Notification,
    Workflow,
    WorkflowInstance,
    WorkflowStep,
)


class FileShareResponseViewTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(username="share-view-sender", password="test-password")
        self.recipient = User.objects.create_user(username="share-view-recipient", password="test-password")
        self.other = User.objects.create_user(username="share-view-other", password="test-password")
        self.workflow = Workflow.objects.create(name="Share response workflow", code="SHARE_RESPONSE")
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow, name="Review", code="REVIEW_RESPONSE", order=1
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow, current_step=self.step, started_by=self.sender
        )
        self.form = FormDefinition.objects.create(workflow=self.workflow, name="Share response form")
        self.section = FormSection.objects.create(form=self.form, name="Files", code="FILES_RESPONSE", order=1)
        self.field = FormField.objects.create(
            section=self.section, name="Attachment", code="ATTACHMENT_RESPONSE",
            label="Attachment", field_type=FormField.FieldType.FILE, order=1,
            allow_file_sharing=True,
        )
        self.form_data = FormData.objects.create(instance=self.instance, data={})
        self.form_file = FormFile.objects.create(
            form_data=self.form_data, field=self.field, row_id="",
            file="workflow_forms/1/ATTACHMENT_RESPONSE/document.pdf",
            original_name="document.pdf", file_size=1024,
            content_type="application/pdf", uploaded_by=self.sender,
        )
        asset = SharedFileAsset.get_or_create_for_form_file(self.form_file)[0]
        self.message = FileShareMessage.objects.create(
            asset=asset, sender=self.sender, recipient=self.recipient,
            workflow_instance=self.instance, workflow_step=self.step,
            interaction_type=FileShareMessage.InteractionType.RESPONSE,
            subject="Please review",
        )

    def test_recipient_response_completes_message_and_notifies_sender(self):
        self.client.force_login(self.recipient)
        response = self.client.post(
            reverse("operator_panel:file_share_message_respond", args=[self.message.pk]),
            data=json.dumps({"response": "بررسی انجام شد."}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], FileShareMessage.Status.COMPLETED)
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, FileShareMessage.Status.COMPLETED)
        event = self.message.events.get(event_type=FileShareMessageEvent.EventType.COMPLETED)
        self.assertEqual(event.details["response"], "بررسی انجام شد.")
        notification = Notification.objects.get(
            recipient=self.sender, file_share_message=self.message
        )
        self.assertFalse(notification.is_read)
        self.assertIn("بررسی انجام شد.", notification.message)

    def test_sender_can_open_sent_message_and_read_response(self):
        FileShareMessageService.transition_status(
            message=self.message,
            to_status=FileShareMessage.Status.READ,
            actor=self.recipient,
        )
        FileShareMessageService.transition_status(
            message=self.message,
            to_status=FileShareMessage.Status.COMPLETED,
            actor=self.recipient,
            details={"response": "نتیجه بررسی"},
        )
        self.client.force_login(self.sender)
        response = self.client.get(
            reverse("operator_panel:file_share_message_detail", args=[self.message.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_sender"])
        self.assertEqual(response.json()["response"], "نتیجه بررسی")
        self.assertEqual(response.json()["file_details"]["original_name"], "document.pdf")
        self.assertEqual(response.json()["file_name"], "document.pdf")
        self.assertNotIn("download_url", response.json())

    def test_unrelated_user_cannot_open_message_detail(self):
        self.client.force_login(self.other)
        response = self.client.get(
            reverse("operator_panel:file_share_message_detail", args=[self.message.pk])
        )
        self.assertEqual(response.status_code, 404)
