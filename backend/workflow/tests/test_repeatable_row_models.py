from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableRow,
    RepeatableRowValue,
    StaticChoiceItem,
    StaticChoiceSet,
    LookupItem,
    LookupList,
    DeviceType,
    DeviceModel,
    Workflow,
    WorkflowInstance,
)


class RepeatableRowModelTests(TestCase):

    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Test Workflow",
            code="TEST_WORKFLOW",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Test Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Test Section",
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

    def test_root_rows_have_independent_order(self):
        first = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.group,
            row_order=0,
        )
        second = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.group,
            row_order=1,
        )

        self.assertEqual(first.row_order, 0)
        self.assertEqual(second.row_order, 1)

    def test_root_row_order_is_unique_within_instance_and_group(self):
        RepeatableRow.objects.create(
            instance=self.instance,
            group=self.group,
            row_order=0,
        )

        with self.assertRaises(IntegrityError):
            RepeatableRow.objects.create(
                instance=self.instance,
                group=self.group,
                row_order=0,
            )

    def test_instance_device_is_optional_for_row(self):
        row = RepeatableRow(
            instance=self.instance,
            group=self.group,
            row_order=0,
        )

        row.full_clean()
        row.save()

        self.assertIsNone(row.instance_device_id)


class NestedRepeatableModelTests(TestCase):

    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Nested Workflow",
            code="NESTED_WORKFLOW",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Nested Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Nested Section",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )
        self.parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            code="DEVICES",
            order=1,
        )
        self.child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parts",
            code="PARTS",
            order=2,
            parent_group=self.parent_group,
        )

    def test_group_parent_must_be_in_same_section(self):
        other_form = FormDefinition.objects.create(
            workflow=Workflow.objects.create(
                name="Other Workflow",
                code="OTHER_WORKFLOW",
            ),
            name="Other Form",
        )
        other_section = FormSection.objects.create(
            form=other_form,
            name="Other Section",
            order=1,
        )
        invalid = FormRepeatableGroup(
            section=self.section,
            name="Invalid",
            code="INVALID",
            order=3,
            parent_group=FormRepeatableGroup.objects.create(
                section=other_section,
                name="Other Parent",
                code="OTHER_PARENT",
                order=1,
            ),
        )

        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_child_row_must_point_to_parent_group_row(self):
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.parent_group,
            row_order=0,
        )
        child_row = RepeatableRow(
            instance=self.instance,
            group=self.child_group,
            parent_row=parent_row,
            row_order=0,
        )

        child_row.full_clean()
        child_row.save()

        self.assertEqual(child_row.parent_row_id, parent_row.id)

    def test_child_row_cannot_be_root_of_group_without_parent_group(self):
        root_only_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Root Only",
            code="ROOT_ONLY",
            order=3,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.parent_group,
            row_order=0,
        )
        invalid = RepeatableRow(
            instance=self.instance,
            group=root_only_group,
            parent_row=parent_row,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            invalid.full_clean()


class RepeatableRowValueModelTests(TestCase):

    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Value Workflow",
            code="VALUE_WORKFLOW",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Value Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Value Section",
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
        self.row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.group,
            row_order=0,
        )

    def make_field(self, code, field_type):
        return FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name=code,
            code=code,
            label=code,
            field_type=field_type,
            order=FormField.objects.filter(
                section=self.section,
                repeatable_group=self.group,
            ).count(),
        )

    def test_text_value(self):
        field = self.make_field("TECHNICIAN", FormField.FieldType.TEXT)
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            text_value="Ehsan",
        )

        value.full_clean()
        value.save()

        self.assertEqual(value.text_value, "Ehsan")

    def test_number_value(self):
        field = self.make_field("COST", FormField.FieldType.NUMBER)
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            decimal_value=Decimal("1250.50"),
        )

        value.full_clean()
        value.save()

        self.assertEqual(value.decimal_value, Decimal("1250.500000"))

    def test_date_value(self):
        field = self.make_field("REPAIR_DATE", FormField.FieldType.DATE)
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            date_value=date(2026, 9, 21),
        )

        value.full_clean()
        value.save()

        self.assertEqual(value.date_value, date(2026, 9, 21))

    def test_boolean_false_is_a_valid_value(self):
        field = self.make_field("IS_REPAIRED", FormField.FieldType.BOOLEAN)
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            boolean_value=False,
        )

        value.full_clean()
        value.save()

        self.assertFalse(value.boolean_value)

    def test_field_must_belong_to_same_repeatable_group(self):
        other_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Other",
            code="OTHER",
            order=2,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=other_group,
            name="OTHER_FIELD",
            code="OTHER_FIELD",
            label="Other Field",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            text_value="invalid",
        )

        with self.assertRaises(ValidationError):
            value.full_clean()

    def test_select_static_value(self):
        choice_set = StaticChoiceSet.objects.create(
            name="Statuses",
            code="STATUSES",
        )
        choice = StaticChoiceItem.objects.create(
            choice_set=choice_set,
            value="READY",
            label="Ready",
            order=0,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="STATUS",
            code="STATUS",
            label="Status",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.STATIC,
            choice_static_set=choice_set,
            order=0,
        )
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            static_choice_item=choice,
        )

        value.full_clean()
        value.save()

        self.assertEqual(value.static_choice_item_id, choice.id)

    def test_textarea_uses_text_value(self):
        field = self.make_field("NOTES", FormField.FieldType.TEXTAREA)
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            text_value="multi-line note",
        )

        value.full_clean()

    def test_datetime_value(self):
        field = self.make_field("CHECKED_AT", FormField.FieldType.DATETIME)
        from datetime import datetime, timezone

        value = RepeatableRowValue(
            row=self.row,
            field=field,
            datetime_value=datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc),
        )

        value.full_clean()

    def test_select_lookup_value(self):
        lookup_list = LookupList.objects.create(
            name="Priorities",
            code="PRIORITIES",
        )
        item = LookupItem.objects.create(
            lookup_list=lookup_list,
            value="HIGH",
            label="High",
            order=0,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="PRIORITY",
            code="PRIORITY",
            label="Priority",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup_list,
            order=0,
        )
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            lookup_item=item,
        )

        value.full_clean()

    def test_select_model_value_must_exist_in_configured_model(self):
        device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Model X",
            code="MODEL_X",
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="DEVICE_MODEL",
            code="DEVICE_MODEL",
            label="Device Model",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=ContentType.objects.get_for_model(DeviceModel),
            choice_value_field="code",
            choice_label_field="name",
            order=0,
        )

        value = RepeatableRowValue(
            row=self.row,
            field=field,
            reference_id=device_model.code,
        )
        value.full_clean()

    def test_select_model_rejects_unknown_reference(self):
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="DEVICE_MODEL",
            code="DEVICE_MODEL",
            label="Device Model",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=ContentType.objects.get_for_model(DeviceModel),
            choice_value_field="code",
            choice_label_field="name",
            order=0,
        )
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            reference_id="DOES_NOT_EXIST",
        )

        with self.assertRaises(ValidationError):
            value.full_clean()

    def test_select_model_requires_value_field(self):
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="DEVICE_MODEL",
            code="DEVICE_MODEL",
            label="Device Model",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=ContentType.objects.get_for_model(DeviceModel),
            order=0,
        )
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            reference_id="MODEL_X",
        )

        with self.assertRaises(ValidationError):
            value.full_clean()

    def test_select_requires_a_valid_choice_source(self):
        field = self.make_field("STATUS", FormField.FieldType.SELECT)
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            reference_id="ANY",
        )

        with self.assertRaises(ValidationError):
            value.full_clean()

    def test_system_field_cannot_be_stored_as_row_value(self):
        field = self.make_field("IMEI", FormField.FieldType.TEXT)
        field.system_key = FormField.SystemKey.IMEI
        field.save(update_fields=["system_key"])

        value = RepeatableRowValue(
            row=self.row,
            field=field,
            text_value="123456789012345",
        )

        with self.assertRaises(ValidationError):
            value.full_clean()

    def test_file_and_formula_types_are_not_supported_as_row_values(self):
        for field_type in ("FILE", "FORMULA"):
            field = self.make_field(f"FIELD_{field_type}", field_type)
            value = RepeatableRowValue(
                row=self.row,
                field=field,
                text_value="invalid",
            )

            with self.assertRaises(ValidationError):
                value.full_clean()

    def test_only_one_value_is_allowed_for_a_field(self):
        field = self.make_field("DESCRIPTION", FormField.FieldType.TEXT)
        value = RepeatableRowValue(
            row=self.row,
            field=field,
            text_value="valid",
            decimal_value=Decimal("10"),
        )

        with self.assertRaises(ValidationError):
            value.full_clean()

    def test_row_and_field_are_unique(self):
        field = self.make_field("DESCRIPTION", FormField.FieldType.TEXT)
        RepeatableRowValue.objects.create(
            row=self.row,
            field=field,
            text_value="first",
        )

        with self.assertRaises(IntegrityError):
            RepeatableRowValue.objects.create(
                row=self.row,
                field=field,
                text_value="second",
            )
