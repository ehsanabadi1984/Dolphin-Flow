from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase
from unittest.mock import patch
from django.urls import reverse

from workflow.form_draft_save_services import FormDraftSaveService
from workflow.form_file_models import FormFile
from workflow.form_file_services import _replace_file, save_uploaded_form_files
import workflow.form_file_services as form_file_services
from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableGroupAccess,
    RepeatableRow,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)
from django.contrib.auth import get_user_model


class RepeatableFilePersistenceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="repeatable-file-user",
            password="password",
        )
        self.workflow = Workflow.objects.create(
            name="Repeatable File Workflow",
            code="REPEATABLE_FILE_WF",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="File Step",
            code="FILE_STEP",
            order=1,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="File Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="File Section",
            code="FILE_SECTION",
            order=1,
        )
        self.group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items_file",
            order=1,
        )
        self.file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="Attachment",
            code="attachment",
            label="Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
        )
        RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        FieldAccess.objects.create(
            field=self.file_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
        )
        WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
        )
        self.form_data = FormData.objects.create(
            instance=self.instance,
            data={},
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

    def _save(self, submitted_data):
        return FormDraftSaveService.save(
            instance=self.instance,
            step=self.step,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
        )

    def _upload(self, name):
        return SimpleUploadedFile(
            name,
            b"file-content",
            content_type="text/plain",
        )

    def test_existing_unchanged_repeatable_row_uses_canonical_row_pk(self):
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.group,
            row_order=0,
        )

        result = self._save(
            submitted_data={
                "items_file": [
                    {
                        "row_id": row.pk,
                    },
                ],
            },
        )

        save_uploaded_form_files(
            instance=self.instance,
            user=self.user,
            submitted_files={
                "items_file_0_attachment": self._upload("existing.txt"),
            },
            save_result=result,
        )

        form_file = FormFile.objects.get(
            form_data=self.form_data,
            field=self.file_field,
        )
        self.assertEqual(form_file.row_id, str(row.pk))
        self.assertNotEqual(form_file.row_id, "")

    def test_new_repeatable_row_uses_created_row_pk(self):
        result = self._save(
            submitted_data={
                "items_file": [
                    {},
                ],
            },
        )

        row = RepeatableRow.objects.get(
            instance=self.instance,
            group=self.group,
        )

        save_uploaded_form_files(
            instance=self.instance,
            user=self.user,
            submitted_files={
                "items_file_0_attachment": self._upload("new.txt"),
            },
            save_result=result,
        )

        form_file = FormFile.objects.get(
            form_data=self.form_data,
            field=self.file_field,
        )
        self.assertEqual(form_file.row_id, str(row.pk))

    def test_new_nested_repeatable_row_uses_child_row_pk_for_file(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Items",
            code="child_items_file",
            order=2,
        )
        child_file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Attachment",
            code="child_attachment",
            label="Child Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        FieldAccess.objects.create(
            field=child_file_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        result = self._save(
            submitted_data={
                "items_file": [
                    {
                        "child_items_file": [
                            {},
                        ],
                    },
                ],
            },
        )

        parent_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=self.group,
        )
        child_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
        )

        save_uploaded_form_files(
            instance=self.instance,
            user=self.user,
            submitted_files={
                "items_file_0_child_items_file_0_child_attachment": self._upload("nested.txt"),
            },
            save_result=result,
        )

        form_file = FormFile.objects.get(
            form_data=self.form_data,
            field=child_file_field,
        )
        self.assertEqual(form_file.row_id, str(child_row.pk))
        self.assertNotEqual(form_file.row_id, str(parent_row.pk))


    def test_nested_files_resolve_child_row_pk_across_multiple_parent_rows(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Items",
            code="child_items_file_multi",
            order=2,
        )
        child_file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Attachment",
            code="child_attachment",
            label="Child Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        FieldAccess.objects.create(
            field=child_file_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        result = self._save(
            submitted_data={
                "items_file": [
                    {
                        "child_items_file_multi": [{}, {}],
                    },
                    {
                        "child_items_file_multi": [{}, {}],
                    },
                ],
            },
        )

        parent_rows = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=self.group,
                parent_row__isnull=True,
            ).order_by("row_order", "pk")
        )
        self.assertEqual(len(parent_rows), 2)

        child_rows = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=child_group,
            ).order_by("parent_row_id", "row_order", "pk")
        )
        self.assertEqual(len(child_rows), 4)

        save_uploaded_form_files(
            instance=self.instance,
            user=self.user,
            submitted_files={
                "items_file_0_child_items_file_multi_0_child_attachment": self._upload("nested-0-0.txt"),
                "items_file_0_child_items_file_multi_1_child_attachment": self._upload("nested-0-1.txt"),
                "items_file_1_child_items_file_multi_0_child_attachment": self._upload("nested-1-0.txt"),
                "items_file_1_child_items_file_multi_1_child_attachment": self._upload("nested-1-1.txt"),
            },
            save_result=result,
        )

        files = list(
            FormFile.objects.filter(
                form_data=self.form_data,
                field=child_file_field,
            ).order_by("row_id")
        )
        self.assertEqual(len(files), 4)
        self.assertEqual(
            {item.row_id for item in files},
            {str(row.pk) for row in child_rows},
        )
        self.assertTrue(
            {str(row.pk) for row in child_rows}.isdisjoint(
                {str(row.pk) for row in parent_rows}
            )
        )


    def test_nested_files_use_parent_context_in_http_field_names(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Items",
            code="child_items_file_context",
            order=2,
        )
        child_file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Attachment",
            code="child_attachment",
            label="Child Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        FieldAccess.objects.create(
            field=child_file_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        result = self._save(
            submitted_data={
                "items_file": [
                    {"child_items_file_context": [{}]},
                    {"child_items_file_context": [{}]},
                ],
            },
        )

        parent_rows = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=self.group,
                parent_row__isnull=True,
            ).order_by("row_order", "pk")
        )
        child_rows = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=child_group,
            ).order_by("parent_row_id", "row_order", "pk")
        )
        self.assertEqual(len(parent_rows), 2)
        self.assertEqual(len(child_rows), 2)
        self.assertEqual(
            [row.parent_row_id for row in child_rows],
            [row.pk for row in parent_rows],
        )

        save_uploaded_form_files(
            instance=self.instance,
            user=self.user,
            submitted_files={
                "items_file_0_child_items_file_context_0_child_attachment":
                    self._upload("parent-0-child.txt"),
                "items_file_1_child_items_file_context_0_child_attachment":
                    self._upload("parent-1-child.txt"),
            },
            save_result=result,
        )

        files = list(
            FormFile.objects.filter(
                form_data=self.form_data,
                field=child_file_field,
            ).order_by("row_id")
        )

        self.assertEqual(len(files), 2)
        self.assertEqual(
            {item.row_id for item in files},
            {str(row.pk) for row in child_rows},
        )
        self.assertEqual(
            {
                item.row_id: item.original_name
                for item in files
            },
            {
                str(child_rows[0].pk): "parent-0-child.txt",
                str(child_rows[1].pk): "parent-1-child.txt",
            },
        )


    def test_new_grandchild_repeatable_row_uses_grandchild_row_pk_for_file(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Items",
            code="child_items_file_grandchild",
            order=2,
        )
        grandchild_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=child_group,
            name="Grandchild Items",
            code="grandchild_items_file",
            order=3,
        )
        grandchild_file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=grandchild_group,
            name="Grandchild Attachment",
            code="grandchild_attachment",
            label="Grandchild Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
        )
        for group in (child_group, grandchild_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )
        FieldAccess.objects.create(
            field=grandchild_file_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        result = self._save(
            submitted_data={
                "items_file": [
                    {
                        "child_items_file_grandchild": [
                            {
                                "grandchild_items_file": [
                                    {},
                                ],
                            },
                        ],
                    },
                ],
            },
        )

        parent_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=self.group,
            parent_row__isnull=True,
        )
        child_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
        )
        grandchild_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=grandchild_group,
            parent_row=child_row,
        )

        save_uploaded_form_files(
            instance=self.instance,
            user=self.user,
            submitted_files={
                (
                    "items_file_0_child_items_file_grandchild_0_"
                    "grandchild_items_file_0_grandchild_attachment"
                ): self._upload("grandchild.txt"),
            },
            save_result=result,
        )

        form_file = FormFile.objects.get(
            form_data=self.form_data,
            field=grandchild_file_field,
        )
        self.assertEqual(form_file.row_id, str(grandchild_row.pk))
        self.assertNotEqual(form_file.row_id, str(child_row.pk))
        self.assertNotEqual(form_file.row_id, str(parent_row.pk))


class NestedRepeatableFileValidationTests(RepeatableFilePersistenceTests):
    def _create_nested_required_file_field(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Items",
            code="child_items_file_validation",
            order=2,
        )
        grandchild_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=child_group,
            name="Grandchild Items",
            code="grandchild_items_file_validation",
            order=3,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=grandchild_group,
            name="Grandchild Attachment",
            code="grandchild_attachment",
            label="Grandchild Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=True,
        )
        for group in (child_group, grandchild_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        return child_group, grandchild_group, field

    def _nested_submitted_data(self):
        return {
            "items_file_0__id": "",
            "items_file_0_child_items_file_validation_0__id": "",
            "items_file_0_child_items_file_validation_0_grandchild_items_file_validation_0__id": "",
        }

    def test_nested_required_file_accepts_canonical_upload_path(self):
        _, grandchild_group, field = self._create_nested_required_file_field()

        form_file_services.validate_uploaded_files(
            instance=self.instance,
            user=self.user,
            submitted_data=self._nested_submitted_data(),
            submitted_files={
                (
                    "items_file_0_child_items_file_validation_0_"
                    "grandchild_items_file_validation_0_grandchild_attachment"
                ): self._upload("nested-validation.txt"),
            },
        )

        self.assertEqual(field.repeatable_group_id, grandchild_group.pk)

    def test_nested_required_file_reports_missing_canonical_upload(self):
        _, grandchild_group, field = self._create_nested_required_file_field()

        with self.assertRaises(ValidationError) as raised:
            form_file_services.validate_uploaded_files(
                instance=self.instance,
                user=self.user,
                submitted_data=self._nested_submitted_data(),
                submitted_files={},
            )

        errors = raised.exception.validation_errors
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["group_code"], grandchild_group.code)
        self.assertEqual(errors[0]["field_code"], field.code)
        self.assertEqual(errors[0]["item_index"], 0)



class DirectFormFileDeletionTests(RepeatableFilePersistenceTests):
    def _create_form_file(self, name="direct-delete.txt"):
        return FormFile.objects.create(
            form_data=self.form_data,
            field=self.file_field,
            row_id="direct-delete-row",
            file=self._upload(name),
            original_name=name,
            file_size=len(b"file-content"),
            content_type="text/plain",
            uploaded_by=self.user,
        )

    def test_delete_endpoint_removes_storage_after_transaction_commit(self):
        form_file = self._create_form_file()
        file_name = form_file.file.name

        self.client.force_login(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse(
                    "operator_panel:delete_form_file",
                    args=[form_file.pk],
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(FormFile.objects.filter(pk=form_file.pk).exists())
        self.assertFalse(default_storage.exists(file_name))

    def test_delete_endpoint_keeps_storage_when_database_delete_rolls_back(self):
        form_file = self._create_form_file("direct-delete-rollback.txt")
        file_name = form_file.file.name

        self.client.force_login(self.user)
        with patch.object(
            FormFile,
            "delete",
            autospec=True,
            side_effect=RuntimeError("forced delete failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse(
                        "operator_panel:delete_form_file",
                        args=[form_file.pk],
                    )
                )

        self.assertTrue(FormFile.objects.filter(pk=form_file.pk).exists())
        self.assertTrue(default_storage.exists(file_name))

class FormFileRowLifecycleTests(RepeatableFilePersistenceTests):
    def test_delete_for_row_deletes_storage_after_transaction_commit(self):
        form_file = FormFile.objects.create(
            form_data=self.form_data,
            field=self.file_field,
            row_id="row-1",
            file=self._upload("row-delete.txt"),
            original_name="row-delete.txt",
            file_size=len(b"file-content"),
            content_type="text/plain",
            uploaded_by=self.user,
        )

        file_name = form_file.file.name
        self.assertTrue(default_storage.exists(file_name))

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            FormFile.delete_for_row(
                form_data=self.form_data,
                row_id="row-1",
            )

        self.assertEqual(len(callbacks), 1)
        self.assertFalse(FormFile.objects.filter(pk=form_file.pk).exists())
        self.assertFalse(default_storage.exists(file_name))

    def test_create_file_persists_storage_on_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            _replace_file(
                form_data=self.form_data,
                field=self.file_field,
                row_id="create-1",
                upload=self._upload("create-success.txt"),
                user=self.user,
            )

        form_file = FormFile.objects.get(
            form_data=self.form_data,
            field=self.file_field,
            row_id="create-1",
        )
        self.assertTrue(default_storage.exists(form_file.file.name))

    def test_batch_file_failure_cleans_previous_storage_writes(self):
        first_field = FormField.objects.create(
            section=self.section,
            name="First Attachment",
            code="first_attachment",
            label="First Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
            order=3,
        )
        second_field = FormField.objects.create(
            section=self.section,
            name="Second Attachment",
            code="second_attachment",
            label="Second Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
            order=4,
        )

        original_replace = form_file_services._replace_file
        call_count = {"value": 0}
        stored_names = []

        def replace_then_fail(*args, **kwargs):
            call_count["value"] += 1
            original_replace(*args, **kwargs)
            form_file = FormFile.objects.order_by("-pk").first()
            if form_file and form_file.file:
                stored_names.append(form_file.file.name)
            if call_count["value"] == 2:
                raise RuntimeError("forced batch failure")

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                with patch.object(
                    form_file_services,
                    "_replace_file",
                    side_effect=replace_then_fail,
                ):
                    save_uploaded_form_files(
                        instance=self.instance,
                        user=self.user,
                        submitted_files={
                            "first_attachment": self._upload("batch-first.txt"),
                            "second_attachment": self._upload("batch-second.txt"),
                        },
                    )

        self.assertFalse(
            FormFile.objects.filter(
                form_data=self.form_data,
                field__in=[first_field, second_field],
            ).exists()
        )
        self.assertEqual(len(stored_names), 2)
        for file_name in stored_names:
            self.assertFalse(default_storage.exists(file_name))

    def test_create_file_cleans_storage_when_save_fails(self):
        original_save = FormFile.save
        created_name = {}

        def save_then_fail(instance, *args, **kwargs):
            original_save(instance, *args, **kwargs)
            created_name["name"] = instance.file.name
            raise RuntimeError("forced file save failure")

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                with patch.object(FormFile, "save", autospec=True, side_effect=save_then_fail):
                    _replace_file(
                        form_data=self.form_data,
                        field=self.file_field,
                        row_id="create-fail",
                        upload=self._upload("create-fail.txt"),
                        user=self.user,
                    )

        self.assertFalse(
            FormFile.objects.filter(
                form_data=self.form_data,
                field=self.file_field,
                row_id="create-fail",
            ).exists()
        )
        self.assertFalse(default_storage.exists(created_name["name"]))

    def test_replace_file_keeps_old_storage_until_commit(self):
        old = FormFile.objects.create(
            form_data=self.form_data,
            field=self.file_field,
            row_id="replace-1",
            file=self._upload("replace-old.txt"),
            original_name="replace-old.txt",
            file_size=len(b"file-content"),
            content_type="text/plain",
            uploaded_by=self.user,
        )
        old_name = old.file.name

        with self.captureOnCommitCallbacks(execute=True):
            _replace_file(
                form_data=self.form_data,
                field=self.file_field,
                row_id="replace-1",
                upload=self._upload("replace-new.txt"),
                user=self.user,
            )

        old.refresh_from_db()
        self.assertTrue(default_storage.exists(old.file.name))
        self.assertFalse(default_storage.exists(old_name))
        self.assertEqual(old.original_name, "replace-new.txt")

    def test_replace_file_cleans_new_storage_when_save_fails(self):
        old = FormFile.objects.create(
            form_data=self.form_data,
            field=self.file_field,
            row_id="replace-fail",
            file=self._upload("replace-old-fail.txt"),
            original_name="replace-old-fail.txt",
            file_size=len(b"file-content"),
            content_type="text/plain",
            uploaded_by=self.user,
        )
        old_name = old.file.name
        original_save = FormFile.save
        new_name = {}

        def save_then_fail(instance, *args, **kwargs):
            original_save(instance, *args, **kwargs)
            new_name["name"] = instance.file.name
            raise RuntimeError("forced replace save failure")

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                with patch.object(FormFile, "save", autospec=True, side_effect=save_then_fail):
                    _replace_file(
                        form_data=self.form_data,
                        field=self.file_field,
                        row_id="replace-fail",
                        upload=self._upload("replace-new-fail.txt"),
                        user=self.user,
                    )

        old.refresh_from_db()
        self.assertEqual(old.file.name, old_name)
        self.assertTrue(default_storage.exists(old_name))
        self.assertFalse(default_storage.exists(new_name["name"]))

    def test_delete_for_row_does_not_delete_storage_on_transaction_rollback(self):
        form_file = FormFile.objects.create(
            form_data=self.form_data,
            field=self.file_field,
            row_id="row-rollback",
            file=self._upload("row-rollback.txt"),
            original_name="row-rollback.txt",
            file_size=len(b"file-content"),
            content_type="text/plain",
            uploaded_by=self.user,
        )

        file_name = form_file.file.name
        self.assertTrue(default_storage.exists(file_name))

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                FormFile.delete_for_row(
                    form_data=self.form_data,
                    row_id="row-rollback",
                )
                raise RuntimeError("rollback")

        self.assertTrue(FormFile.objects.filter(pk=form_file.pk).exists())
        self.assertTrue(default_storage.exists(file_name))


class FileFieldDefinitionsNestedRowTests(RepeatableFilePersistenceTests):
    def test_nested_file_definition_uses_canonical_child_row_index(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Items",
            code="child_items_file_definitions",
            order=2,
        )
        child_file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Attachment",
            code="child_attachment",
            label="Child Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        FieldAccess.objects.create(
            field=child_file_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.group,
            row_order=0,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
            row_order=0,
        )
        FormFile.objects.create(
            form_data=self.form_data,
            field=child_file_field,
            row_id=str(child_row.pk),
            file=self._upload("nested-definition.txt"),
            original_name="nested-definition.txt",
            file_size=len(b"file-content"),
            content_type="text/plain",
            uploaded_by=self.user,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "operator_panel:file_field_definitions",
                args=[self.instance.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        group_payload = next(
            item for item in payload["groups"]
            if item["code"] == child_group.code
        )
        self.assertEqual(len(group_payload["files"]), 1)
        self.assertEqual(
            group_payload["files"][0]["row_id"],
            str(child_row.pk),
        )
        self.assertEqual(group_payload["files"][0]["row_index"], 0)


    def test_nested_file_definition_uses_full_canonical_input_name(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Items",
            code="child_items_file_path",
            order=2,
        )
        grandchild_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=child_group,
            name="Grandchild Items",
            code="grandchild_items_file_path",
            order=3,
        )
        grandchild_file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=grandchild_group,
            name="Grandchild Attachment",
            code="grandchild_attachment",
            label="Grandchild Attachment",
            field_type=FormField.FieldType.FILE,
            is_required=False,
        )
        for group in (child_group, grandchild_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )
        FieldAccess.objects.create(
            field=grandchild_file_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        parent_rows = [
            RepeatableRow.objects.create(
                instance=self.instance,
                group=self.group,
                row_order=index,
            )
            for index in range(2)
        ]
        child_rows = [
            RepeatableRow.objects.create(
                instance=self.instance,
                group=child_group,
                parent_row=parent_rows[0],
                row_order=index,
            )
            for index in range(2)
        ]
        grandchild_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=grandchild_group,
            parent_row=child_rows[1],
            row_order=0,
        )
        FormFile.objects.create(
            form_data=self.form_data,
            field=grandchild_file_field,
            row_id=str(grandchild_row.pk),
            file=self._upload("grandchild-definition.txt"),
            original_name="grandchild-definition.txt",
            file_size=len(b"file-content"),
            content_type="text/plain",
            uploaded_by=self.user,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "operator_panel:file_field_definitions",
                args=[self.instance.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        group_payload = next(
            item for item in payload["groups"]
            if item["code"] == grandchild_group.code
        )
        self.assertEqual(len(group_payload["files"]), 1)
        file_payload = group_payload["files"][0]
        self.assertEqual(file_payload["row_id"], str(grandchild_row.pk))
        self.assertEqual(file_payload["row_index"], 0)
        self.assertEqual(
            file_payload["input_name"],
            (
                "items_file_0_"
                "child_items_file_path_1_"
                "grandchild_items_file_path_0_"
                "grandchild_attachment"
            ),
        )
