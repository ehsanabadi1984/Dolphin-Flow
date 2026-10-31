from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.core.files.storage import default_storage
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from workflow.form_file_models import FormFile, SharedFileAsset
from workflow.file_lifecycle_services import FileLifecycleService
from workflow.file_share_services import FileShareMessageService
from workflow.models import (
    FileShareMessage, FileShareMessageEvent, FormData, FormDefinition,
    FormField, FormSection, Workflow, WorkflowInstance, WorkflowStep,
)


class FileShareModelTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(username="share-sender", password="test-password")
        self.recipient_one = User.objects.create_user(username="share-recipient-one", password="test-password")
        self.recipient_two = User.objects.create_user(username="share-recipient-two", password="test-password")
        self.workflow = Workflow.objects.create(name="Share model workflow", code="SHARE_MODEL")
        self.step = WorkflowStep.objects.create(workflow=self.workflow, name="Review", code="REVIEW", order=1)
        self.instance = WorkflowInstance.objects.create(workflow=self.workflow, current_step=self.step, started_by=self.sender)
        self.form = FormDefinition.objects.create(workflow=self.workflow, name="Share form")
        self.section = FormSection.objects.create(form=self.form, name="Files", code="FILES", order=1)
        self.field = FormField.objects.create(
            section=self.section, name="Attachment", code="ATTACHMENT",
            label="Attachment", field_type=FormField.FieldType.FILE,
            order=1, allow_file_sharing=True,
        )
        self.form_data = FormData.objects.create(instance=self.instance, data={})
        self.form_file = FormFile.objects.create(
            form_data=self.form_data, field=self.field, row_id="",
            file="workflow_forms/1/ATTACHMENT/document.pdf",
            original_name="document.pdf", file_size=1024,
            content_type="application/pdf", uploaded_by=self.sender,
        )

    def make_asset(self):
        return SharedFileAsset.get_or_create_for_form_file(self.form_file)[0]

    def make_message(self, recipient, **kwargs):
        return FileShareMessage.objects.create(
            asset=self.make_asset(), sender=self.sender, recipient=recipient,
            workflow_instance=self.instance, workflow_step=self.step, **kwargs,
        )

    def test_asset_references_existing_file_without_copying(self):
        asset = self.make_asset()
        self.assertEqual(asset.form_file_id, self.form_file.pk)
        self.assertEqual(asset.storage_name, self.form_file.file.name)

    def test_asset_keeps_original_storage_path_after_form_file_replacement(self):
        asset = self.make_asset()
        original_path = asset.storage_name

        self.form_file.file = "workflow_forms/1/ATTACHMENT/replacement.pdf"
        self.form_file.save(update_fields=["file"])
        asset.refresh_from_db()

        self.assertEqual(asset.storage_name, original_path)
        self.assertNotEqual(asset.storage_name, self.form_file.file.name)

    def test_same_physical_file_reuses_one_asset(self):
        first = self.make_asset()
        second, created = SharedFileAsset.get_or_create_for_form_file(self.form_file)
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SharedFileAsset.objects.count(), 1)

    def test_duplicate_storage_object_is_rejected_by_database(self):
        asset = self.make_asset()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedFileAsset.objects.create(
                    form_file=self.form_file, storage_backend=asset.storage_backend,
                    storage_name=asset.storage_name, original_name="duplicate.pdf",
                )

    def test_each_recipient_gets_an_independent_message(self):
        first = self.make_message(self.recipient_one)
        second = self.make_message(self.recipient_two)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(first.asset_id, second.asset_id)
        self.assertEqual(first.sender_id, second.sender_id)
        self.assertNotEqual(first.recipient_id, second.recipient_id)
        self.assertEqual(FileShareMessage.objects.count(), 2)

    def test_message_status_must_be_valid(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_message(self.recipient_one, status="UNKNOWN")

    def test_cancelled_message_requires_cancelled_at(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_message(self.recipient_one, status=FileShareMessage.Status.CANCELLED)

    def test_read_date_cannot_precede_sent_date(self):
        message = self.make_message(self.recipient_one, status=FileShareMessage.Status.READ)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FileShareMessage.objects.filter(pk=message.pk).update(
                    read_at=message.sent_at - timedelta(seconds=1)
                )

    def test_completed_timestamp_cannot_precede_sent_date(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_message(
                    self.recipient_one, status=FileShareMessage.Status.COMPLETED,
                    completed_at=timezone.now() - timedelta(days=1),
                )

    def test_terminal_message_cannot_be_reactivated_from_a_stale_instance(self):
        message = self.make_message(self.recipient_one)
        stale_instance = FileShareMessage.objects.get(pk=message.pk)

        message.status = FileShareMessage.Status.CANCELLED
        message.cancelled_at = timezone.now()
        message.save()

        stale_instance.status = FileShareMessage.Status.READ
        stale_instance.read_at = timezone.now()
        with self.assertRaises(ValidationError):
            stale_instance.save()

        message.refresh_from_db()
        self.assertEqual(message.status, FileShareMessage.Status.CANCELLED)

    def test_cleanup_pending_asset_rejects_new_messages_after_storage_cleanup(self):
        asset = self.make_asset()
        message = self.make_message(self.recipient_one)
        FormFile.objects.filter(pk=self.form_file.pk).delete()

        message.status = FileShareMessage.Status.CANCELLED
        message.cancelled_at = timezone.now()
        with self.captureOnCommitCallbacks(execute=True):
            message.save()

        asset.refresh_from_db()
        self.assertTrue(asset.cleanup_pending)
        self.assertIsNotNone(asset.storage_deleted_at)

        with self.assertRaises(ValidationError):
            self.make_message(self.recipient_two)

        with self.assertRaises(ValidationError):
            FileShareMessage.objects.create(
                asset=asset,
                sender=self.sender,
                recipient=self.recipient_two,
                workflow_instance=self.instance,
                workflow_step=self.step,
            )

    def test_failed_storage_cleanup_can_be_retried(self):
        asset = self.make_asset()
        FormFile.objects.filter(pk=self.form_file.pk).delete()

        with patch.object(default_storage, "delete", side_effect=[OSError("storage unavailable"), None]):
            with self.assertRaises(OSError):
                FileLifecycleService._delete_if_unreferenced(
                    storage=default_storage,
                    file_name=asset.storage_name,
                    storage_backend=asset.storage_backend,
                )

            asset.refresh_from_db()
            self.assertTrue(asset.cleanup_pending)
            self.assertIsNone(asset.storage_deleted_at)

            results = FileLifecycleService.retry_pending_asset_cleanups()
            self.assertEqual(results, [True])

        asset.refresh_from_db()
        self.assertIsNotNone(asset.storage_deleted_at)

    def test_message_service_records_each_valid_status_transition(self):
        message = self.make_message(self.recipient_one)

        message, read_event = FileShareMessageService.transition_status(
            message=message,
            to_status=FileShareMessage.Status.READ,
            actor=self.recipient_one,
            details={"source": "inbox"},
        )
        self.assertEqual(message.status, FileShareMessage.Status.READ)
        self.assertIsNotNone(message.read_at)
        self.assertEqual(read_event.event_type, FileShareMessageEvent.EventType.READ)

        message, response_event = FileShareMessageService.transition_status(
            message=message,
            to_status=FileShareMessage.Status.RESPONDED,
            actor=self.recipient_one,
        )
        self.assertEqual(message.status, FileShareMessage.Status.RESPONDED)
        self.assertIsNotNone(message.responded_at)
        self.assertEqual(response_event.event_type, FileShareMessageEvent.EventType.RESPONDED)

        message, completed_event = FileShareMessageService.transition_status(
            message=message,
            to_status=FileShareMessage.Status.COMPLETED,
            actor=self.recipient_one,
        )
        self.assertEqual(message.status, FileShareMessage.Status.COMPLETED)
        self.assertIsNotNone(message.completed_at)
        self.assertEqual(completed_event.event_type, FileShareMessageEvent.EventType.COMPLETED)
        self.assertEqual(message.events.count(), 3)

    def test_message_service_rejects_skipped_or_terminal_transitions(self):
        message = self.make_message(self.recipient_one)
        with self.assertRaises(ValidationError):
            FileShareMessageService.transition_status(
                message=message,
                to_status=FileShareMessage.Status.COMPLETED,
                actor=self.recipient_one,
            )

        FileShareMessageService.transition_status(
            message=message,
            to_status=FileShareMessage.Status.CANCELLED,
            actor=self.sender,
        )
        with self.assertRaises(ValidationError):
            FileShareMessageService.transition_status(
                message=message,
                to_status=FileShareMessage.Status.READ,
                actor=self.recipient_one,
            )

    def test_cancelled_message_and_its_events_are_preserved(self):
        message = self.make_message(self.recipient_one)
        cancelled_at = timezone.now()
        FileShareMessage.objects.filter(pk=message.pk).update(
            status=FileShareMessage.Status.CANCELLED,
            cancelled_at=cancelled_at,
        )
        message.refresh_from_db()
        event = FileShareMessageEvent.objects.create(
            message=message, event_type=FileShareMessageEvent.EventType.CANCELLED,
            actor=self.sender, details={"reason": "sender_cancelled"},
        )
        message.refresh_from_db()
        self.assertEqual(message.status, FileShareMessage.Status.CANCELLED)
        self.assertEqual(message.events.count(), 1)
        self.assertEqual(message.events.get().pk, event.pk)
        self.assertEqual(event.details["reason"], "sender_cancelled")
