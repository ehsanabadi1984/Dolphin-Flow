from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from workflow.form_draft_save_services import FormDraftSaveService
from workflow.form_file_models import FormFile
from workflow.form_file_services import save_uploaded_form_files
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
                "items_file_0_child_items_file_child_attachment": self._upload("nested.txt"),
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
