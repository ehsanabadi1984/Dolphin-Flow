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
    Device,
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
    FormData,
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
    LookupItem,
    LookupList,
    RepeatableRow,
    RepeatableRowValue,
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
        FieldAccess.objects.create(
            field=self.form_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
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


    def test_nested_repeatable_groups_are_normalized_recursively_to_grandchild(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parents",
            code="parents_depth_three",
            order=1,
        )
        parent_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Parent Name",
            code="parent_name_depth_three",
            label="Parent Name",
            field_type=FormField.FieldType.TEXT,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name="Children",
            code="children_depth_three",
            order=2,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Name",
            code="child_name_depth_three",
            label="Child Name",
            field_type=FormField.FieldType.TEXT,
        )
        grandchild_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=child_group,
            name="Grandchildren",
            code="grandchildren_depth_three",
            order=3,
        )
        grandchild_field = FormField.objects.create(
            section=self.section,
            repeatable_group=grandchild_group,
            name="Grandchild Name",
            code="grandchild_name_depth_three",
            label="Grandchild Name",
            field_type=FormField.FieldType.TEXT,
        )

        normalized = FormDraftSaveService._normalize_submitted_data(
            form=self.form,
            submitted_data={
                "parents_depth_three": [
                    {
                        "row_id": None,
                        "parent_name_depth_three": "Parent",
                        "children_depth_three": [
                            {
                                "row_id": None,
                                "child_name_depth_three": "Child",
                                "grandchildren_depth_three": [
                                    {
                                        "row_id": None,
                                        "grandchild_name_depth_three": "Grandchild",
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        )

        parent = normalized.repeatable_groups["parents_depth_three"][0]
        child = parent.child_groups["children_depth_three"][0]
        grandchild = child.child_groups["grandchildren_depth_three"][0]

        self.assertEqual(parent.fields, {parent_field.code: "Parent"})
        self.assertEqual(child.fields, {child_field.code: "Child"})
        self.assertEqual(
            grandchild.fields,
            {grandchild_field.code: "Grandchild"},
        )
        self.assertEqual(grandchild.child_groups, {})

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

    def test_normal_field_is_created_in_form_data(self):
        result = self.call(
            submitted_data={"customer_name": "Ehsan"},
        )

        form_data = FormData.objects.get(instance=self.instance)
        self.assertEqual(form_data.data, {"customer_name": "Ehsan"})
        self.assertEqual(result.form_data.pk, form_data.pk)

    def test_normal_field_is_updated_in_form_data(self):
        FormData.objects.create(
            instance=self.instance,
            data={"customer_name": "Original"},
        )

        result = self.call(
            submitted_data={"customer_name": "Updated"},
        )

        form_data = FormData.objects.get(instance=self.instance)
        self.assertEqual(form_data.data, {"customer_name": "Updated"})
        self.assertEqual(result.form_data.pk, form_data.pk)

    def test_invalid_normal_field_value_is_rejected_before_persistence(self):
        number_field = FormField.objects.create(
            section=self.section,
            name="Amount",
            code="amount",
            label="Amount",
            field_type=FormField.FieldType.NUMBER,
            order=2,
        )
        FieldAccess.objects.create(
            field=number_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        FormData.objects.create(
            instance=self.instance,
            data={"amount": "12.50"},
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={"amount": "not-a-number"},
            )

        form_data = FormData.objects.get(instance=self.instance)
        self.assertEqual(form_data.data, {"amount": "12.50"})

    def test_invalid_dependent_select_is_rejected_before_persistence(self):
        lookup = LookupList.objects.create(
            name="Regions",
            code="DRAFT_REGIONS",
        )
        parent = LookupItem.objects.create(
            lookup_list=lookup,
            value="TEHRAN",
            label="Tehran",
        )
        other_parent = LookupItem.objects.create(
            lookup_list=lookup,
            value="TABRIZ",
            label="Tabriz",
        )
        child = LookupItem.objects.create(
            lookup_list=lookup,
            parent=other_parent,
            value="NORTH",
            label="North",
        )
        parent_field = FormField.objects.create(
            section=self.section,
            name="Region",
            code="region",
            label="Region",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
            order=2,
        )
        child_field = FormField.objects.create(
            section=self.section,
            name="Area",
            code="area",
            label="Area",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
            choice_parent_field=parent_field,
            order=3,
        )
        FieldAccess.objects.create(
            field=parent_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=child_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        FormData.objects.create(
            instance=self.instance,
            data={"region": parent.value, "area": ""},
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={"area": child.value},
            )

        form_data = FormData.objects.get(instance=self.instance)
        self.assertEqual(
            form_data.data,
            {"region": parent.value, "area": ""},
        )

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

    def test_save_applies_device_update(self):
        device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            code="devices_update_integration",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=1,
        )
        device_fields = {}
        definitions = (
            (FormField.SystemKey.IMEI, "device_update_imei", FormField.FieldType.TEXT),
            (FormField.SystemKey.DEVICE_TYPE, "device_update_type", FormField.FieldType.SELECT),
            (FormField.SystemKey.DEVICE_MODEL, "device_update_model", FormField.FieldType.SELECT),
            (FormField.SystemKey.REPORTED_PROBLEM, "device_update_problem", FormField.FieldType.TEXTAREA),
            (FormField.SystemKey.DESCRIPTION, "device_update_description", FormField.FieldType.TEXTAREA),
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
            code="PHONE_UPDATE_INTEGRATION",
            is_active=True,
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Phone X",
            code="PHONE_X_UPDATE_INTEGRATION",
            is_active=True,
        )
        device = Device.objects.create(
            device_model=device_model,
        )
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="777777777777777",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
            reported_problem="Old",
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=device_group,
            row_order=0,
            instance_device=instance_device,
        )

        for field in device_fields.values():
            self.grant_repeatable_write_permissions(device_group, field)

        result = self.call(
            submitted_data={
                "devices_update_integration": [
                    {
                        "row_id": row.pk,
                        "device_update_imei": "777777777777777",
                        "device_update_type": device_type.pk,
                        "device_update_model": device_model.pk,
                        "device_update_problem": "New problem",
                        "device_update_description": "New description",
                    },
                ],
            },
        )

        instance_device.refresh_from_db()
        self.assertEqual(instance_device.reported_problem, "New problem")
        self.assertEqual(instance_device.description, "New description")
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
    def test_changed_normal_field_is_rejected_before_persistence_without_edit_permission(self):
        FormData.objects.create(
            instance=self.instance,
            data={"customer_name": "Original"},
        )
        FieldAccess.objects.filter(
            field=self.form_field,
            step=self.step,
            user=self.user,
        ).update(can_edit=False)

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={"customer_name": "Changed"},
            )

        form_data = FormData.objects.get(instance=self.instance)
        self.assertEqual(form_data.data, {"customer_name": "Original"})

    def test_unchanged_normal_field_is_allowed_without_edit_permission(self):
        FormData.objects.create(
            instance=self.instance,
            data={"customer_name": "Original"},
        )
        FieldAccess.objects.filter(
            field=self.form_field,
            step=self.step,
            user=self.user,
        ).update(can_edit=False)

        result = self.call(
            submitted_data={"customer_name": "Original"},
        )

        self.assertTrue(result.saved)
        form_data = FormData.objects.get(instance=self.instance)
        self.assertEqual(form_data.data, {"customer_name": "Original"})

    def test_repeatable_row_update_is_rejected_before_persistence_without_group_edit_permission(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items Row Edit Permission",
            code="items_row_edit_permission",
            order=10,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Item Name",
            code="item_name_row_edit_permission",
            label="Item Name",
            field_type=FormField.FieldType.TEXT,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=field,
            text_value="Original",
        )
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
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

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    "items_row_edit_permission": [
                        {
                            "row_id": row.pk,
                            "item_name_row_edit_permission": "Changed",
                        },
                    ],
                },
            )

        row.refresh_from_db()
        self.assertEqual(
            row.values.get(field=field).text_value,
            "Original",
        )

    def test_repeatable_row_create_is_rejected_without_group_add_permission(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items Row Add Permission",
            code="items_row_add_permission",
            order=11,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Item Name",
            code="item_name_row_add_permission",
            label="Item Name",
            field_type=FormField.FieldType.TEXT,
        )
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=False,
            can_delete=True,
        )
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    "items_row_add_permission": [
                        {
                            "row_id": None,
                            "item_name_row_add_permission": "New",
                        },
                    ],
                },
            )

        self.assertFalse(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).exists()
        )

    def test_repeatable_row_delete_is_rejected_without_group_delete_permission(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items Row Delete Permission",
            code="items_row_delete_permission",
            order=12,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Item Name",
            code="item_name_row_delete_permission",
            label="Item Name",
            field_type=FormField.FieldType.TEXT,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=False,
        )
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    "items_row_delete_permission": [],
                },
            )

        self.assertTrue(
            RepeatableRow.objects.filter(pk=row.pk).exists()
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


    def _create_device_system_fields_for_identity_tests(self, code_prefix):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name=f"Devices {code_prefix}",
            code=f"devices_{code_prefix.lower()}",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=20,
        )
        fields = {}
        definitions = (
            (FormField.SystemKey.IMEI, "imei", FormField.FieldType.TEXT),
            (FormField.SystemKey.DEVICE_TYPE, "device_type", FormField.FieldType.SELECT),
            (FormField.SystemKey.DEVICE_MODEL, "device_model", FormField.FieldType.SELECT),
        )
        for order, (system_key, suffix, field_type) in enumerate(definitions):
            field = FormField.objects.create(
                section=self.section,
                repeatable_group=group,
                name=f"{code_prefix} {suffix}",
                code=f"{code_prefix.lower()}_{suffix}",
                label=f"{code_prefix} {suffix}",
                field_type=field_type,
                system_key=system_key,
                order=order,
            )
            fields[system_key] = field
            self.grant_repeatable_write_permissions(group, field)
        return group, fields

    def test_save_reuses_existing_device_on_create_by_imei(self):
        group, fields = self._create_device_system_fields_for_identity_tests(
            "CREATE_REUSE",
        )
        device_type = DeviceType.objects.create(
            name="Create Reuse Type",
            code="DRAFT_CREATE_REUSE_TYPE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Create Reuse Model",
            code="DRAFT_CREATE_REUSE_MODEL",
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="810000000000001",
        )

        result = self.call(
            submitted_data={
                group.code: [
                    {
                        "create_reuse_imei": "810000000000001",
                        "create_reuse_device_type": device_type.pk,
                        "create_reuse_device_model": device_model.pk,
                    },
                ],
            },
        )

        instance_device = InstanceDevice.objects.get(instance=self.instance)
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model_id)
        self.assertIsNone(instance_device.draft_device_type_id)
        self.assertTrue(result.saved)

    def test_save_resolves_unresolved_device_by_existing_imei(self):
        group, fields = self._create_device_system_fields_for_identity_tests(
            "RESOLVE",
        )
        device_type = DeviceType.objects.create(
            name="Resolve Type",
            code="DRAFT_RESOLVE_TYPE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Resolve Model",
            code="DRAFT_RESOLVE_MODEL",
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="820000000000002",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_imei="820000000000099",
            draft_device_model=device_model,
            draft_device_type=device_type,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        result = self.call(
            submitted_data={
                group.code: [
                    {
                        "row_id": row.pk,
                        "resolve_imei": "820000000000002",
                        "resolve_device_type": device_type.pk,
                        "resolve_device_model": device_model.pk,
                    },
                ],
            },
        )

        instance_device.refresh_from_db()
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model_id)
        self.assertIsNone(instance_device.draft_device_type_id)
        self.assertTrue(result.saved)

    def test_save_allows_resolved_device_model_change(self):
        group, fields = self._create_device_system_fields_for_identity_tests(
            "MODEL_CHANGE",
        )
        device_type = DeviceType.objects.create(
            name="Model Change Type",
            code="DRAFT_MODEL_CHANGE_TYPE",
        )
        original_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Original Model",
            code="DRAFT_MODEL_CHANGE_ORIGINAL",
        )
        target_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Target Model",
            code="DRAFT_MODEL_CHANGE_TARGET",
        )
        device = Device.objects.create(device_model=original_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="830000000000003",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        result = self.call(
            submitted_data={
                group.code: [
                    {
                        "row_id": row.pk,
                        "model_change_imei": "830000000000003",
                        "model_change_device_type": device_type.pk,
                        "model_change_device_model": target_model.pk,
                    },
                ],
            },
        )

        device.refresh_from_db()
        self.assertEqual(device.device_model_id, target_model.pk)
        self.assertTrue(result.saved)

    def test_save_rejects_imei_change_on_resolved_device(self):
        group, fields = self._create_device_system_fields_for_identity_tests(
            "IMEI_CHANGE",
        )
        device_type = DeviceType.objects.create(
            name="IMEI Change Type",
            code="DRAFT_IMEI_CHANGE_TYPE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="IMEI Change Model",
            code="DRAFT_IMEI_CHANGE_MODEL",
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="840000000000004",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    group.code: [
                        {
                            "row_id": row.pk,
                            "imei_change_imei": "840000000000005",
                            "imei_change_device_type": device_type.pk,
                            "imei_change_device_model": device_model.pk,
                        },
                    ],
                },
            )

        self.assertEqual(
            DeviceIdentifier.objects.get(device=device).value,
            "840000000000004",
        )

    def test_save_rejects_device_model_type_mismatch(self):
        group, fields = self._create_device_system_fields_for_identity_tests(
            "MISMATCH",
        )
        first_type = DeviceType.objects.create(
            name="Mismatch Type A",
            code="DRAFT_MISMATCH_TYPE_A",
        )
        second_type = DeviceType.objects.create(
            name="Mismatch Type B",
            code="DRAFT_MISMATCH_TYPE_B",
        )
        model = DeviceModel.objects.create(
            device_type=first_type,
            brand="Test",
            name="Mismatch Model",
            code="DRAFT_MISMATCH_MODEL",
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    group.code: [
                        {
                            "row_id": None,
                            "mismatch_device_type": second_type.pk,
                            "mismatch_device_model": model.pk,
                        },
                    ],
                },
            )

        self.assertFalse(
            InstanceDevice.objects.filter(instance=self.instance).exists()
        )

    def test_save_rejects_duplicate_existing_device_in_same_instance(self):
        group, fields = self._create_device_system_fields_for_identity_tests(
            "DUPLICATE",
        )
        device_type = DeviceType.objects.create(
            name="Duplicate Type",
            code="DRAFT_DUPLICATE_TYPE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Duplicate Model",
            code="DRAFT_DUPLICATE_MODEL",
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="850000000000006",
        )
        existing_instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
        )
        RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=existing_instance_device,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    group.code: [
                        {
                            "row_id": None,
                            "duplicate_imei": "850000000000006",
                            "duplicate_device_type": device_type.pk,
                            "duplicate_device_model": device_model.pk,
                        },
                    ],
                },
            )

        self.assertEqual(
            InstanceDevice.objects.filter(instance=self.instance, is_active=True).count(),
            1,
        )



    def test_adding_children_to_both_root_rows_preserves_each_root_and_child(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parents",
            code="parents_child_regression",
            order=10,
        )
        parent_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Address",
            code="address_child_regression",
            label="Address",
            field_type=FormField.FieldType.TEXTAREA,
            order=0,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name="Children",
            code="children_child_regression",
            order=11,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Name",
            code="child_name_regression",
            label="Child Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        self.grant_repeatable_write_permissions(parent_group, parent_field)
        self.grant_repeatable_write_permissions(child_group, child_field)

        first_save = self.call(
            submitted_data={
                "parents_child_regression": [
                    {
                        "row_id": None,
                        "address_child_regression": "آقایی",
                    },
                    {
                        "row_id": None,
                        "address_child_regression": "صمدی",
                    },
                ],
            },
        )
        self.assertTrue(first_save.saved)

        parent_rows = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=parent_group,
            ).order_by("row_order", "pk")
        )
        self.assertEqual(
            [row.values.get(field=parent_field).text_value for row in parent_rows],
            ["آقایی", "صمدی"],
        )

        second_save = self.call(
            submitted_data={
                "parents_child_regression": [
                    {
                        "row_id": parent_rows[0].pk,
                        "address_child_regression": "آقایی",
                        "children_child_regression": [
                            {
                                "row_id": None,
                                "child_name_regression": "فرزند آقایی",
                            },
                        ],
                    },
                    {
                        "row_id": parent_rows[1].pk,
                        "address_child_regression": "صمدی",
                        "children_child_regression": [
                            {
                                "row_id": None,
                                "child_name_regression": "فرزند صمدی",
                            },
                        ],
                    },
                ],
            },
        )
        self.assertTrue(second_save.saved)

        parent_rows = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=parent_group,
            ).order_by("row_order", "pk")
        )
        self.assertEqual(
            [row.values.get(field=parent_field).text_value for row in parent_rows],
            ["آقایی", "صمدی"],
        )

        child_rows = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=child_group,
            ).order_by("parent_row_id", "row_order", "pk")
        )
        self.assertEqual(child_rows.__len__(), 2)
        self.assertEqual(
            [row.parent_row_id for row in child_rows],
            [parent_rows[0].pk, parent_rows[1].pk],
        )
        self.assertEqual(
            [
                row.values.get(field=child_field).text_value
                for row in child_rows
            ],
            ["فرزند آقایی", "فرزند صمدی"],
        )

