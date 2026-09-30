import json

from django.test import RequestFactory, TestCase

from workflow.formula_admin import FormulaFieldAdminForm
from workflow.formula_services import FormulaService
from accounts.models import User
from operator_panel.formula_views import formula_field_options
from workflow.models import FormDefinition, FormField, FormRepeatableGroup, FormSection, Workflow


def formula_config(tokens, decimal_places=2):
    return json.dumps({
        "version": 2,
        "decimal_places": decimal_places,
        "tokens": tokens,
    })


class FormulaFieldAdminFormTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Formula Admin Workflow",
            code="FORMULA_ADMIN",
            is_active=True,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Formula Admin Form",
            is_active=True,
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Devices",
            code="DEVICES",
            order=1,
            is_active=True,
        )
        self.device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            order=1,
            is_active=True,
        )
        self.child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.device_group,
            name="Parts",
            code="parts",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            order=2,
            is_active=True,
        )
        self.sibling_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Other",
            code="other",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            order=3,
            is_active=True,
        )
        self.amount = FormField.objects.create(
            section=self.section,
            repeatable_group=self.child_group,
            name="Amount",
            code="amount",
            field_type=FormField.FieldType.NUMBER,
            label="Amount",
            order=1,
            is_active=True,
        )
        self.sibling_amount = FormField.objects.create(
            section=self.section,
            repeatable_group=self.sibling_group,
            name="Other Amount",
            code="other_amount",
            field_type=FormField.FieldType.NUMBER,
            label="Other Amount",
            order=1,
            is_active=True,
        )

    def _data(self, *, tokens):
        return {
            "section": str(self.section.pk),
            "repeatable_group": str(self.device_group.pk),
            "field_type": FormulaService.FIELD_TYPE,
            "name": "Parts Total",
            "code": "parts_total",
            "label": "Parts Total",
            "order": "2",
            "is_active": "on",
            "calendar": FormField.Calendar.GREGORIAN,
            "choice_source": FormField.ChoiceSource.NONE,
            "decimal_places": "2",
            "system_key": FormField.SystemKey.NONE,
            "formula_builder": json.dumps({
                "version": 2,
                "decimal_places": 0,
                "tokens": tokens,
            }),
            "formula_decimal_places": "0",
        }

    def test_formula_field_options_returns_device_and_descendant_fields_only(self):
        device_amount = FormField.objects.create(
            section=self.section,
            repeatable_group=self.device_group,
            name="Device Amount",
            code="device_amount",
            field_type=FormField.FieldType.NUMBER,
            label="Device Amount",
            order=1,
            is_active=True,
        )

        staff_user = User.objects.create_user(
            username="formula-options-staff",
            password="test-password",
            is_staff=True,
        )
        request = RequestFactory().get(
            "/operator/formula-field-options/",
            {
                "section_id": self.section.pk,
                "group_id": self.device_group.pk,
            },
        )
        request.user = staff_user

        response = formula_field_options(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        option_ids = {item["id"] for item in payload["fields"]}

        self.assertIn(device_amount.pk, option_ids)
        self.assertIn(self.amount.pk, option_ids)
        self.assertNotIn(self.sibling_amount.pk, option_ids)
    def test_device_formula_can_aggregate_descendant_field(self):
        form = FormulaFieldAdminForm(
            data=self._data(
                tokens=[
                    {"type": "function", "value": "SUM"},
                    {"type": "paren", "value": "("},
                    {"type": "field", "field_id": self.amount.pk},
                    {"type": "paren", "value": ")"},
                ]
            )
        )

        self.assertTrue(form.is_valid(), form.errors.as_json())
        options = json.loads(
            form.fields["formula_builder"].widget.attrs["data-field-options"]
        )
        self.assertIn(self.amount.pk, {item["id"] for item in options})
        self.assertNotIn(self.sibling_amount.pk, {item["id"] for item in options})

    def test_device_formula_cannot_use_descendant_field_outside_aggregate(self):
        form = FormulaFieldAdminForm(
            data=self._data(
                tokens=[
                    {"type": "field", "field_id": self.amount.pk},
                ]
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("formula_builder", form.errors)

    def test_device_formula_can_reference_same_group_field_normally(self):
        device_amount = FormField.objects.create(
            section=self.section,
            repeatable_group=self.device_group,
            name="Device Amount",
            code="device_amount",
            field_type=FormField.FieldType.NUMBER,
            label="Device Amount",
            order=1,
            is_active=True,
        )
        form = FormulaFieldAdminForm(
            data=self._data(
                tokens=[
                    {"type": "field", "field_id": device_amount.pk},
                    {"type": "operator", "value": "*"},
                    {"type": "number", "value": "2"},
                ]
            )
        )

        self.assertTrue(form.is_valid(), form.errors.as_json())
