from django.test import TestCase
from django.contrib.auth.models import Permission
from django.urls import reverse

from accounts.models import User
from workflow.form_file_models import FormFile, SharedFileAsset
from workflow.file_share_services import FileShareDraftService
from workflow.models import (
    FileShareDraft, FileShareMessage, FileShareMessageEvent, Notification,
    FormData, FormDefinition, FormField, FormSection,
    Workflow, WorkflowInstance, WorkflowStep, WorkflowTransition,
    WorkflowTransitionExecution, WorkflowMembership, FieldAccess,
    WorkflowPermission,
)


class FileShareDraftFinalizationTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(username="draft-sender", password="pass")
        self.recipient_one = User.objects.create_user(username="draft-recipient-1", password="pass")
        self.recipient_two = User.objects.create_user(username="draft-recipient-2", password="pass")
        self.workflow = Workflow.objects.create(name="Draft workflow", code="DRAFT_WF")
        self.step = WorkflowStep.objects.create(workflow=self.workflow, name="Current", code="CURRENT", order=1)
        self.instance = WorkflowInstance.objects.create(workflow=self.workflow, current_step=self.step, started_by=self.sender)
        for member in (self.sender, self.recipient_one, self.recipient_two):
            WorkflowMembership.objects.create(
                workflow=self.workflow, user=member,
                role=WorkflowMembership.Role.EXECUTOR, is_active=True,
            )
        self.sender.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts",
            content_type__model="user",
            codename="share_files",
        ))
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.sender,
            action=WorkflowPermission.Action.SHARE_FILES,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.form = FormDefinition.objects.create(workflow=self.workflow, name="Draft form")
        self.section = FormSection.objects.create(form=self.form, name="Files", code="FILES")
        self.field = FormField.objects.create(
            section=self.section, name="Attachment", code="ATTACHMENT",
            label="Attachment", field_type=FormField.FieldType.FILE,
            allow_file_sharing=True,
        )
        FieldAccess.objects.create(
            field=self.field, step=self.step, user=self.sender,
            can_view=True, can_edit=False,
        )
        self.form_data = FormData.objects.create(instance=self.instance, data={})
        self.form_file = FormFile.objects.create(
            form_data=self.form_data, field=self.field, row_id="",
            file="workflow_forms/1/ATTACHMENT/draft.pdf",
            original_name="draft.pdf", file_size=123, content_type="application/pdf",
            uploaded_by=self.sender,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow, from_step=self.step, to_step=None,
            name="Finish", code="FINISH_DRAFT",
        )
        self.execution = WorkflowTransitionExecution.objects.create(
            instance=self.instance, transition=self.transition, performed_by=self.sender,
        )

    def _draft(self, recipient):
        return FileShareDraft.objects.create(
            sender=self.sender, recipient=recipient,
            workflow_instance=self.instance, workflow_step=self.step,
            form_file=self.form_file,
            interaction_type=FileShareMessage.InteractionType.VIEW,
            subject="Please review",
        )

    def test_inbox_page_and_draft_api_are_available_to_authenticated_sender(self):
        draft = self._draft(self.recipient_one)
        self.client.force_login(self.sender)

        page = self.client.get(reverse("operator_panel:file_share_inbox_page"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "صندوق پیام‌ها")

        response = self.client.get(reverse("operator_panel:file_share_inbox"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["drafts"]), 1)
        self.assertEqual(payload["drafts"][0]["id"], draft.pk)
        self.assertEqual(payload["drafts"][0]["body"], draft.body)
        self.assertTrue(payload["drafts"][0]["update_url"])
        self.assertTrue(payload["drafts"][0]["delete_url"])

    def test_file_field_definitions_exposes_shareable_only_with_all_permissions(self):
        self.client.force_login(self.sender)
        url = reverse("operator_panel:file_field_definitions", args=[self.instance.pk])

        allowed = self.client.get(url)
        self.assertEqual(allowed.status_code, 200)
        field_payload = next(
            item for item in allowed.json()["fields"]
            if item["code"] == self.field.code
        )
        self.assertTrue(field_payload["shareable"])

        WorkflowPermission.objects.filter(
            workflow=self.workflow,
            step=self.step,
            user=self.sender,
            action=WorkflowPermission.Action.SHARE_FILES,
        ).delete()

        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 200)
        field_payload = next(
            item for item in denied.json()["fields"]
            if item["code"] == self.field.code
        )
        self.assertFalse(field_payload["shareable"])

    def test_recipient_discovery_requires_global_and_step_permissions(self):
        self.client.force_login(self.sender)
        url = reverse("operator_panel:file_share_inbox")
        allowed = self.client.get(url, {
            "instance_id": self.instance.pk,
            "step_id": self.step.pk,
        })
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(
            {item["id"] for item in allowed.json()["available_recipients"]},
            {self.recipient_one.pk, self.recipient_two.pk},
        )

        WorkflowPermission.objects.filter(
            workflow=self.workflow,
            step=self.step,
            user=self.sender,
            action=WorkflowPermission.Action.SHARE_FILES,
        ).delete()
        denied = self.client.get(url, {
            "instance_id": self.instance.pk,
            "step_id": self.step.pk,
        })
        self.assertEqual(denied.status_code, 403)

    def test_create_drafts_creates_independent_recipient_requests(self):
        drafts = FileShareDraftService.create_drafts(
            instance=self.instance,
            step=self.step,
            sender=self.sender,
            form_file=self.form_file,
            recipient_ids=[self.recipient_one.pk, self.recipient_two.pk],
            interaction_type=FileShareMessage.InteractionType.REVIEW,
            subject="Please approve",
            body="Review this attachment",
        )
        self.assertEqual(len(drafts), 2)
        self.assertEqual(
            {draft.recipient_id for draft in drafts},
            {self.recipient_one.pk, self.recipient_two.pk},
        )
        self.assertEqual(
            {draft.form_file_id for draft in drafts},
            {self.form_file.pk},
        )

    def test_sender_can_update_and_delete_only_unconverted_drafts(self):
        draft = self._draft(self.recipient_one)
        updated = FileShareDraftService.update_draft(
            draft_id=draft.pk,
            sender=self.sender,
            subject="Updated subject",
            body="Updated body",
            interaction_type=FileShareMessage.InteractionType.ACTION,
        )
        self.assertEqual(updated.subject, "Updated subject")
        self.assertEqual(updated.body, "Updated body")
        self.assertEqual(updated.interaction_type, FileShareMessage.InteractionType.ACTION)
        FileShareDraftService.delete_draft(draft_id=draft.pk, sender=self.sender)
        self.assertFalse(FileShareDraft.objects.filter(pk=draft.pk).exists())

    def test_create_drafts_updates_existing_file_drafts_and_reconciles_recipients(self):
        first = self._draft(self.recipient_one)
        removed = self._draft(self.recipient_two)
        drafts = FileShareDraftService.create_drafts(
            instance=self.instance, step=self.step, sender=self.sender,
            form_file=self.form_file, recipient_ids=[self.recipient_one.pk],
            interaction_type=FileShareMessage.InteractionType.REVIEW,
            subject="Revised subject", body="Revised details",
        )
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].pk, first.pk)
        first.refresh_from_db()
        self.assertEqual(first.interaction_type, FileShareMessage.InteractionType.REVIEW)
        self.assertEqual(first.subject, "Revised subject")
        self.assertEqual(first.body, "Revised details")
        self.assertFalse(FileShareDraft.objects.filter(pk=removed.pk).exists())
        self.assertEqual(FileShareDraft.objects.filter(
            sender=self.sender, form_file=self.form_file,
            status=FileShareDraft.Status.DRAFT,
        ).count(), 1)

    def test_file_share_get_returns_drafts_for_the_selected_file(self):
        draft = self._draft(self.recipient_one)
        self.client.force_login(self.sender)
        response = self.client.get(reverse("operator_panel:file_share_inbox"), {
            "instance_id": self.instance.pk,
            "step_id": self.step.pk,
            "form_file_id": self.form_file.pk,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["file_drafts"]), 1)
        self.assertEqual(payload["file_drafts"][0]["id"], draft.pk)
        self.assertEqual(payload["file_drafts"][0]["recipient_id"], self.recipient_one.pk)

    def test_unread_message_count_endpoint_tracks_pending_and_read_messages(self):
        asset = SharedFileAsset.get_or_create_for_form_file(self.form_file)[0]
        message = FileShareMessage.objects.create(
            asset=asset, sender=self.sender, recipient=self.recipient_one,
            workflow_instance=self.instance, workflow_step=self.step,
        )
        self.client.force_login(self.recipient_one)
        url = reverse("operator_panel:file_share_inbox")
        unread = self.client.get(url, {"counts_only": "1"})
        self.assertEqual(unread.status_code, 200)
        self.assertEqual(unread.json()["unread_messages_count"], 1)

        from workflow.file_share_services import FileShareMessageService
        FileShareMessageService.transition_status(
            message=message, to_status=FileShareMessage.Status.READ,
            actor=self.recipient_one,
        )
        read = self.client.get(url, {"counts_only": "1"})
        self.assertEqual(read.json()["unread_messages_count"], 0)

    def test_file_share_notification_links_to_mailbox_message_view(self):
        asset = SharedFileAsset.get_or_create_for_form_file(self.form_file)[0]
        message = FileShareMessage.objects.create(
            asset=asset, sender=self.sender, recipient=self.recipient_one,
            workflow_instance=self.instance, workflow_step=self.step,
        )
        Notification.objects.create(
            recipient=self.recipient_one,
            notification_type=Notification.NotificationType.FILE_SHARE_MESSAGE,
            title="فایل جدید",
            message="فایلی برای شما ارسال شده است.",
            workflow_instance=self.instance,
            workflow_step=self.step,
            file_share_message=message,
        )
        self.client.force_login(self.recipient_one)
        response = self.client.get(reverse("operator_panel:notifications"))
        self.assertEqual(response.status_code, 200)
        notification = response.json()["notifications"][0]
        expected_url = (
            reverse("operator_panel:file_share_inbox_page")
            + f"?message_id={message.pk}"
        )
        self.assertEqual(notification["workflow_instance_url"], expected_url)
        self.assertEqual(notification["file_share_message_url"], expected_url)

    def test_submit_converts_one_draft_per_recipient_without_copying_file(self):
        first = self._draft(self.recipient_one)
        second = self._draft(self.recipient_two)

        messages = FileShareDraftService.finalize_for_submit(
            instance=self.instance, step=self.step, sender=self.sender,
            transition_execution=self.execution, form_snapshot={"fields": {"x": "y"}},
        )

        self.assertEqual(len(messages), 2)
        self.assertEqual(FileShareMessage.objects.count(), 2)
        self.assertEqual(messages[0].asset_id, messages[1].asset_id)
        self.assertEqual(messages[0].asset.storage_name, self.form_file.file.name)
        for draft in (first, second):
            draft.refresh_from_db()
            self.assertEqual(draft.status, FileShareDraft.Status.CONVERTED)
            self.assertIsNone(draft.form_file_id)
            self.assertIsNotNone(draft.file_share_message_id)
            self.assertIsNotNone(draft.converted_at)
        self.assertEqual(FileShareMessageEvent.objects.filter(
            event_type=FileShareMessageEvent.EventType.SENT
        ).count(), 2)
        notifications = Notification.objects.filter(
            notification_type=Notification.NotificationType.FILE_SHARE_MESSAGE,
            file_share_message__in=messages,
        )
        self.assertEqual(notifications.count(), 2)
        self.assertEqual(
            set(notifications.values_list("recipient_id", flat=True)),
            {self.recipient_one.pk, self.recipient_two.pk},
        )

    def test_recipient_scoped_message_detail_does_not_grant_sender_access(self):
        asset = SharedFileAsset.get_or_create_for_form_file(self.form_file)[0]
        message = FileShareMessage.objects.create(
            asset=asset, sender=self.sender, recipient=self.recipient_one,
            workflow_instance=self.instance, workflow_step=self.step,
            form_snapshot={"file": {"field_label": self.field.label}},
        )
        self.client.force_login(self.sender)
        denied = self.client.get(reverse(
            "operator_panel:file_share_message_detail", args=[message.pk]
        ))
        self.assertEqual(denied.status_code, 404)

        self.client.force_login(self.recipient_one)
        allowed = self.client.get(reverse(
            "operator_panel:file_share_message_detail", args=[message.pk]
        ))
        self.assertEqual(allowed.status_code, 200)
        details = allowed.json()["file_details"]
        self.assertEqual(details["field_label"], self.field.label)
        self.assertEqual(details["original_name"], "draft.pdf")
        self.assertEqual(details["file_size"], 123)
        self.assertEqual(details["content_type"], "application/pdf")
        self.assertNotIn("field_code", details)
        self.assertNotIn("row_id", details)
        self.assertNotIn("form_snapshot", allowed.json())
        message.refresh_from_db()
        self.assertEqual(message.status, FileShareMessage.Status.READ)

    def test_recipient_can_open_cancelled_message_and_sees_unavailable_notice_payload(self):
        asset = SharedFileAsset.get_or_create_for_form_file(self.form_file)[0]
        message = FileShareMessage.objects.create(
            asset=asset, sender=self.sender, recipient=self.recipient_one,
            workflow_instance=self.instance, workflow_step=self.step,
            form_snapshot={"file": {"field_label": self.field.label}},
            subject="Cancelled attachment",
        )
        self.client.force_login(self.sender)
        recalled = self.client.post(reverse(
            "operator_panel:file_share_message_recall", args=[message.pk]
        ))
        self.assertEqual(recalled.status_code, 200)

        self.client.force_login(self.recipient_one)
        response = self.client.get(reverse(
            "operator_panel:file_share_message_detail", args=[message.pk]
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        payload = response.json()
        self.assertEqual(payload["status"], FileShareMessage.Status.CANCELLED)
        self.assertTrue(payload["unavailable"])
        self.assertIn("لغو", payload["unavailable_message"])
        self.assertNotIn("download_url", payload)
        self.assertNotIn("file_details", payload)

    def test_opening_messages_marks_linked_notifications_read_for_every_status(self):
        asset = SharedFileAsset.get_or_create_for_form_file(self.form_file)[0]
        statuses = (
            FileShareMessage.Status.PENDING,
            FileShareMessage.Status.CANCELLED,
            FileShareMessage.Status.EXPIRED,
        )
        self.client.force_login(self.recipient_one)

        for status in statuses:
            with self.subTest(status=status):
                message = FileShareMessage.objects.create(
                    asset=asset, sender=self.sender, recipient=self.recipient_one,
                    workflow_instance=self.instance, workflow_step=self.step,
                    form_snapshot={"file": {"field_label": self.field.label}},
                    subject=f"Message {status}",
                )
                if status != FileShareMessage.Status.PENDING:
                    from workflow.file_share_services import FileShareMessageService

                    FileShareMessageService.transition_status(
                        message=message,
                        to_status=status,
                        actor=(
                            self.sender
                            if status == FileShareMessage.Status.CANCELLED
                            else None
                        ),
                    )
                notification = Notification.objects.create(
                    recipient=self.recipient_one,
                    notification_type=Notification.NotificationType.FILE_SHARE_MESSAGE,
                    title="فایل جدید",
                    message="فایلی برای شما ارسال شده است.",
                    workflow_instance=self.instance,
                    workflow_step=self.step,
                    file_share_message=message,
                )

                response = self.client.get(reverse(
                    "operator_panel:file_share_message_detail", args=[message.pk]
                ))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/json")
                notification.refresh_from_db()
                self.assertTrue(notification.is_read)

                if status == FileShareMessage.Status.PENDING:
                    message.refresh_from_db()
                    self.assertEqual(message.status, FileShareMessage.Status.READ)
                else:
                    self.assertEqual(response.json()["status"], status)

    def test_file_deletion_cascades_only_unconverted_drafts(self):
        draft = self._draft(self.recipient_one)
        FileShareDraftService.finalize_for_submit(
            instance=self.instance, step=self.step, sender=self.sender,
            transition_execution=self.execution, form_snapshot={},
        )
        draft.refresh_from_db()
        converted_id = draft.pk
        self.assertEqual(draft.status, FileShareDraft.Status.CONVERTED)
        self.assertIsNone(draft.form_file_id)
        self.assertTrue(FileShareDraft.objects.filter(pk=converted_id).exists())

        temporary = self._draft(self.recipient_two)
        self.form_file.delete()
        self.assertFalse(FileShareDraft.objects.filter(pk=temporary.pk).exists())
        self.assertTrue(FileShareDraft.objects.filter(pk=converted_id).exists())
