from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from workflow.form_file_models import FormFile
from workflow.form_file_services import validate_uploaded_files
from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
)


User = get_user_model()


class FormFilePermissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="form-file-permission-user",
            password="password",
        )
        self.workflow = Workflow.objects.create(
            name="Form File Workflow",
            code="FORM_FILE_PERMISSION_WF",
            is_active=True,
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="File Step",
            code="FORM_FILE_PERMISSION_STEP",
            order=1,
            is_active=True,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="File Form",
            is_active=True,
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="File Section",
            code="FORM_FILE_SECTION",
            order=1,
            is_active=True,
        )
        self.normal_file = FormField.objects.create(
            section=self.section,
            name="Attachment",
            code="attachment",
            label="Attachment",
            field_type=FormField.FieldType.FILE,
            is_active=True,
        )
        self.group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Attachments",
            code="attachments",
            order=1,
            is_active=True,
        )
        self.repeatable_file = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="Row Attachment",
            code="row_attachment",
            label="Row Attachment",
            field_type=FormField.FieldType.FILE,
            order=0,
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        FieldAccess.objects.create(
            field=self.normal_file,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
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
            field=self.repeatable_file,
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
        self.form_data = FormData.objects.create(
            instance=self.instance,
            data={
                self.group.code: [
                    {"_id": "row-1", self.repeatable_file.code: ""},
                ],
            },
        )
        self.normal_file_record = FormFile.objects.create(
            form_data=self.form_data,
            field=self.normal_file,
            row_id="",
            file=SimpleUploadedFile("normal.txt", b"normal"),
            original_name="normal.txt",
            file_size=6,
            content_type="text/plain",
            uploaded_by=self.user,
        )
        self.repeatable_file_record = FormFile.objects.create(
            form_data=self.form_data,
            field=self.repeatable_file,
            row_id="row-1",
            file=SimpleUploadedFile("row.txt", b"row"),
            original_name="row.txt",
            file_size=3,
            content_type="text/plain",
            uploaded_by=self.user,
        )
        self.client.force_login(self.user)

    def _upload(self, name="new.txt"):
        return SimpleUploadedFile(name, b"new file", content_type="text/plain")

    def test_normal_file_without_view_permission_is_hidden_and_download_denied(self):
        FieldAccess.objects.filter(
            field=self.normal_file,
            step=self.step,
            user=self.user,
        ).update(can_view=False)

        response = self.client.get(
            reverse(
                "operator_panel:file_field_definitions",
                args=[self.instance.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fields"], [])

        response = self.client.get(
            reverse(
                "operator_panel:download_form_file",
                args=[self.normal_file_record.pk],
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_normal_file_without_edit_permission_cannot_upload(self):
        FieldAccess.objects.filter(
            field=self.normal_file,
            step=self.step,
            user=self.user,
        ).update(can_edit=False)

        with self.assertRaises(ValidationError):
            validate_uploaded_files(
                instance=self.instance,
                user=self.user,
                submitted_data={},
                submitted_files={"attachment": self._upload()},
            )

    def test_normal_file_without_edit_permission_cannot_delete(self):
        FieldAccess.objects.filter(
            field=self.normal_file,
            step=self.step,
            user=self.user,
        ).update(can_edit=False)

        response = self.client.post(
            reverse(
                "operator_panel:delete_form_file",
                args=[self.normal_file_record.pk],
            )
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            FormFile.objects.filter(pk=self.normal_file_record.pk).exists()
        )

    def test_repeatable_group_without_view_permission_is_hidden(self):
        RepeatableGroupAccess.objects.filter(
            group=self.group,
            step=self.step,
            user=self.user,
        ).update(can_view=False)

        response = self.client.get(
            reverse(
                "operator_panel:file_field_definitions",
                args=[self.instance.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["groups"], [])

    def test_repeatable_field_without_view_permission_is_hidden(self):
        FieldAccess.objects.filter(
            field=self.repeatable_file,
            step=self.step,
            user=self.user,
        ).update(can_view=False)

        response = self.client.get(
            reverse(
                "operator_panel:file_field_definitions",
                args=[self.instance.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        groups = response.json()["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["fields"], [])

    def test_repeatable_group_without_edit_permission_cannot_upload_or_delete(self):
        RepeatableGroupAccess.objects.filter(
            group=self.group,
            step=self.step,
            user=self.user,
        ).update(can_edit=False)

        with self.assertRaises(ValidationError):
            validate_uploaded_files(
                instance=self.instance,
                user=self.user,
                submitted_data={
                    self.group.code: [
                        {"row_id": "row-1"},
                    ],
                },
                submitted_files={
                    f"{self.group.code}_0_{self.repeatable_file.code}": self._upload(),
                },
            )

        response = self.client.post(
            reverse(
                "operator_panel:delete_form_file",
                args=[self.repeatable_file_record.pk],
            )
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            FormFile.objects.filter(pk=self.repeatable_file_record.pk).exists()
        )

    def test_repeatable_field_without_edit_permission_cannot_upload_or_delete(self):
        FieldAccess.objects.filter(
            field=self.repeatable_file,
            step=self.step,
            user=self.user,
        ).update(can_edit=False)

        with self.assertRaises(ValidationError):
            validate_uploaded_files(
                instance=self.instance,
                user=self.user,
                submitted_data={
                    self.group.code: [
                        {"row_id": "row-1"},
                    ],
                },
                submitted_files={
                    f"{self.group.code}_0_{self.repeatable_file.code}": self._upload(),
                },
            )

        response = self.client.post(
            reverse(
                "operator_panel:delete_form_file",
                args=[self.repeatable_file_record.pk],
            )
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            FormFile.objects.filter(pk=self.repeatable_file_record.pk).exists()
        )

    def test_repeatable_group_and_field_permissions_control_editable_state(self):
        response = self.client.get(
            reverse(
                "operator_panel:file_field_definitions",
                args=[self.instance.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        group = response.json()["groups"][0]
        self.assertTrue(group["fields"][0]["editable"])

        RepeatableGroupAccess.objects.filter(
            group=self.group,
            step=self.step,
            user=self.user,
        ).update(can_edit=False)

        response = self.client.get(
            reverse(
                "operator_panel:file_field_definitions",
                args=[self.instance.pk],
            )
        )
        self.assertFalse(response.json()["groups"][0]["fields"][0]["editable"])
