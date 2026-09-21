from decimal import Decimal
from datetime import date, datetime, timezone

from django.core.exceptions import ValidationError
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
from workflow.repeatable_row_services import RepeatableRowService


class RepeatableRowServiceTests(TestCase):

    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Service Workflow",
            code="SERVICE_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Service Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Service Section",
            code="SERVICE",
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

    def test_create_row_auto_assigns_order(self):
        first = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )
        second = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

        self.assertEqual(first.row_order, 0)
        self.assertEqual(second.row_order, 1)

    def test_create_row_respects_explicit_order(self):
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
            row_order=7,
        )

        self.assertEqual(row.row_order, 7)

    def test_create_child_row_requires_matching_parent_group(self):
        parent_group = self.group
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Children",
            code="CHILDREN",
            order=2,
            parent_group=parent_group,
        )
        parent = RepeatableRowService.create_row(
            instance=self.instance,
            group=parent_group,
        )

        child = RepeatableRowService.create_row(
            instance=self.instance,
            group=child_group,
            parent_row=parent,
        )

        self.assertEqual(child.parent_row_id, parent.id)

    def test_create_row_rejects_parent_from_another_instance(self):
        other_instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )
        parent = RepeatableRowService.create_row(
            instance=other_instance,
            group=self.group,
        )

        with self.assertRaises(ValidationError):
            RepeatableRowService.create_row(
                instance=self.instance,
                group=self.group,
                parent_row=parent,
            )

    def test_get_rows_is_ordered_and_scoped_to_parent(self):
        parent_group = self.group
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Children",
            code="CHILDREN",
            order=2,
            parent_group=parent_group,
        )
        parent_a = RepeatableRowService.create_row(
            instance=self.instance,
            group=parent_group,
        )
        parent_b = RepeatableRowService.create_row(
            instance=self.instance,
            group=parent_group,
        )
        child_b = RepeatableRowService.create_row(
            instance=self.instance,
            group=child_group,
            parent_row=parent_b,
            row_order=0,
        )
        child_a = RepeatableRowService.create_row(
            instance=self.instance,
            group=child_group,
            parent_row=parent_a,
            row_order=0,
        )

        rows = list(
            RepeatableRowService.get_rows(
                instance=self.instance,
                group=child_group,
                parent_row=parent_b,
            )
        )

        self.assertEqual(rows, [child_b])
        self.assertNotIn(child_a, rows)

    def test_update_row_changes_parent_and_order(self):
        parent_group = self.group
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Children",
            code="CHILDREN",
            order=2,
            parent_group=parent_group,
        )
        parent_a = RepeatableRowService.create_row(
            instance=self.instance,
            group=parent_group,
        )
        parent_b = RepeatableRowService.create_row(
            instance=self.instance,
            group=parent_group,
        )
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=child_group,
            parent_row=parent_a,
        )

        updated = RepeatableRowService.update_row(
            row=row,
            parent_row=parent_b,
            row_order=4,
        )

        self.assertEqual(updated.parent_row_id, parent_b.id)
        self.assertEqual(updated.row_order, 4)

    def test_set_text_value(self):
        field = self.make_field("NAME", FormField.FieldType.TEXT)

        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )
        value = RepeatableRowService.set_value(
            row=row,
            field=field,
            value="Ehsan",
        )

        self.assertEqual(value.text_value, "Ehsan")
        self.assertEqual(
            RepeatableRowValue.objects.count(),
            1,
        )

    def test_set_value_updates_existing_value_instead_of_creating_duplicate(self):
        field = self.make_field("NAME", FormField.FieldType.TEXT)
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

        first = RepeatableRowService.set_value(
            row=row,
            field=field,
            value="First",
        )
        second = RepeatableRowService.set_value(
            row=row,
            field=field,
            value="Second",
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=row,
                field=field,
            ).text_value,
            "Second",
        )

    def test_set_number_value(self):
        field = self.make_field("COST", FormField.FieldType.NUMBER)
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

        value = RepeatableRowService.set_value(
            row=row,
            field=field,
            value="1250.50",
        )

        self.assertEqual(value.decimal_value, Decimal("1250.500000"))

    def test_set_boolean_false(self):
        field = self.make_field("ACTIVE", FormField.FieldType.BOOLEAN)
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

        value = RepeatableRowService.set_value(
            row=row,
            field=field,
            value=False,
        )

        self.assertFalse(value.boolean_value)

    def test_set_static_select_value(self):
        choice_set = StaticChoiceSet.objects.create(
            name="Statuses",
            code="SERVICE_STATUS",
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
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

        value = RepeatableRowService.set_value(
            row=row,
            field=field,
            value="READY",
        )

        self.assertEqual(value.static_choice_item_id, choice.id)

    def test_set_lookup_select_value(self):
        lookup_list = LookupList.objects.create(
            name="Priorities",
            code="SERVICE_PRIORITY",
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
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

        value = RepeatableRowService.set_value(
            row=row,
            field=field,
            value="HIGH",
        )

        self.assertEqual(value.lookup_item_id, item.id)

    def test_set_model_select_value(self):
        from django.contrib.contenttypes.models import ContentType
        from workflow.models import DeviceModel, DeviceType

        device_type = DeviceType.objects.create(
            name="Phone",
            code="SERVICE_PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Model X",
            code="SERVICE_MODEL_X",
        )
        field = self.make_field(
            "DEVICE_MODEL",
            FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=ContentType.objects.get_for_model(DeviceModel),
            choice_value_field="code",
            choice_label_field="name",
        )
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

        value = RepeatableRowService.set_value(
            row=row,
            field=field,
            value=device_model.code,
        )

        self.assertEqual(value.reference_id, device_model.code)

    def test_set_value_rejects_field_from_another_group(self):
        other_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Other",
            code="OTHER",
            order=2,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=other_group,
            name="OTHER",
            code="OTHER",
            label="Other",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )

        with self.assertRaises(ValidationError):
            RepeatableRowService.set_value(
                row=row,
                field=field,
                value="invalid",
            )

    def test_remove_value(self):
        field = self.make_field("NAME", FormField.FieldType.TEXT)
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )
        RepeatableRowService.set_value(
            row=row,
            field=field,
            value="Ehsan",
        )

        self.assertTrue(
            RepeatableRowService.remove_value(
                row=row,
                field=field,
            )
        )
        self.assertFalse(
            RepeatableRowValue.objects.filter(
                row=row,
                field=field,
            ).exists()
        )
        self.assertFalse(
            RepeatableRowService.remove_value(
                row=row,
                field=field,
            )
        )

    def test_delete_row_removes_values(self):
        field = self.make_field("NAME", FormField.FieldType.TEXT)
        row = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )
        RepeatableRowService.set_value(
            row=row,
            field=field,
            value="Ehsan",
        )

        RepeatableRowService.delete_row(row=row)

        self.assertFalse(
            RepeatableRow.objects.filter(pk=row.pk).exists()
        )
        self.assertFalse(
            RepeatableRowValue.objects.filter(row_id=row.pk).exists()
        )

    def test_delete_row_rejects_rows_with_children(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Children",
            code="CHILDREN",
            order=2,
            parent_group=self.group,
        )
        parent = RepeatableRowService.create_row(
            instance=self.instance,
            group=self.group,
        )
        RepeatableRowService.create_row(
            instance=self.instance,
            group=child_group,
            parent_row=parent,
        )

        with self.assertRaises(ValidationError):
            RepeatableRowService.delete_row(row=parent)
