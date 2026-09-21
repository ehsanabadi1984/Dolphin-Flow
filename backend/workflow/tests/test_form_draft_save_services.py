from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from unittest.mock import patch

from workflow.form_draft_diff_services import RowChangeAction
from workflow.form_draft_save_services import (
    FormDraftSaveResult,
    FormDraftSaveService,
)
from workflow.models import (
    DeviceModel,
    DeviceType,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    FieldAccess,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowStep,
    WorkflowStepExecution,
    InstanceDevice,
    RepeatableRow,
)


class FormDraftSaveServiceContractTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="draft-save-user",
            password="password",
        )
        self.workflow = Workflow.objects.create(
            name="Draft Save Workflow",
            code="DRAFT_SAVE_WF",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Draft Step",
            code="DRAFT_STEP",
            order=1,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Draft Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Draft Section",
            code="DRAFT_SECTION",
            order=1,
        )
        self.form_field = FormField.objects.create(
            section=self.section,
            name="Customer Name",
            code="customer_name",
            label="Customer Name",
            field_type=FormField.FieldType.TEXT,
        )
        FormSection.objects.create(
            form=self.form,
            name="Draft Section 2",
            code="DRAFT_SECTION_2",
            order=2,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
        )
        self.execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
        )

    def call(self, **overrides):
        params = {
            "instance": self.instance,
            "step": self.step,
            "user": self.user,
            "submitted_data": {},
            "edit_mode": True,
        }
        params.update(overrides)
        return FormDraftSaveService.save(**params)


    def grant_repeatable_write_permissions(self, group, field):
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

    def test_valid_context_builds_permission_snapshot(self):
        result = self.call(
            submitted_data={"customer_name": "Ehsan"},
        )

        self.assertIsInstance(result, FormDraftSaveResult)
        self.assertTrue(result.saved)
        self.assertTrue(result.is_draft)
        self.assertIsNotNone(result.permission_context)
        self.assertEqual(
            result.normalized_payload.normal_fields,
            {"customer_name": "Ehsan"},
        )
        self.assertEqual(result.diff.groups, ())

    def test_save_builds_repeatable_diff(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Item Name",
            code="item_name",
            label="Item Name",
            field_type=FormField.FieldType.TEXT,
        )
        self.grant_repeatable_write_permissions(group, field)
        existing_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        deleted_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=1,
        )

        result = self.call(
            submitted_data={
                "items": [
                    {
                        "row_id": existing_row.pk,
                        "item_name": "Updated",
                    },
                    {
                        "row_id": None,
                        "item_name": "New",
                    },
                ],
            },
        )

        self.assertEqual(len(result.diff.groups), 1)
        changes = result.diff.groups[0].changes
        self.assertEqual(
            [change.action for change in changes],
            [
                RowChangeAction.UPDATE,
                RowChangeAction.CREATE,
                RowChangeAction.DELETE,
            ],
        )
        self.assertEqual(changes[0].row_id, existing_row.pk)
        self.assertIsNone(changes[1].row_id)
        self.assertEqual(changes[2].row_id, deleted_row.pk)

        self.assertEqual(
            result.diff.groups[0].group.pk,
            group.pk,
        )

        self.assertTrue(RepeatableRow.objects.filter(pk=existing_row.pk).exists())
        self.assertFalse(RepeatableRow.objects.filter(pk=deleted_row.pk).exists())
        created_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=group,
            values__field=field,
            values__text_value="New",
        )
        existing_row.refresh_from_db()
        self.assertEqual(existing_row.values.get(field=field).text_value, "Updated")

    def test_save_applies_repeatable_diff(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Item Name",
            code="item_name",
            label="Item Name",
            field_type=FormField.FieldType.TEXT,
        )
        self.grant_repeatable_write_permissions(group, field)

        result = self.call(
            submitted_data={
                "items": [
                    {
                        "row_id": None,
                        "item_name": "New",
                    },
                ],
            },
        )

        self.assertEqual(
            [change.action for change in result.diff.groups[0].changes],
            [RowChangeAction.CREATE],
        )
        created_row = RepeatableRow.objects.get(instance=self.instance, group=group)
        self.assertEqual(created_row.values.get(field=field).text_value, "New")

    def test_save_applies_device_create_with_new_normal_parent(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parents",
            code="parents_device_integration",
            order=1,
        )
        parent_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Parent Name",
            code="parent_name_device_integration",
            label="Parent Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )

        device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name="Devices",
            code="devices_device_integration",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=2,
        )
        device_fields = {}
        definitions = (
            (FormField.SystemKey.IMEI, "device_imei", FormField.FieldType.TEXT),
            (FormField.SystemKey.DEVICE_TYPE, "device_type", FormField.FieldType.SELECT),
            (FormField.SystemKey.DEVICE_MODEL, "device_model", FormField.FieldType.SELECT),
        )
        for field_order, (system_key, code, field_type) in enumerate(definitions):
            device_fields[system_key] = FormField.objects.create(
                section=self.section,
                repeatable_group=device_group,
                name=code,
                code=code,
                label=code,
                field_type=field_type,
                system_key=system_key,
                order=field_order,
            )

        device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE_INTEGRATION",
            is_active=True,
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Phone X",
            code="PHONE_X_INTEGRATION",
            is_active=True,
        )

        self.grant_repeatable_write_permissions(parent_group, parent_field)
        for field in device_fields.values():
            self.grant_repeatable_write_permissions(device_group, field)

        result = self.call(
            submitted_data={
                "parents_device_integration": [
                    {
                        "parent_name_device_integration": "Parent",
                        "devices_device_integration": [
                            {
                                "device_imei": "",
                                "device_type": device_type.pk,
                                "device_model": device_model.pk,
                            },
                        ],
                    },
                ],
            },
        )

        parent_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=parent_group,
        )
        child_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=device_group,
        )
        instance_device = InstanceDevice.objects.get(
            instance=self.instance,
            device=None,
        )

        self.assertEqual(parent_row.values.get(field=parent_field).text_value, "Parent")
        self.assertEqual(child_row.parent_row_id, parent_row.pk)
        self.assertEqual(child_row.instance_device_id, instance_device.pk)
        self.assertEqual(instance_device.draft_device_model_id, device_model.pk)
        self.assertEqual(instance_device.draft_device_type_id, device_type.pk)
        self.assertTrue(result.saved)

    def test_save_rolls_back_all_repeatable_changes_when_apply_fails(self):
        group = FormRepeatableGroup.objects.create(section=self.section, name="Items", code="items_atomic", order=1)
        field = FormField.objects.create(section=self.section, repeatable_group=group, name="Item Name", code="item_name_atomic", label="Item Name", field_type=FormField.FieldType.TEXT)
        self.grant_repeatable_write_permissions(group, field)
        existing_row = RepeatableRow.objects.create(instance=self.instance, group=group, row_order=0)

        with patch(
            "workflow.form_draft_save_services.FormDraftDeleteApplyService.apply",
            side_effect=ValidationError("forced failure"),
        ):
            with self.assertRaises(ValidationError):
                self.call(submitted_data={
                    "items_atomic": [
                        {"row_id": existing_row.pk, "item_name_atomic": "Updated"},
                        {"row_id": None, "item_name_atomic": "New"},
                    ],
                })

        existing_row.refresh_from_db()
        self.assertFalse(existing_row.values.filter(field=field).exists())
        self.assertEqual(
            RepeatableRow.objects.filter(instance=self.instance, group=group).count(),
            1,
        )
    def test_save_requires_edit_mode(self):
        with self.assertRaises(ValidationError):
            self.call(edit_mode=False)

    def test_save_rejects_submitted_step(self):
        self.execution.is_submitted = True
        self.execution.save(update_fields=["is_submitted"])

        with self.assertRaises(ValidationError):
            self.call()

    def test_save_rejects_step_from_another_workflow(self):
        other_workflow = Workflow.objects.create(
            name="Other Workflow",
            code="OTHER_DRAFT_WF",
        )
        other_step = WorkflowStep.objects.create(
            workflow=other_workflow,
            name="Other Step",
            code="OTHER_STEP",
            order=1,
        )

        with self.assertRaises(ValidationError):
            self.call(step=other_step)

    def test_save_rejects_non_current_step(self):
        another_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Another Step",
            code="ANOTHER_STEP",
            order=2,
        )

        with self.assertRaises(ValidationError):
            self.call(step=another_step)

    def test_save_requires_step_execution(self):
        self.execution.delete()

        with self.assertRaises(ValidationError):
            self.call()

    def test_missing_form_is_rejected(self):
        self.form.is_active = False
        self.form.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            self.call()

    def test_repeatable_payload_is_normalized_with_stable_row_identity(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Item Name",
            code="item_name",
            label="Item Name",
            field_type=FormField.FieldType.TEXT,
        )
        self.grant_repeatable_write_permissions(group, field)

        existing_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        result = self.call(
            submitted_data={
                "customer_name": "Ehsan",
                "items": [
                    {
                        "row_id": existing_row.pk,
                        "item_name": "First",
                    },
                    {
                        "row_id": None,
                        "item_name": "Second",
                    },
                ],
            },
        )

        rows = result.normalized_payload.repeatable_groups["items"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].row_id, existing_row.pk)
        self.assertEqual(rows[0].fields, {"item_name": "First"})
        self.assertIsNone(rows[1].row_id)
        self.assertEqual(rows[1].fields, {"item_name": "Second"})
        self.assertEqual(
            result.normalized_payload.normal_fields,
            {"customer_name": "Ehsan"},
        )
        self.assertEqual(field.repeatable_group_id, group.pk)

    def test_invalid_repeatable_payload_shape_is_rejected(self):
        FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    "items": {"row_id": 1},
                },
            )

    def test_invalid_row_identity_is_rejected(self):
        FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    "items": [
                        {
                            "row_id": "12",
                        },
                    ],
                },
            )

    def test_nested_repeatable_groups_are_normalized_recursively(self):
        parent = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parents",
            code="parents",
            order=1,
        )
        child = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent,
            name="Children",
            code="children",
            order=2,
        )
        parent_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent,
            name="Parent Name",
            code="parent_name",
            label="Parent Name",
            field_type=FormField.FieldType.TEXT,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child,
            name="Child Name",
            code="child_name",
            label="Child Name",
            field_type=FormField.FieldType.TEXT,
        )
        self.grant_repeatable_write_permissions(parent, parent_field)
        self.grant_repeatable_write_permissions(child, child_field)

        parent_row_db = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent,
            row_order=0,
        )
        child_row_db = RepeatableRow.objects.create(
            instance=self.instance,
            group=child,
            parent_row=parent_row_db,
            row_order=0,
        )

        result = self.call(
            submitted_data={
                "parents": [
                    {
                        "row_id": parent_row_db.pk,
                        "parent_name": "Parent",
                        "children": [
                            {
                                "row_id": child_row_db.pk,
                                "child_name": "Child",
                            },
                        ],
                    },
                ],
            },
        )

        parent_row = result.normalized_payload.repeatable_groups["parents"][0]
        child_row = parent_row.child_groups["children"][0]

        self.assertEqual(parent_row.row_id, parent_row_db.pk)
        self.assertEqual(parent_row.fields, {"parent_name": "Parent"})
        self.assertEqual(child_row.row_id, child_row_db.pk)
        self.assertEqual(child_row.fields, {"child_name": "Child"})

    def test_existing_row_id_must_belong_to_same_instance_and_group(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section, name="Items", code="items_identity", order=1,
        )
        other_group = FormRepeatableGroup.objects.create(
            section=self.section, name="Other", code="other_identity", order=2,
        )
        FormField.objects.create(
            section=self.section, repeatable_group=group,
            name="Item", code="item_name", label="Item",
            field_type=FormField.FieldType.TEXT,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance, group=other_group, row_order=0,
        )
        with self.assertRaises(ValidationError):
            self.call(submitted_data={"items_identity": [{"row_id": row.pk, "item_name": "x"}]})

    def test_existing_row_id_from_another_instance_is_rejected(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section, name="Items", code="items_other_instance", order=1,
        )
        FormField.objects.create(
            section=self.section, repeatable_group=group,
            name="Item", code="item_name", label="Item",
            field_type=FormField.FieldType.TEXT,
        )
        other_instance = WorkflowInstance.objects.create(
            workflow=self.workflow, current_step=self.step, started_by=self.user,
        )
        row = RepeatableRow.objects.create(
            instance=other_instance, group=group, row_order=0,
        )
        with self.assertRaises(ValidationError):
            self.call(submitted_data={"items_other_instance": [{"row_id": row.pk}]})

    def test_unknown_existing_row_id_is_rejected(self):
        FormRepeatableGroup.objects.create(
            section=self.section, name="Items", code="items_unknown", order=1,
        )
        with self.assertRaises(ValidationError):
            self.call(submitted_data={"items_unknown": [{"row_id": 999999}]})

    def test_duplicate_row_id_in_payload_is_rejected(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section, name="Items", code="items_duplicate", order=1,
        )
        FormField.objects.create(
            section=self.section, repeatable_group=group,
            name="Item", code="item_name", label="Item",
            field_type=FormField.FieldType.TEXT,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance, group=group, row_order=0,
        )
        with self.assertRaises(ValidationError):
            self.call(submitted_data={"items_duplicate": [
                {"row_id": row.pk, "item_name": "a"},
                {"row_id": row.pk, "item_name": "b"},
            ]})

    def test_existing_nested_row_must_have_submitted_parent(self):
        parent = FormRepeatableGroup.objects.create(
            section=self.section, name="Parents", code="parents_identity", order=1,
        )
        child = FormRepeatableGroup.objects.create(
            section=self.section, parent_group=parent,
            name="Children", code="children_identity", order=2,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance, group=parent, row_order=0,
        )
        other_parent_row = RepeatableRow.objects.create(
            instance=self.instance, group=parent, row_order=1,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance, group=child,
            parent_row=other_parent_row, row_order=0,
        )
        with self.assertRaises(ValidationError):
            self.call(submitted_data={"parents_identity": [{
                "row_id": parent_row.pk,
                "children_identity": [{"row_id": child_row.pk}],
            }]})
