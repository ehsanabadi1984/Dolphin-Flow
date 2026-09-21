from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    LookupItem,
    LookupList,
    RepeatableRow,
    RepeatableRowValue,
    StaticChoiceItem,
    StaticChoiceSet,
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
