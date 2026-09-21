from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_device_update_apply_services import (
    FormDraftDeviceUpdateApplyService,
)
from workflow.form_draft_diff_services import (
    FormDraftDiff,
    FormDraftDiffService,
    RepeatableGroupDiff,
    RowChange,
    RowChangeAction,
    RowReference,
    RowReferenceKind,
)
from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.models import (
    Device,
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
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


class FormDraftDeviceUpdateApplyServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Device Update Workflow",
            code="DEVICE_UPDATE_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Device Update Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Device Update Section",
            code="DEVICE_UPDATE_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )
        self.device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE",
            is_active=True,
        )
        self.other_type = DeviceType.objects.create(
            name="Laptop",
            code="LAPTOP",
            is_active=True,
        )
        self.device_model = DeviceModel.objects.create(
            device_type=self.device_type,
            brand="Test",
            name="Phone X",
            code="PHONE_X",
            is_active=True,
        )
        self.other_model = DeviceModel.objects.create(
            device_type=self.device_type,
            brand="Test",
            name="Phone Y",
            code="PHONE_Y",
            is_active=True,
        )
        self.other_type_model = DeviceModel.objects.create(
            device_type=self.other_type,
            brand="Test",
            name="Laptop X",
            code="LAPTOP_X",
            is_active=True,
        )

    def create_device_group(self, *, code="devices", parent_group=None, order=1):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name="Devices",
            code=code,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=order,
        )
        fields = {}
        definitions = (
            (FormField.SystemKey.IMEI, f"{code}_imei", FormField.FieldType.TEXT),
            (FormField.SystemKey.DEVICE_TYPE, f"{code}_type", FormField.FieldType.SELECT),
            (FormField.SystemKey.DEVICE_MODEL, f"{code}_model", FormField.FieldType.SELECT),
            (FormField.SystemKey.REPORTED_PROBLEM, f"{code}_problem", FormField.FieldType.TEXTAREA),
            (FormField.SystemKey.DESCRIPTION, f"{code}_description", FormField.FieldType.TEXTAREA),
            (FormField.SystemKey.WARRANTY_STATUS, f"{code}_warranty", FormField.FieldType.SELECT),
            (FormField.SystemKey.STATUS, f"{code}_status", FormField.FieldType.SELECT),
        )
        for order, (system_key, field_code, field_type) in enumerate(definitions):
            fields[system_key] = FormField.objects.create(
                section=self.section,
                repeatable_group=group,
                name=field_code,
                code=field_code,
                label=field_code,
                field_type=field_type,
                system_key=system_key,
                order=order,
            )
        fields["custom"] = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=f"{code} color",
            code=f"{code}_color",
            label="Color",
            field_type=FormField.FieldType.TEXT,
            order=len(definitions),
        )
        return group, fields

    @staticmethod
    def row(*, row_id, fields):
        return NormalizedRow(
            row_id=row_id,
            fields=fields,
            child_groups={},
        )

    def build_diff(self, *, group, row):
        payload = NormalizedFormPayload(
            normal_fields={},
            repeatable_groups={group.code: (row,)},
        )
        return FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )

    def create_resolved_row(self, group, *, imei="111111111111111"):
        device = Device.objects.create(device_model=self.device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value=imei,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
            reported_problem="Old problem",
            description="Old description",
            warranty_status="OLD",
            status="OLD",
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
            instance_device=instance_device,
        )
        return row, instance_device, device

    def create_unresolved_row(self, group, *, imei="222222222222222"):
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_imei=imei,
            draft_device_model=self.device_model,
            draft_device_type=self.device_type,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
            instance_device=instance_device,
        )
        return row, instance_device

    def test_resolved_device_updates_system_and_custom_values(self):
        group, fields = self.create_device_group()
        row, instance_device, device = self.create_resolved_row(group)
        RepeatableRowValue.objects.create(
            row=row,
            field=fields["custom"],
            text_value="Old color",
        )

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "111111111111111",
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
                    fields[FormField.SystemKey.REPORTED_PROBLEM].code: "New problem",
                    fields[FormField.SystemKey.DESCRIPTION].code: "New description",
                    fields[FormField.SystemKey.WARRANTY_STATUS].code: "VALID",
                    fields[FormField.SystemKey.STATUS].code: "RECEIVED",
                    fields["custom"].code: "Black",
                },
            ),
        )

        FormDraftDeviceUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        instance_device.refresh_from_db()
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(instance_device.reported_problem, "New problem")
        self.assertEqual(instance_device.description, "New description")
        self.assertEqual(instance_device.warranty_status, "VALID")
        self.assertEqual(instance_device.status, "RECEIVED")
        self.assertEqual(
            RepeatableRowValue.objects.get(row=row, field=fields["custom"]).text_value,
            "Black",
        )

    def test_resolved_imei_cannot_change(self):
        group, fields = self.create_device_group()
        row, instance_device, device = self.create_resolved_row(group)

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "999999999999999",
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                },
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftDeviceUpdateApplyService.apply(
                instance=self.instance,
                diff=diff,
            )

        instance_device.refresh_from_db()
        self.assertEqual(instance_device.device_id, device.pk)

    def test_resolved_device_model_can_change_with_consistent_type(self):
        group, fields = self.create_device_group()
        row, instance_device, device = self.create_resolved_row(group)

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "111111111111111",
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.other_model.pk,
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                },
            ),
        )

        FormDraftDeviceUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        device.refresh_from_db()
        self.assertEqual(device.device_model_id, self.other_model.pk)
        instance_device.refresh_from_db()
        self.assertEqual(instance_device.device_id, device.pk)

    def test_resolved_device_model_type_mismatch_is_rejected(self):
        group, fields = self.create_device_group()
        row, instance_device, device = self.create_resolved_row(group)

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "111111111111111",
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.other_type_model.pk,
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                },
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftDeviceUpdateApplyService.apply(
                instance=self.instance,
                diff=diff,
            )

        device.refresh_from_db()
        self.assertEqual(device.device_model_id, self.device_model.pk)

    def test_unresolved_device_can_resolve_by_imei(self):
        group, fields = self.create_device_group()
        row, instance_device = self.create_unresolved_row(group, imei="333333333333333")
        device = Device.objects.create(device_model=self.device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="333333333333333",
        )

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "333333333333333",
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                },
            ),
        )

        FormDraftDeviceUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        instance_device.refresh_from_db()
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model_id)
        self.assertIsNone(instance_device.draft_device_type_id)

    def test_unresolved_unknown_imei_remains_unresolved(self):
        group, fields = self.create_device_group()
        row, instance_device = self.create_unresolved_row(group, imei="444444444444444")

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "555555555555555",
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.other_model.pk,
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                },
            ),
        )

        FormDraftDeviceUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        instance_device.refresh_from_db()
        self.assertIsNone(instance_device.device_id)
        self.assertEqual(instance_device.draft_imei, "555555555555555")
        self.assertEqual(instance_device.draft_device_model_id, self.other_model.pk)
        self.assertEqual(instance_device.draft_device_type_id, self.device_type.pk)

    def test_unresolved_blank_imei_is_allowed(self):
        group, fields = self.create_device_group()
        row, instance_device = self.create_unresolved_row(group, imei="")

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "",
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.other_model.pk,
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                },
            ),
        )

        FormDraftDeviceUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        instance_device.refresh_from_db()
        self.assertIsNone(instance_device.device_id)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertEqual(instance_device.draft_device_model_id, self.other_model.pk)

    def test_resolution_to_duplicate_device_is_rejected(self):
        group, fields = self.create_device_group()
        row, instance_device = self.create_unresolved_row(group, imei="")
        device = Device.objects.create(device_model=self.device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="666666666666666",
        )
        InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
        )

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "666666666666666",
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                },
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftDeviceUpdateApplyService.apply(
                instance=self.instance,
                diff=diff,
            )

        instance_device.refresh_from_db()
        self.assertIsNone(instance_device.device_id)

    def test_failed_device_update_rolls_back(self):
        group, fields = self.create_device_group()
        row, instance_device, device = self.create_resolved_row(group)

        diff = self.build_diff(
            group=group,
            row=self.row(
                row_id=row.pk,
                fields={
                    fields[FormField.SystemKey.IMEI].code: "111111111111111",
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.other_type_model.pk,
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                    fields[FormField.SystemKey.REPORTED_PROBLEM].code: "Should rollback",
                },
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftDeviceUpdateApplyService.apply(
                instance=self.instance,
                diff=diff,
            )

        device.refresh_from_db()
        instance_device.refresh_from_db()
        self.assertEqual(device.device_model_id, self.device_model.pk)
        self.assertEqual(instance_device.reported_problem, "Old problem")
