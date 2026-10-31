from django.test import TestCase

from accounts.models import User
from workflow.form_file_models import FormFile
from workflow.file_share_services import FileShareDraftService
from workflow.models import (
    FileShareDraft, FileShareMessage, FileShareMessageEvent,
    FormData, FormDefinition, FormField, FormSection,
    Workflow, WorkflowInstance, WorkflowStep, WorkflowTransition,
    WorkflowTransitionExecution,
)


class FileShareDraftFinalizationTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(username="draft-sender", password="pass")
        self.recipient_one = User.objects.create_user(username="draft-recipient-1", password="pass")
        self.recipient_two = User.objects.create_user(username="draft-recipient-2", password="pass")
        self.workflow = Workflow.objects.create(name="Draft workflow", code="DRAFT_WF")
        self.step = WorkflowStep.objects.create(workflow=self.workflow, name="Current", code="CURRENT", order=1)
        self.instance = WorkflowInstance.objects.create(workflow=self.workflow, current_step=self.step, started_by=self.sender)
        self.form = FormDefinition.objects.create(workflow=self.workflow, name="Draft form")
        self.section = FormSection.objects.create(form=self.form, name="Files", code="FILES")
        self.field = FormField.objects.create(
            section=self.section, name="Attachment", code="ATTACHMENT",
            label="Attachment", field_type=FormField.FieldType.FILE,
            allow_file_sharing=True,
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
