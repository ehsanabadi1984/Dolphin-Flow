from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_device_create_apply_services import (
    FormDraftDeviceCreateApplyService,
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


class FormDraftDeviceCreateApplyServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Device Create Workflow",
            code="DEVICE_CREATE_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Device Create Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Device Section",
            code="DEVICE_SECTION",
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
        self.device_model = DeviceModel.objects.create(
            device_type=self.device_type,
            brand="Test",
            name="Phone X",
            code="PHONE_X",
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
        field_definitions = (
            (FormField.SystemKey.IMEI, f"{code}_imei", FormField.FieldType.TEXT),
            (FormField.SystemKey.DEVICE_TYPE, f"{code}_type", FormField.FieldType.SELECT),
            (FormField.SystemKey.DEVICE_MODEL, f"{code}_model", FormField.FieldType.SELECT),
            (FormField.SystemKey.REPORTED_PROBLEM, f"{code}_problem", FormField.FieldType.TEXTAREA),
            (FormField.SystemKey.DESCRIPTION, f"{code}_description", FormField.FieldType.TEXTAREA),
            (FormField.SystemKey.WARRANTY_STATUS, f"{code}_warranty", FormField.FieldType.SELECT),
            (FormField.SystemKey.STATUS, f"{code}_status", FormField.FieldType.SELECT),
        )
        for field_order, (system_key, field_code, field_type) in enumerate(field_definitions):
            fields[system_key] = FormField.objects.create(
                section=self.section,
                repeatable_group=group,
                name=field_code,
                code=field_code,
                label=field_code,
                field_type=field_type,
                system_key=system_key,
                order=field_order,
            )
        fields["custom"] = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=f"{code} color",
            code=f"{code}_color",
            label="Color",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.NONE,
            order=len(field_definitions),
        )
        return group, fields

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

    def test_existing_device_is_attached_to_new_row(self):
        group, fields = self.create_device_group()
        device = Device.objects.create(device_model=self.device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="111111111111111",
        )
        diff = self.build_diff(
            devices=[self.row(fields={
                fields[FormField.SystemKey.IMEI].code: "111111111111111",
                fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
                fields["custom"].code: "Black",
            })],
        )
        created = FormDraftDeviceCreateApplyService.apply(
            instance=self.instance, diff=diff,
        )
        row = next(iter(created.values()))
        instance_device = row.instance_device
        self.assertEqual(row.group_id, group.pk)
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model_id)
        self.assertIsNone(instance_device.draft_device_type_id)
        value = RepeatableRowValue.objects.get(row=row, field=fields["custom"])
        self.assertEqual(value.text_value, "Black")

    def test_new_imei_creates_unresolved_draft_device(self):
        _, fields = self.create_device_group()
        diff = self.build_diff(
            devices=[self.row(fields={
                fields[FormField.SystemKey.IMEI].code: "222222222222222",
                fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
            })],
        )
        created = FormDraftDeviceCreateApplyService.apply(
            instance=self.instance, diff=diff,
        )
        instance_device = next(iter(created.values())).instance_device
        self.assertIsNone(instance_device.device_id)
        self.assertEqual(instance_device.draft_imei, "222222222222222")
        self.assertEqual(instance_device.draft_device_model_id, self.device_model.pk)
        self.assertEqual(instance_device.draft_device_type_id, self.device_type.pk)

    def test_blank_imei_creates_unidentified_device_without_lookup(self):
        _, fields = self.create_device_group()
        diff = self.build_diff(
            devices=[self.row(fields={
                fields[FormField.SystemKey.IMEI].code: "",
                fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
            })],
        )
        created = FormDraftDeviceCreateApplyService.apply(
            instance=self.instance, diff=diff,
        )
        instance_device = next(iter(created.values())).instance_device
        self.assertIsNone(instance_device.device_id)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertEqual(instance_device.draft_device_model_id, self.device_model.pk)
        self.assertEqual(instance_device.draft_device_type_id, self.device_type.pk)

    def test_system_fields_are_persisted_on_instance_device(self):
        _, fields = self.create_device_group()
        diff = self.build_diff(
            devices=[self.row(fields={
                fields[FormField.SystemKey.IMEI].code: "",
                fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
                fields[FormField.SystemKey.REPORTED_PROBLEM].code: "Broken screen",
                fields[FormField.SystemKey.DESCRIPTION].code: "Customer reported damage",
                fields[FormField.SystemKey.WARRANTY_STATUS].code: "VALID",
                fields[FormField.SystemKey.STATUS].code: "RECEIVED",
            })],
        )
        created = FormDraftDeviceCreateApplyService.apply(
            instance=self.instance, diff=diff,
        )
        instance_device = next(iter(created.values())).instance_device
        self.assertEqual(instance_device.reported_problem, "Broken screen")
        self.assertEqual(instance_device.description, "Customer reported damage")
        self.assertEqual(instance_device.warranty_status, "VALID")
        self.assertEqual(instance_device.status, "RECEIVED")

    def test_model_and_type_must_match(self):
        other_type = DeviceType.objects.create(name="Laptop", code="LAPTOP", is_active=True)
        group, fields = self.create_device_group()
        diff = self.build_diff(
            devices=[self.row(fields={
                fields[FormField.SystemKey.IMEI].code: "",
                fields[FormField.SystemKey.DEVICE_TYPE].code: other_type.pk,
                fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
            })],
        )
        with self.assertRaises(ValidationError):
            FormDraftDeviceCreateApplyService.apply(instance=self.instance, diff=diff)
        self.assertFalse(RepeatableRow.objects.filter(instance=self.instance, group=group).exists())
        self.assertFalse(InstanceDevice.objects.filter(instance=self.instance).exists())

    def test_existing_device_with_mismatched_model_is_rejected(self):
        group, fields = self.create_device_group()
        other_model = DeviceModel.objects.create(
            device_type=self.device_type,
            brand="Test",
            name="Phone Y",
            code="PHONE_Y",
            is_active=True,
        )
        device = Device.objects.create(device_model=self.device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="333333333333333",
        )
        diff = self.build_diff(
            devices=[self.row(fields={
                fields[FormField.SystemKey.IMEI].code: "333333333333333",
                fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                fields[FormField.SystemKey.DEVICE_MODEL].code: other_model.pk,
            })],
        )
        with self.assertRaises(ValidationError):
            FormDraftDeviceCreateApplyService.apply(instance=self.instance, diff=diff)
        self.assertFalse(RepeatableRow.objects.filter(instance=self.instance, group=group).exists())

    def test_same_device_cannot_be_added_twice_to_instance(self):
        group, fields = self.create_device_group()
        device = Device.objects.create(device_model=self.device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="444444444444444",
        )
        InstanceDevice.objects.create(instance=self.instance, device=device)
        diff = self.build_diff(
            devices=[self.row(fields={
                fields[FormField.SystemKey.IMEI].code: "444444444444444",
                fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
            })],
        )
        with self.assertRaises(ValidationError):
            FormDraftDeviceCreateApplyService.apply(instance=self.instance, diff=diff)
        self.assertFalse(RepeatableRow.objects.filter(instance=self.instance, group=group).exists())

    def test_create_is_atomic_when_second_row_has_invalid_model(self):
        group, fields = self.create_device_group()
        invalid_model_id = 999999999
        diff = self.build_diff(
            devices=[
                self.row(fields={
                    fields[FormField.SystemKey.IMEI].code: "555555555555555",
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                    fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
                }),
                self.row(fields={
                    fields[FormField.SystemKey.IMEI].code: "",
                    fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
                    fields[FormField.SystemKey.DEVICE_MODEL].code: invalid_model_id,
                }),
            ],
        )
        with self.assertRaises(ValidationError):
            FormDraftDeviceCreateApplyService.apply(instance=self.instance, diff=diff)
        self.assertEqual(
            RepeatableRow.objects.filter(instance=self.instance, group=group).count(), 0,
        )
        self.assertEqual(InstanceDevice.objects.filter(instance=self.instance).count(), 0)

    def test_nested_device_create_uses_existing_parent_row(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parent",
            code="parents",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            order=1,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
            row_order=0,
        )
        child_group, fields = self.create_device_group(
            code="devices",
            parent_group=parent_group,
            order=2,
        )

        desired_row = self.row(fields={
            fields[FormField.SystemKey.IMEI].code: "",
            fields[FormField.SystemKey.DEVICE_TYPE].code: self.device_type.pk,
            fields[FormField.SystemKey.DEVICE_MODEL].code: self.device_model.pk,
        })
        change = RowChange(
            action=RowChangeAction.CREATE,
            group=child_group,
            row_id=None,
            desired_row=desired_row,
            row_reference=RowReference(
                kind=RowReferenceKind.CREATE,
                value="child-create",
            ),
            parent_reference=RowReference(
                kind=RowReferenceKind.EXISTING,
                value=parent_row.pk,
            ),
        )
        diff = FormDraftDiff(
            groups=(
                RepeatableGroupDiff(
                    group=child_group,
                    changes=(change,),
                ),
            ),
        )

        created = FormDraftDeviceCreateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        child_row = next(iter(created.values()))
        self.assertEqual(child_row.parent_row_id, parent_row.pk)
        self.assertIsNotNone(child_row.instance_device_id)
