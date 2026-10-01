import json

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.form_services import DynamicFormService
from workflow.models import (
    FieldAccess,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableGroupAccess,
    RepeatableRow,
    RepeatableRowValue,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)


User = get_user_model()


class NestedRepeatableFormulaPresentationTests(TestCase):
    """Regression coverage for calculated Formula values in nested TABLE rows."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="nested_formula_presentation_user",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="Nested Formula Presentation Test",
            code="NESTED_FORMULA_PRESENTATION_TEST",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Formula Step",
            code="FORMULA_STEP",
            order=1,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=cls.workflow,
            user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        cls.form = FormDefinition.objects.create(
            workflow=cls.workflow,
            name="Nested Formula Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Nested Formula Section",
            code="NESTED_FORMULA_SECTION",
            order=1,
            is_active=True,
        )

        cls.parent_group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Parent Table",
            code="parent_table",
            order=1,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )

        cls.child_group = FormRepeatableGroup.objects.create(
            section=cls.section,
            parent_group=cls.parent_group,
            name="Child Table",
            code="child_table",
            order=2,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )

        cls.parent_value_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.parent_group,
            name="Parent Value",
            code="parent_value",
            field_type=FormField.FieldType.NUMBER,
            label="Parent Value",
            order=1,
            is_active=True,
        )

        cls.child_input_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.child_group,
            name="Child Amount",
            code="child_amount",
            field_type=FormField.FieldType.NUMBER,
            label="Child Amount",
            order=1,
            is_active=True,
        )

        cls.child_formula_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.child_group,
            name="Child Total",
            code="child_total",
            field_type=FormField.FieldType.FORMULA,
            label="Child Total",
            order=2,
            is_active=True,
            choices={
                "version": 2,
                "tokens": [
                    {
                        "type": "field",
                        "field_id": cls.child_input_field.pk,
                    },
                    {
                        "type": "operator",
                        "value": "*",
                    },
                    {
                        "type": "number",
                        "value": "2",
                    },
                ],
                "decimal_places": 2,
            },
        )

        for group in (cls.parent_group, cls.child_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=cls.step,
                role=WorkflowMembership.Role.EXECUTOR,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )

        for field in (
            cls.parent_value_field,
            cls.child_input_field,
            cls.child_formula_field,
        ):
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                role=WorkflowMembership.Role.EXECUTOR,
                can_view=True,
                can_edit=True,
            )

    def test_nested_child_table_formula_value_survives_presentation_build(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            status=WorkflowInstance.Status.ACTIVE,
        )

        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step,
            performed_by=self.user,
        )

        parent_row = RepeatableRow.objects.create(
            instance=instance,
            group=self.parent_group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=parent_row,
            field=self.parent_value_field,
            decimal_value=Decimal("10"),
        )

        child_row = RepeatableRow.objects.create(
            instance=instance,
            group=self.child_group,
            parent_row=parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=self.child_input_field,
            decimal_value=Decimal("750"),
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=False,
        )

        parent_context = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].pk == self.parent_group.pk
        )
        child_context = next(
            child
            for child in parent_context["items"][0]["child_groups"]
            if child["group"].pk == self.child_group.pk
        )

        child_fields = {
            item["field"].code: item
            for item in child_context["items"][0]["fields"]
        }

        self.assertEqual(
            child_fields["child_amount"]["value"],
            "750",
        )

        # Formula values are calculated on read and are intentionally not
        # persisted in RepeatableRowValue. The presentation layer must still
        # receive the calculated value for the child TABLE row.
        self.assertEqual(
            child_fields["child_total"]["value"],
            "1500.00",
        )
        self.assertEqual(
            child_fields["child_total"]["display_value"],
            "1500.00",
        )

        child_flat_table = child_context["flat_table"]
        child_formula_cell = next(
            cell
            for cell in child_flat_table["rows"][0]["column_cells"]
            if cell["field"].code == "child_total"
        )

        self.assertEqual(
            child_formula_cell["value"],
            "1500.00",
        )
        self.assertEqual(
            child_formula_cell["display_value"],
            "1500.00",
        )
