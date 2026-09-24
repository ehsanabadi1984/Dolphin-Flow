from django.urls import reverse

from workflow.form_file_models import FormFile
from workflow.models import (
    FieldAccess,
    FormField,
    FormRepeatableGroup,
    RepeatableGroupAccess,
    RepeatableRow,
)
from workflow.tests.test_form_file_services import RepeatableFilePersistenceTests


class RepeatableFileFieldDefinitionContractTests(RepeatableFilePersistenceTests):
    def _create_row_with_file(self, *, row_order=0, name="contract.txt"):
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.group,
            row_order=row_order,
        )
        form_file = FormFile.objects.create(
            form_data=self.form_data,
            field=self.file_field,
            row_id=str(row.pk),
            file=self._upload(name),
            original_name=name,
            file_size=len(b"file-content"),
            content_type="text/plain",
            uploaded_by=self.user,
        )
        return row, form_file

    def test_repeatable_file_definition_exposes_ui_contract(self):
        row, form_file = self._create_row_with_file()

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
            if item["code"] == self.group.code
        )
        self.assertEqual(
            group_payload["fields"],
            [{
                "field_id": self.file_field.pk,
                "code": self.file_field.code,
                "label": self.file_field.label,
                "editable": True,
                "required": False,
                "column_index": 0,
            }],
        )
        self.assertFalse(group_payload["is_table"])

        self.assertEqual(
            group_payload["files"],
            [{
                "field_code": self.file_field.code,
                "row_id": str(row.pk),
                "row_index": 0,
                "input_name": (
                    f"{self.group.code}_0_{self.file_field.code}"
                ),
                "id": form_file.pk,
                "name": "contract.txt",
                "url": reverse(
                    "operator_panel:download_form_file",
                    args=[form_file.pk],
                ),
                "delete_url": reverse(
                    "operator_panel:delete_form_file",
                    args=[form_file.pk],
                ),
            }],
        )

    def test_repeatable_file_definition_preserves_field_edit_and_required_flags(self):
        self.file_field.is_required = True
        self.file_field.save(update_fields=["is_required"])

        FieldAccess.objects.filter(
            field=self.file_field,
            step=self.step,
            user=self.user,
        ).update(can_edit=False)

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
            if item["code"] == self.group.code
        )

        self.assertEqual(
            group_payload["fields"][0]["editable"],
            False,
        )
        self.assertEqual(
            group_payload["fields"][0]["required"],
            True,
        )

    def test_repeatable_file_definition_omits_file_group_when_field_is_not_viewable(self):
        FieldAccess.objects.filter(
            field=self.file_field,
            step=self.step,
            user=self.user,
        ).update(can_view=False)

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "operator_panel:file_field_definitions",
                args=[self.instance.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertFalse(
            any(
                item["code"] == self.group.code
                for item in payload["groups"]
            )
        )

    def test_repeatable_table_file_definition_uses_visible_column_index(self):
        self.file_field.order = 1
        self.file_field.save(update_fields=["order"])
        text_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="Name",
            code="name",
            label="Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )

        row, form_file = self._create_row_with_file(
            name="table-contract.txt",
        )

        self.group.display_type = FormRepeatableGroup.DisplayType.TABLE
        self.group.save(update_fields=["display_type"])

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
            if item["code"] == self.group.code
        )

        self.assertTrue(group_payload["is_table"])
        self.assertEqual(group_payload["fields"][0]["code"], self.file_field.code)
        self.assertEqual(group_payload["fields"][0]["column_index"], 1)
        self.assertEqual(group_payload["files"][0]["row_id"], str(row.pk))
        self.assertEqual(group_payload["files"][0]["input_name"], "items_file_0_attachment")
        self.assertEqual(group_payload["files"][0]["id"], form_file.pk)
        self.assertEqual(text_field.order, 0)
