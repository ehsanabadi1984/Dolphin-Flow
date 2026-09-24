from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from unittest.mock import patch

from workflow.form_draft_delete_apply_services import FormDraftDeleteApplyService
from workflow.form_file_models import FormFile
from workflow.form_draft_diff_services import FormDraftDiffService
from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    RepeatableRow,
    RepeatableRowValue,
    Workflow,
    WorkflowInstance,
)


class FormDraftDeleteApplyServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Delete Apply Workflow",
            code="DELETE_APPLY_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Delete Apply Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Delete Apply Section",
            code="DELETE_APPLY_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    def create_group(self, *, code, parent_group=None, group_type=FormRepeatableGroup.GroupType.NORMAL, order=1):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name=code.title(),
            code=code,
            group_type=group_type,
            order=order,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=f"{code}_name",
            code=f"{code}_name",
            label=f"{code}_name",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        return group, field

    @staticmethod
    def row(*, row_id=None, fields=None, child_groups=None):
        return NormalizedRow(
            row_id=row_id,
            fields=fields or {},
            child_groups=child_groups or {},
        )

    def build_diff(self, **groups):
        payload = NormalizedFormPayload(
            normal_fields={},
            repeatable_groups={code: tuple(rows) for code, rows in groups.items()},
        )
        return FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )

    def test_delete_removes_row_values_and_file_sidecars(self):
        group, field = self.create_group(code="items")
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=field,
            text_value="Delete me",
        )
        from workflow.models import FormData
        form_data = FormData.objects.create(
            instance=self.instance,
            data={},
        )
        file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="attachment",
            code="attachment",
            label="Attachment",
            field_type=FormField.FieldType.FILE,
            order=1,
        )
        form_file = FormFile.objects.create(
            form_data=form_data,
            field=file_field,
            row_id=str(row.pk),
            file=SimpleUploadedFile(
                "delete.txt",
                b"file-content",
                content_type="text/plain",
            ),
            original_name="delete.txt",
        )

        storage = form_file.file.storage
        file_name = form_file.file.name
        with patch.object(storage, "delete") as storage_delete:
            with self.captureOnCommitCallbacks(execute=True):
                deleted = FormDraftDeleteApplyService.apply(
                    instance=self.instance,
                    diff=self.build_diff(items=[]),
                )

        self.assertEqual(deleted, (row.pk,))
        self.assertFalse(RepeatableRow.objects.filter(pk=row.pk).exists())
        self.assertFalse(RepeatableRowValue.objects.filter(row_id=row.pk).exists())
        self.assertFalse(FormFile.objects.filter(pk=form_file.pk).exists())
        storage_delete.assert_called_once_with(file_name)
        form_file.file.delete(save=False)

    def test_delete_removes_row_and_values(self):
        group, field = self.create_group(code="items")
        row = RepeatableRow.objects.create(instance=self.instance, group=group, row_order=0)
        RepeatableRowValue.objects.create(row=row, field=field, text_value="Delete me")

        deleted = FormDraftDeleteApplyService.apply(
            instance=self.instance,
            diff=self.build_diff(items=[]),
        )

        self.assertEqual(deleted, (row.pk,))
        self.assertFalse(RepeatableRow.objects.filter(pk=row.pk).exists())
        self.assertFalse(RepeatableRowValue.objects.filter(row_id=row.pk).exists())

    def test_nested_delete_is_bottom_up(self):
        parent_group, parent_field = self.create_group(code="parents", order=1)
        child_group, child_field = self.create_group(
            code="children", parent_group=parent_group, order=2
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance, group=parent_group, row_order=0
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance, group=child_group,
            parent_row=parent_row, row_order=0
        )
        RepeatableRowValue.objects.create(row=parent_row, field=parent_field, text_value="Parent")
        RepeatableRowValue.objects.create(row=child_row, field=child_field, text_value="Child")

        deleted = FormDraftDeleteApplyService.apply(
            instance=self.instance,
            diff=self.build_diff(parents=[]),
        )

        self.assertEqual(deleted, (child_row.pk, parent_row.pk))
        self.assertFalse(
            RepeatableRow.objects.filter(pk__in=[parent_row.pk, child_row.pk]).exists()
        )

    def test_delete_preserves_rows_not_in_deleted_set(self):
        group, field = self.create_group(code="items")
        first = RepeatableRow.objects.create(instance=self.instance, group=group, row_order=0)
        second = RepeatableRow.objects.create(instance=self.instance, group=group, row_order=1)
        RepeatableRowValue.objects.create(row=second, field=field, text_value="Keep")

        FormDraftDeleteApplyService.apply(
            instance=self.instance,
            diff=self.build_diff(
                items=[self.row(row_id=second.pk, fields={})],
            ),
        )

        self.assertFalse(RepeatableRow.objects.filter(pk=first.pk).exists())
        self.assertTrue(RepeatableRow.objects.filter(pk=second.pk).exists())

    def test_delete_row_tree_removes_device_row_tree_and_preserves_device_assignment(self):
        parent_group, parent_field = self.create_group(
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=1,
        )
        child_group, child_field = self.create_group(
            code="device_children",
            parent_group=parent_group,
            order=2,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            draft_imei="TREE-DRAFT-IMEI",
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
            row_order=0,
            instance_device=instance_device,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=parent_row,
            field=parent_field,
            text_value="Parent",
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=child_field,
            text_value="Child",
        )

        deleted = FormDraftDeleteApplyService.delete_row_tree(
            instance=self.instance,
            row_id=parent_row.pk,
        )

        self.assertEqual(deleted, (child_row.pk, parent_row.pk))
        self.assertFalse(
            RepeatableRow.objects.filter(
                pk__in=[parent_row.pk, child_row.pk],
            ).exists()
        )
        self.assertFalse(
            RepeatableRowValue.objects.filter(
                row_id__in=[parent_row.pk, child_row.pk],
            ).exists()
        )
        self.assertTrue(
            InstanceDevice.objects.filter(
                pk=instance_device.pk,
                draft_imei="TREE-DRAFT-IMEI",
                is_active=False,
            ).exists()
        )

    def test_device_delete_removes_row_and_preserves_instance_device(self):
        group, field = self.create_group(
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            draft_imei="DRAFT-IMEI",
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
            instance_device=instance_device,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=field,
            text_value="Delete device row",
        )

        deleted = FormDraftDeleteApplyService.apply(
            instance=self.instance,
            diff=self.build_diff(devices=[]),
        )

        self.assertEqual(deleted, (row.pk,))
        self.assertFalse(RepeatableRow.objects.filter(pk=row.pk).exists())
        self.assertFalse(RepeatableRowValue.objects.filter(row_id=row.pk).exists())
        self.assertTrue(
            InstanceDevice.objects.filter(
                pk=instance_device.pk,
                is_active=False,
            ).exists()
        )
        self.assertTrue(
            InstanceDevice.objects.filter(
                pk=instance_device.pk,
                draft_imei="DRAFT-IMEI",
            ).exists()
        )

    def test_failed_delete_rolls_back_previous_deletes(self):
        group, field = self.create_group(code="items")
        first = RepeatableRow.objects.create(instance=self.instance, group=group, row_order=0)
        second = RepeatableRow.objects.create(instance=self.instance, group=group, row_order=1)
        RepeatableRowValue.objects.create(row=first, field=field, text_value="First")
        RepeatableRowValue.objects.create(row=second, field=field, text_value="Second")

        diff = self.build_diff(items=[])
        with patch(
            "workflow.form_draft_delete_apply_services.FormDraftDeleteApplyService._delete_row",
            side_effect=[None, ValidationError("forced failure")],
        ):
            with self.assertRaises(ValidationError):
                FormDraftDeleteApplyService.apply(instance=self.instance, diff=diff)

        self.assertTrue(RepeatableRow.objects.filter(pk=first.pk).exists())
        self.assertTrue(RepeatableRow.objects.filter(pk=second.pk).exists())

