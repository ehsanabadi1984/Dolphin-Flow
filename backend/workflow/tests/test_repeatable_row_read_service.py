from decimal import Decimal
from datetime import date, datetime, timezone

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from workflow.models import (
    DeviceModel,
    DeviceType,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    LookupItem,
    LookupList,
    RepeatableRow,
    RepeatableRowValue,
    StaticChoiceItem,
    StaticChoiceSet,
    Workflow,
    WorkflowInstance,
)
from workflow.repeatable_row_services import RepeatableRowService
from workflow.repeatable_row_read_services import RepeatableRowReadService


class RepeatableRowReadServiceTests(TestCase):

    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Read Workflow",
            code="READ_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Read Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Read Section",
            code="READ",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )
        self.group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="ITEMS",
            order=1,
        )

    def make_field(self, code, field_type, **kwargs):
        return FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name=code,
            code=code,
            label=code,
            field_type=field_type,
            order=FormField.objects.filter(
                repeatable_group=self.group,
            ).count(),
            **kwargs,
        )

    def make_row(self):
        return RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

    def test_reconstruct_row_returns_fields_in_definition_order(self):
        name = self.make_field("NAME", FormField.FieldType.TEXT)
        cost = self.make_field("COST", FormField.FieldType.NUMBER)

        row = self.make_row()
        RepeatableRowService.set_value(
            row=row,
            field=cost,
            value="12.5",
        )
        RepeatableRowService.set_value(
            row=row,
            field=name,
            value="Ehsan",
        )

        result = RepeatableRowReadService.reconstruct_row(row=row)

        self.assertEqual(
            [item["code"] for item in result["fields"]],
            ["NAME", "COST"],
        )
        self.assertEqual(result["fields"][0]["value"], "Ehsan")
        self.assertEqual(
            result["fields"][1]["value"],
            Decimal("12.500000"),
        )

    def test_missing_value_is_reconstructed_as_empty_value(self):
        field = self.make_field("NAME", FormField.FieldType.TEXT)
        row = self.make_row()

        result = RepeatableRowReadService.reconstruct_row(row=row)

        self.assertIsNone(result["fields"][0]["value"])
        self.assertEqual(result["fields"][0]["display_value"], "")

    def test_boolean_false_is_not_lost(self):
        field = self.make_field("ACTIVE", FormField.FieldType.BOOLEAN)
        row = self.make_row()
        RepeatableRowService.set_value(
            row=row,
            field=field,
            value=False,
        )

        result = RepeatableRowReadService.reconstruct_row(row=row)

        self.assertFalse(result["fields"][0]["value"])
        self.assertEqual(result["fields"][0]["display_value"], "خیر")

    def test_static_select_reconstructs_value_and_label(self):
        choice_set = StaticChoiceSet.objects.create(
            name="Statuses",
            code="READ_STATUS",
        )
        choice = StaticChoiceItem.objects.create(
            choice_set=choice_set,
            value="READY",
            label="Ready",
            order=0,
        )
        field = self.make_field(
            "STATUS",
            FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.STATIC,
            choice_static_set=choice_set,
        )
        row = self.make_row()
        RepeatableRowService.set_value(
            row=row,
            field=field,
            value="READY",
        )

        result = RepeatableRowReadService.reconstruct_row(row=row)

        self.assertEqual(result["fields"][0]["value"], "READY")
        self.assertEqual(result["fields"][0]["display_value"], "Ready")

    def test_lookup_select_reconstructs_value_and_label(self):
        lookup_list = LookupList.objects.create(
            name="Priorities",
            code="READ_PRIORITY",
        )
        item = LookupItem.objects.create(
            lookup_list=lookup_list,
            value="HIGH",
            label="High",
            order=0,
        )
        field = self.make_field(
            "PRIORITY",
            FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup_list,
        )
        row = self.make_row()
        RepeatableRowService.set_value(
            row=row,
            field=field,
            value="HIGH",
        )

        result = RepeatableRowReadService.reconstruct_row(row=row)

        self.assertEqual(result["fields"][0]["value"], "HIGH")
        self.assertEqual(result["fields"][0]["display_value"], "High")

    def test_model_select_reconstructs_reference_and_label(self):
        device_type = DeviceType.objects.create(
            name="Phone",
            code="READ_PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Model X",
            code="READ_MODEL_X",
        )
        field = self.make_field(
            "MODEL",
            FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=ContentType.objects.get_for_model(DeviceModel),
            choice_value_field="code",
            choice_label_field="name",
        )
        row = self.make_row()
        RepeatableRowService.set_value(
            row=row,
            field=field,
            value=device_model.code,
        )

        result = RepeatableRowReadService.reconstruct_row(row=row)

        self.assertEqual(
            result["fields"][0]["value"],
            device_model.code,
        )
        self.assertEqual(
            result["fields"][0]["display_value"],
            "Model X",
        )

    def test_device_row_reconstructs_system_fields_from_instance_device(self):
        device_type = DeviceType.objects.create(
            name="Phone",
            code="READ_DEVICE_PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Model X",
            code="READ_DEVICE_MODEL",
        )
        from workflow.models import Device, DeviceIdentifier

        device = Device.objects.create(
            device_model=device_model,
        )
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="123456789",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
            reported_problem="Broken screen",
            description="Customer report",
            warranty_status="VALID",
            status="RECEIVED",
        )
        device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            code="DEVICES",
            order=2,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        for code, system_key, field_type in (
            ("IMEI", FormField.SystemKey.IMEI, FormField.FieldType.TEXT),
            ("TYPE", FormField.SystemKey.DEVICE_TYPE, FormField.FieldType.SELECT),
            ("MODEL", FormField.SystemKey.DEVICE_MODEL, FormField.FieldType.SELECT),
            ("PROBLEM", FormField.SystemKey.REPORTED_PROBLEM, FormField.FieldType.TEXTAREA),
            ("DESC", FormField.SystemKey.DESCRIPTION, FormField.FieldType.TEXTAREA),
            ("WARRANTY", FormField.SystemKey.WARRANTY_STATUS, FormField.FieldType.TEXT),
            ("STATUS", FormField.SystemKey.STATUS, FormField.FieldType.TEXT),
        ):
            FormField.objects.create(
                section=self.section,
                repeatable_group=device_group,
                name=code,
                code=code,
                label=code,
                field_type=field_type,
                system_key=system_key,
                order=FormField.objects.filter(
                    repeatable_group=device_group,
                ).count(),
            )

        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=device_group,
            instance_device=instance_device,
        )

        result = RepeatableRowReadService.reconstruct_row(row=row)
        values = {
            item["code"]: item
            for item in result["fields"]
        }

        self.assertEqual(values["IMEI"]["value"], "123456789")
        self.assertEqual(values["TYPE"]["value"], device_type.pk)
        self.assertEqual(values["TYPE"]["display_value"], str(device_type))
        self.assertEqual(values["MODEL"]["value"], device_model.pk)
        self.assertEqual(values["MODEL"]["display_value"], str(device_model))
        self.assertEqual(values["PROBLEM"]["value"], "Broken screen")
        self.assertEqual(values["DESC"]["value"], "Customer report")
        self.assertEqual(values["WARRANTY"]["value"], "VALID")
        self.assertEqual(values["STATUS"]["value"], "RECEIVED")

    def test_draft_device_reconstructs_draft_identity(self):
        device_type = DeviceType.objects.create(
            name="Phone",
            code="READ_DRAFT_PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Draft Model",
            code="READ_DRAFT_MODEL",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_imei="987654321",
            draft_device_type=device_type,
            draft_device_model=device_model,
        )
        device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Draft Devices",
            code="DRAFT_DEVICES",
            order=2,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        type_field = FormField.objects.create(
            section=self.section,
            repeatable_group=device_group,
            name="TYPE",
            code="TYPE",
            label="TYPE",
            field_type=FormField.FieldType.SELECT,
            system_key=FormField.SystemKey.DEVICE_TYPE,
            order=0,
        )
        model_field = FormField.objects.create(
            section=self.section,
            repeatable_group=device_group,
            name="MODEL",
            code="MODEL",
            label="MODEL",
            field_type=FormField.FieldType.SELECT,
            system_key=FormField.SystemKey.DEVICE_MODEL,
            order=1,
        )
        imei_field = FormField.objects.create(
            section=self.section,
            repeatable_group=device_group,
            name="IMEI",
            code="IMEI",
            label="IMEI",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.IMEI,
            order=2,
        )

        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=device_group,
            instance_device=instance_device,
        )

        result = RepeatableRowReadService.reconstruct_row(row=row)
        values = {item["code"]: item for item in result["fields"]}

        self.assertEqual(values["IMEI"]["value"], "987654321")
        self.assertEqual(values["TYPE"]["value"], device_type.pk)
        self.assertEqual(values["MODEL"]["value"], device_model.pk)

    def test_reconstruct_group_reconstructs_rows_in_order(self):
        field = self.make_field("NAME", FormField.FieldType.TEXT)
        first = self.make_row()
        second = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
            row_order=1,
        )
        RepeatableRowService.set_value(
            row=first,
            field=field,
            value="First",
        )
        RepeatableRowService.set_value(
            row=second,
            field=field,
            value="Second",
        )

        result = RepeatableRowReadService.reconstruct_group(
            instance=self.instance,
            group=self.group,
        )

        self.assertEqual(
            [item["row_order"] for item in result["items"]],
            [0, 1],
        )
        self.assertEqual(
            result["items"][0]["fields"][0]["value"],
            "First",
        )

    def test_reconstruct_instance_rebuilds_nested_group_tree(self):
        parent_group = self.group
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parts",
            code="PARTS",
            order=2,
            parent_group=parent_group,
        )
        grandchild_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Checks",
            code="CHECKS",
            order=3,
            parent_group=child_group,
        )
        parent = self.make_row()
        child = RepeatableRowService.create_row(
            instance=self.instance,
            group=child_group,
            parent_row=parent,
        )
        grandchild = RepeatableRowService.create_row(
            instance=self.instance,
            group=grandchild_group,
            parent_row=child,
        )

        result = RepeatableRowReadService.reconstruct_instance(
            instance=self.instance,
        )

        root = next(
            group
            for group in result["groups"]
            if group["code"] == "ITEMS"
        )
        self.assertEqual(
            root["items"][0]["row_id"],
            parent.pk,
        )
        self.assertEqual(
            root["child_groups"][0]["code"],
            "PARTS",
        )
        self.assertEqual(
            root["child_groups"][0]["items"][0]["row_id"],
            child.pk,
        )
        self.assertEqual(
            root["child_groups"][0]["child_groups"][0]["code"],
            "CHECKS",
        )
        self.assertEqual(
            root["child_groups"][0]["child_groups"][0]["items"][0]["row_id"],
            grandchild.pk,
        )

    def test_get_rows_rejects_parent_from_another_instance(self):
        other_instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )
        parent = self.make_row()

        with self.assertRaises(Exception):
            RepeatableRowReadService.get_rows(
                instance=other_instance,
                group=self.group,
                parent_row=parent,
            )
