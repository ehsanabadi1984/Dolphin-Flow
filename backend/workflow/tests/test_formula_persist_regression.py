"""
Regression tests for Formula persistence across the real dynamic-form save path.

Scenario under test (mirrors the live repair form configuration):

    repeatable NORMAL group ``cunspartTable``
        quantity   NUMBER
        UnitPrice  NUMBER
        TotalPrice FORMULA = quantity * UnitPrice   (decimal_places=0)

    top-level FORMULA field ``FinalPriceRepair``
        FinalPriceRepair = SUM(cunspartTable.TotalPrice)  (decimal_places=2)

The browser submits every row including the calculated ``TotalPrice`` and
``FinalPriceRepair`` values.  The server must:

  * ignore the client-supplied formula values (never authoritative),
  * derive formula values server-side from the raw inputs,
  * persist the derived values into ``FormData.data``,
  * render the derived values again on read-only and edit GET.

The tests drive the real save path (DynamicFormService.save_form_for_step
with the formula bootstrap applied) and assert the persisted JSON.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.form_services import DynamicFormService
from workflow.formula_bootstrap import bootstrap_formula_system
from workflow.formula_services import FormulaService
from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)

User = get_user_model()


def formula_config(*, tokens, decimal_places=2):
    return json.dumps({
        "version": 2,
        "decimal_places": decimal_places,
        "tokens": tokens,
    })


class FormulaPersistenceTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        bootstrap_formula_system()

        cls.user = User.objects.create_user(username="formula_user", password="p")

        cls.workflow = Workflow.objects.create(
            name="Repair",
            code="REPAIR_FORMULA",
            is_active=True,
        )
        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step 1",
            code="STEP1",
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
            name="Repair Form",
            is_active=True,
        )
        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Repair Table",
            code="REPAIR_TABLE",
            order=1,
            is_active=True,
        )
        cls.final_section = FormSection.objects.create(
            form=cls.form,
            name="Final",
            code="FINAL",
            order=2,
            is_active=True,
        )

        # A plain normal field that must be unaffected by formula logic.
        cls.note_field = FormField.objects.create(
            section=cls.final_section,
            name="Note",
            code="note",
            field_type=FormField.FieldType.TEXT,
            label="یادداشت",
            order=0,
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="cunspartTable",
            code="cunspartTable",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            order=0,
            is_active=True,
        )
        cls.qty = FormField.objects.create(
            section=cls.section, repeatable_group=cls.group,
            name="quantity", code="quantity",
            field_type=FormField.FieldType.NUMBER,
            label="تعداد", order=0, is_active=True,
        )
        cls.price = FormField.objects.create(
            section=cls.section, repeatable_group=cls.group,
            name="UnitPrice", code="UnitPrice",
            field_type=FormField.FieldType.NUMBER,
            label="قیمت واحد", order=1, is_active=True,
        )
        cls.total = FormField.objects.create(
            section=cls.section, repeatable_group=cls.group,
            name="TotalPrice", code="TotalPrice",
            field_type=FormulaService.FIELD_TYPE,
            label="قیمت کل", order=2, is_active=True,
            choices=formula_config(tokens=[
                {"type": "field", "field_id": cls.qty.pk},
                {"type": "operator", "value": "*"},
                {"type": "field", "field_id": cls.price.pk},
            ], decimal_places=0),
        )
        cls.final = FormField.objects.create(
            section=cls.final_section,
            name="FinalPriceRepair", code="FinalPriceRepair",
            field_type=FormulaService.FIELD_TYPE,
            label="قیمت نهایی", order=1, is_active=True,
            choices=formula_config(tokens=[
                {"type": "function", "value": "SUM"},
                {"type": "paren", "value": "("},
                {"type": "field", "field_id": cls.total.pk},
                {"type": "paren", "value": ")"},
            ], decimal_places=2),
        )

        for field, edit in (
            (cls.note_field, True),
            (cls.qty, True),
            (cls.price, True),
            (cls.total, False),
            (cls.final, False),
        ):
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                role=WorkflowMembership.Role.EXECUTOR,
                can_view=True,
                can_edit=edit,
            )
        RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

    def make_instance(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            status=WorkflowInstance.Status.ACTIVE,
            started_by=self.user,
        )
        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step,
            performed_by=self.user,
        )
        return instance

    def post_payload(self, rows, note="", include_formula_values=True):
        """Build the POST dict exactly like the browser would submit it."""
        data = {}
        for idx, row in enumerate(rows):
            if row.get("_id"):
                data[f"cunspartTable_{idx}__id"] = row["_id"]
            for code in ("quantity", "UnitPrice", "TotalPrice"):
                if code == "TotalPrice" and not include_formula_values:
                    continue
                data[f"cunspartTable_{idx}_{code}"] = row.get(code, "")
        if note is not None:
            data["note"] = note
        if include_formula_values and rows:
            total = sum(
                int(row.get("quantity") or 0) * int(row.get("UnitPrice") or 0)
                for row in rows
            )
            data["FinalPriceRepair"] = f"{total}.00"
        return data

    def save_rows(self, rows, note=""):
        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload(rows, note=note),
        )
        return instance

    def persisted_rows(self, instance):
        fd = FormData.objects.get(instance=instance)
        return fd.data

    # --------------------------------------------------------------
    # Main regression: the reported scenario survives the real save
    # --------------------------------------------------------------

    def test_first_save_persists_server_derived_formula_values(self):
        instance = self.save_rows([
            {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
            {"quantity": "50", "UnitPrice": "50", "TotalPrice": "2500"},
            {"quantity": "10", "UnitPrice": "1000", "TotalPrice": "10000"},
        ])
        data = self.persisted_rows(instance)
        rows = data["cunspartTable"]
        self.assertEqual([r["quantity"] for r in rows], ["10", "50", "10"])
        self.assertEqual([r["UnitPrice"] for r in rows], ["500", "50", "1000"])
        self.assertEqual(
            [r["TotalPrice"] for r in rows],
            ["5000", "2500", "10000"],
        )
        self.assertEqual(data["FinalPriceRepair"], "17500.00")

    def test_client_supplied_formula_values_are_never_authoritative(self):
        # Tampered formula values must be replaced by server derivation.
        instance = self.save_rows([
            {"quantity": "10", "UnitPrice": "500", "TotalPrice": "99999"},
            {"quantity": "50", "UnitPrice": "50", "TotalPrice": "99999"},
        ])
        rows = self.persisted_rows(instance)["cunspartTable"]
        self.assertEqual([r["TotalPrice"] for r in rows], ["5000", "2500"])
        self.assertEqual(
            self.persisted_rows(instance)["FinalPriceRepair"],
            "7500.00",
        )

    def test_formula_values_survive_when_not_submitted_in_payload(self):
        # Simulate a client that omits formula values entirely.
        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload(
                [
                    {"quantity": "4", "UnitPrice": "2000", "TotalPrice": ""},
                    {"quantity": "2", "UnitPrice": "100", "TotalPrice": ""},
                ],
                include_formula_values=False,
            ),
        )
        rows = self.persisted_rows(instance)["cunspartTable"]
        self.assertEqual([r["TotalPrice"] for r in rows], ["8000", "200"])
        self.assertEqual(self.persisted_rows(instance)["FinalPriceRepair"], "8200.00")

    # --------------------------------------------------------------
    # Second save / edit semantics (previous_item matters)
    # --------------------------------------------------------------

    def test_second_save_after_editing_quantity_updates_formulas(self):
        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload(
                [
                    {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
                    {"quantity": "50", "UnitPrice": "50", "TotalPrice": "2500"},
                ],
            ),
        )
        rows = self.persisted_rows(instance)["cunspartTable"]
        row_ids = [r["_id"] for r in rows]

        # Second save: keep both rows, edit quantity of row 1 (10 -> 20),
        # change UnitPrice of row 2 (50 -> 60).
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload([
                {"_id": row_ids[0], "quantity": "20", "UnitPrice": "500", "TotalPrice": "10000"},
                {"_id": row_ids[1], "quantity": "50", "UnitPrice": "60", "TotalPrice": "3000"},
            ]),
        )
        data = self.persisted_rows(instance)
        self.assertEqual(data["cunspartTable"][0]["_id"], row_ids[0])
        self.assertEqual(data["cunspartTable"][1]["_id"], row_ids[1])
        self.assertEqual([r["TotalPrice"] for r in data["cunspartTable"]], ["10000", "3000"])
        self.assertEqual(data["FinalPriceRepair"], "13000.00")

    def test_second_save_editing_only_quantity(self):
        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload(
                [
                    {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
                    {"quantity": "3", "UnitPrice": "200", "TotalPrice": "600"},
                ],
            ),
        )
        ids = [r["_id"] for r in self.persisted_rows(instance)["cunspartTable"]]
        # Change only the quantity of the first row.
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload([
                {"_id": ids[0], "quantity": "7", "UnitPrice": "500", "TotalPrice": "3500"},
                {"_id": ids[1], "quantity": "3", "UnitPrice": "200", "TotalPrice": "600"},
            ]),
        )
        data = self.persisted_rows(instance)
        rows = data["cunspartTable"]
        self.assertEqual(rows[0]["quantity"], "7")
        self.assertEqual(rows[0]["TotalPrice"], "3500")
        self.assertEqual(rows[1]["quantity"], "3")
        self.assertEqual(rows[1]["TotalPrice"], "600")
        self.assertEqual(data["FinalPriceRepair"], "4100.00")

    def test_second_save_editing_only_unit_price(self):
        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload(
                [
                    {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
                    {"quantity": "3", "UnitPrice": "200", "TotalPrice": "600"},
                ],
            ),
        )
        ids = [r["_id"] for r in self.persisted_rows(instance)["cunspartTable"]]
        # Change only the unit price of the second row.
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload([
                {"_id": ids[0], "quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
                {"_id": ids[1], "quantity": "3", "UnitPrice": "150", "TotalPrice": "450"},
            ]),
        )
        data = self.persisted_rows(instance)
        rows = data["cunspartTable"]
        self.assertEqual(rows[1]["UnitPrice"], "150")
        self.assertEqual(rows[1]["TotalPrice"], "450")
        self.assertEqual(rows[0]["TotalPrice"], "5000")
        self.assertEqual(data["FinalPriceRepair"], "5450.00")

    def test_second_save_adding_a_new_row(self):
        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload(
                [{"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"}],
            ),
        )
        existing_id = self.persisted_rows(instance)["cunspartTable"][0]["_id"]

        # Keep existing row and append a brand-new row (no _id).
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload([
                {"_id": existing_id, "quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
                {"quantity": "3", "UnitPrice": "200", "TotalPrice": "600"},
            ]),
        )
        data = self.persisted_rows(instance)
        rows = data["cunspartTable"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["_id"], existing_id)
        self.assertEqual([r["TotalPrice"] for r in rows], ["5000", "600"])
        self.assertEqual(data["FinalPriceRepair"], "5600.00")

    def test_second_save_deleting_a_row_updates_aggregate(self):
        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload([
                {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
                {"quantity": "50", "UnitPrice": "50", "TotalPrice": "2500"},
                {"quantity": "10", "UnitPrice": "1000", "TotalPrice": "10000"},
            ]),
        )
        ids = [r["_id"] for r in self.persisted_rows(instance)["cunspartTable"]]

        # Submit only rows 1 and 3 -> row 2 is deleted.
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload([
                {"_id": ids[0], "quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
                {"_id": ids[2], "quantity": "10", "UnitPrice": "1000", "TotalPrice": "10000"},
            ]),
        )
        data = self.persisted_rows(instance)
        self.assertEqual(len(data["cunspartTable"]), 2)
        self.assertEqual(data["FinalPriceRepair"], "15000.00")

    def test_clearing_all_rows_sets_empty_group_and_zero_aggregate(self):
        instance = self.save_rows([
            {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
        ])
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={"note": "x", "FinalPriceRepair": "0.00"},
        )
        data = self.persisted_rows(instance)
        self.assertEqual(data["cunspartTable"], [])
        self.assertEqual(data["FinalPriceRepair"], "0.00")
        self.assertEqual(data["note"], "x")

    # --------------------------------------------------------------
    # Formula on formula + aggregate semantics
    # --------------------------------------------------------------

    def test_row_formula_depending_on_another_row_formula(self):
        # Discounted = TotalPrice - (TotalPrice * 10%) style chain:
        # Vat = TotalPrice * 0.1 computed from the derived TotalPrice row.
        vat = FormField.objects.create(
            section=self.section, repeatable_group=self.group,
            name="Vat", code="Vat",
            field_type=FormulaService.FIELD_TYPE,
            label="مالیات", order=3, is_active=True,
            choices=formula_config(tokens=[
                {"type": "field", "field_id": self.total.pk},
                {"type": "operator", "value": "*"},
                {"type": "number", "value": "0.1"},
            ], decimal_places=2),
        )
        FieldAccess.objects.create(
            field=vat, step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True, can_edit=False,
        )

        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=self.post_payload([
                {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
            ]),
        )
        data = self.persisted_rows(instance)
        row = data["cunspartTable"][0]
        self.assertEqual(row["TotalPrice"], "5000")
        self.assertEqual(row["Vat"], "500.00")

    def test_aggregate_over_group_uses_derived_row_formula_values(self):
        # Reuse the existing FinalPriceRepair = SUM(TotalPrice) formula.
        instance = self.save_rows([
            {"quantity": "2", "UnitPrice": "100", "TotalPrice": "200"},
            {"quantity": "3", "UnitPrice": "400", "TotalPrice": "1200"},
        ])
        self.assertEqual(self.persisted_rows(instance)["FinalPriceRepair"], "1400.00")

    # --------------------------------------------------------------
    # Forms without formulas / non-formula fields
    # --------------------------------------------------------------

    def test_form_without_formula_fields_is_untouched(self):
        workflow = Workflow.objects.create(
            name="Plain", code="PLAIN_NO_FORMULA", is_active=True,
        )
        step = WorkflowStep.objects.create(
            workflow=workflow, name="S", code="S", order=1, is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=workflow, user=self.user,
            role=WorkflowMembership.Role.EXECUTOR, is_active=True,
        )
        form = FormDefinition.objects.create(
            workflow=workflow, name="F", is_active=True,
        )
        section = FormSection.objects.create(
            form=form, name="S", code="S", order=1, is_active=True,
        )
        field = FormField.objects.create(
            section=section, name="city", code="city",
            field_type=FormField.FieldType.TEXT,
            label="شهر", order=1, is_active=True,
        )
        FieldAccess.objects.create(
            field=field, step=step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True, can_edit=True,
        )
        instance = WorkflowInstance.objects.create(
            workflow=workflow, current_step=step,
            status=WorkflowInstance.Status.ACTIVE, started_by=self.user,
        )
        WorkflowStepExecution.objects.create(
            instance=instance, workflow_step=step, performed_by=self.user,
        )
        DynamicFormService.save_form_for_step(
            instance=instance, user=self.user,
            submitted_data={"city": "Tehran"},
        )
        self.assertEqual(
            self.persisted_rows(instance),
            {"city": "Tehran"},
        )

    def test_normal_non_formula_fields_and_rows_preserved(self):
        instance = self.make_instance()
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "note": "hello",
                "cunspartTable_0_quantity": "10",
                "cunspartTable_0_UnitPrice": "500",
                "cunspartTable_0_TotalPrice": "5000",
                "FinalPriceRepair": "5000.00",
            },
        )
        data = self.persisted_rows(instance)
        self.assertEqual(data["note"], "hello")
        self.assertEqual(data["cunspartTable"][0]["quantity"], "10")

    # --------------------------------------------------------------
    # GET rendering: read-only vs edit contexts
    # --------------------------------------------------------------

    def test_read_only_get_renders_derived_values(self):
        instance = self.save_rows([
            {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
            {"quantity": "50", "UnitPrice": "50", "TotalPrice": "2500"},
            {"quantity": "10", "UnitPrice": "1000", "TotalPrice": "10000"},
        ])
        ctx = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=False,
        )
        normal = {
            item["field"].code: item
            for section in ctx["sections"]
            for item in section["fields"]
        }
        self.assertEqual(normal["FinalPriceRepair"]["display_value"], "17500.00")

        group = next(
            group
            for section in ctx["sections"]
            for group in section["repeatable_groups"]
        )
        totals = [
            fld["display_value"]
            for item in group["items"]
            for fld in item["fields"]
            if fld["field"].code == "TotalPrice"
        ]
        self.assertEqual(totals, ["5000", "2500", "10000"])

    def test_edit_get_renders_derived_values(self):
        instance = self.save_rows([
            {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
        ])
        ctx = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )
        group = next(
            group
            for section in ctx["sections"]
            for group in section["repeatable_groups"]
        )
        totals = [
            fld["value"]
            for item in group["items"]
            for fld in item["fields"]
            if fld["field"].code == "TotalPrice"
        ]
        self.assertEqual(totals, ["5000"])

    def test_repeatable_formula_fields_never_render_as_editable(self):
        instance = self.save_rows([
            {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
        ])
        for edit_mode in (False, True):
            ctx = DynamicFormService.get_form_for_step(
                instance=instance,
                user=self.user,
                edit_mode=edit_mode,
            )
            for section in ctx["sections"]:
                for item in section["fields"]:
                    if item["field"].code in ("FinalPriceRepair",):
                        self.assertFalse(item["can_edit"])
                        self.assertFalse(item["permission_can_edit"])
                for group in section["repeatable_groups"]:
                    for fld in group["fields"]:
                        if fld["field"].code == "TotalPrice":
                            self.assertFalse(fld["can_edit"])

    # --------------------------------------------------------------
    # HTTP / template rendering: edit state must be server-signalled
    # --------------------------------------------------------------

    def test_rendered_form_carries_server_signalled_edit_mode(self):
        """
        formula.js must never infer edit mode from DOM heuristics: the
        read-only page intentionally still renders a .df-form-actions bar
        (ویرایش / پاک کردن actions) and hidden device inputs, so neither
        .df-form-actions presence nor input presence can distinguish the
        two states.  The <form> element therefore carries an explicit
        data-edit-mode attribute.
        """
        from django.urls import reverse

        instance = self.save_rows([
            {"quantity": "10", "UnitPrice": "500", "TotalPrice": "5000"},
            {"quantity": "50", "UnitPrice": "50", "TotalPrice": "2500"},
            {"quantity": "10", "UnitPrice": "1000", "TotalPrice": "10000"},
        ])
        url = reverse("operator_panel:workflow_instance", args=[instance.pk])
        self.client.force_login(self.user)

        read_only = self.client.get(url)
        self.assertEqual(read_only.status_code, 200)
        html = read_only.content.decode()

        # Server-derived values are present in the read-only markup.
        self.assertIn("17500.00", html)
        self.assertIn("data-edit-mode=\"0\"", html)
        # The actions bar that made the old heuristic fail is still there.
        self.assertIn('class="df-form-actions"', html)
        # No editable quantity input is rendered in read-only mode.
        self.assertNotIn('name="cunspartTable_0_quantity"', html)

        edit = self.client.get(url, {"edit": "1"})
        self.assertEqual(edit.status_code, 200)
        html = edit.content.decode()
        self.assertIn("data-edit-mode=\"1\"", html)
        self.assertIn('name="cunspartTable_0_quantity"', html)
        self.assertIn('name="cunspartTable_1_UnitPrice"', html)
