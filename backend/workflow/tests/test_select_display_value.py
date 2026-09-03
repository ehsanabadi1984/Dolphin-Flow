"""
Regression tests for the Dynamic Form SELECT display bug.

A SELECT field backed by LookupItem / StaticChoiceItem / MODEL choices
stores the machine value (e.g. ``sim``) inside FormData. The read-only
form must display the human-readable label (e.g. ``سیم``) instead of
the raw stored value, while the editable SELECT keeps the stored value
as the ``<option value>``.

The label resolution happens in the DynamicFormService context-building
layer (``display_value``); the template renders ``display_value`` with a
fallback to the raw value so unresolved/blanks never render empty.
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.template.loader import get_template
from django.test import RequestFactory, TestCase

from workflow.form_services import DynamicFormService
from workflow.models import (
    DeviceType,
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    LookupItem,
    LookupList,
    RepeatableGroupAccess,
    StaticChoiceItem,
    StaticChoiceSet,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)

User = get_user_model()


class SelectDisplayValueTests(TestCase):
    """
    NORMAL repeatable group rows (Dynamic Tables) and top-level fields
    must expose a ``display_value`` that resolves SELECT machine values
    to their human-readable labels.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="select_display_test",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="Select Display Workflow",
            code="SELECT_DISPLAY_WF",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step",
            code="STEP",
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
            name="Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Section",
            code="SEC",
            order=1,
            is_active=True,
        )

        # ----------------------------------------------------------
        # Lookup list used by repeatable-row SELECT fields
        # ----------------------------------------------------------

        cls.part_lookup = LookupList.objects.create(
            name="قطعات",
            code="PARTS_LOOKUP",
            is_active=True,
        )

        for value, label in [
            ("sim", "سیم"),
            ("pich", "پیچ"),
            ("khazan", "خازن"),
        ]:
            LookupItem.objects.create(
                lookup_list=cls.part_lookup,
                value=value,
                label=label,
                is_active=True,
            )

        # ----------------------------------------------------------
        # Static choice set used by repeatable-row SELECT fields
        # ----------------------------------------------------------

        cls.quality_set = StaticChoiceSet.objects.create(
            name="کیفیت",
            code="QUALITY_SET",
            is_active=True,
        )

        for value, label in [
            ("sahih", "سالم"),
            ("moib", "معیوب"),
        ]:
            StaticChoiceItem.objects.create(
                choice_set=cls.quality_set,
                value=value,
                label=label,
                is_active=True,
            )

        # ----------------------------------------------------------
        # Repeatable groups live in their own sections (each section
        # owns a unique field-code namespace).
        # ----------------------------------------------------------

        cls.list_section = FormSection.objects.create(
            form=cls.form,
            name="List Section",
            code="SEC_LIST",
            order=2,
            is_active=True,
        )

        cls.table_section = FormSection.objects.create(
            form=cls.form,
            name="Table Section",
            code="SEC_TABLE",
            order=3,
            is_active=True,
        )

        # ----------------------------------------------------------
        # LIST repeatable group
        # ----------------------------------------------------------

        cls.list_group = FormRepeatableGroup.objects.create(
            section=cls.list_section,
            name="قطعات (لیست)",
            code="parts_list",
            display_type=FormRepeatableGroup.DisplayType.LIST,
            order=1,
            is_active=True,
        )

        cls.list_part_field = cls._make_repeatable_select(
            group=cls.list_group,
            code="part",
            label="قطعه",
            choice_source=FormField.ChoiceSource.LOOKUP,
            lookup_list=cls.part_lookup,
            order=1,
        )

        cls.list_quality_field = cls._make_repeatable_select(
            group=cls.list_group,
            code="quality",
            label="کیفیت",
            choice_source=FormField.ChoiceSource.STATIC,
            static_set=cls.quality_set,
            order=2,
        )

        cls.list_qty_field = FormField.objects.create(
            section=cls.list_section,
            repeatable_group=cls.list_group,
            name="Quantity",
            code="quantity",
            field_type=FormField.FieldType.NUMBER,
            label="تعداد",
            order=3,
            is_active=True,
        )

        # ----------------------------------------------------------
        # TABLE repeatable group
        # ----------------------------------------------------------

        cls.table_group = FormRepeatableGroup.objects.create(
            section=cls.table_section,
            name="قطعات (جدول)",
            code="parts_table",
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            order=1,
            is_active=True,
        )

        cls.table_part_field = cls._make_repeatable_select(
            group=cls.table_group,
            code="part",
            label="قطعه",
            choice_source=FormField.ChoiceSource.LOOKUP,
            lookup_list=cls.part_lookup,
            order=1,
        )

        cls.table_quality_field = cls._make_repeatable_select(
            group=cls.table_group,
            code="quality",
            label="کیفیت",
            choice_source=FormField.ChoiceSource.STATIC,
            static_set=cls.quality_set,
            order=2,
        )

        cls.table_qty_field = FormField.objects.create(
            section=cls.table_section,
            repeatable_group=cls.table_group,
            name="Quantity",
            code="quantity",
            field_type=FormField.FieldType.NUMBER,
            label="تعداد",
            order=3,
            is_active=True,
        )

        # ----------------------------------------------------------
        # Top-level fields
        # ----------------------------------------------------------

        cls.customer_lookup = LookupList.objects.create(
            name="نوع مشتری",
            code="CUSTOMER_LOOKUP",
            is_active=True,
        )

        LookupItem.objects.create(
            lookup_list=cls.customer_lookup,
            value="retail",
            label="خرده فروش",
            is_active=True,
        )

        cls.customer_field = FormField.objects.create(
            section=cls.section,
            name="نوع مشتری",
            code="customer_type",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=cls.customer_lookup,
            label="نوع مشتری",
            order=1,
            is_active=True,
        )

        cls.warranty_set = StaticChoiceSet.objects.create(
            name="گارانتی",
            code="WARRANTY_SET",
            is_active=True,
        )

        StaticChoiceItem.objects.create(
            choice_set=cls.warranty_set,
            value="under_warranty",
            label="تحت گارانتی",
            is_active=True,
        )

        cls.warranty_field = FormField.objects.create(
            section=cls.section,
            name="گارانتی",
            code="warranty",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.STATIC,
            choice_static_set=cls.warranty_set,
            label="گارانتی",
            order=2,
            is_active=True,
        )

        cls.device_type = DeviceType.objects.create(
            name="موبایل",
            code="MOBILE_DISPLAY_TEST",
            is_active=True,
        )

        cls.device_choice_field = FormField.objects.create(
            section=cls.section,
            name="نوع دستگاه",
            code="device_choice",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=ContentType.objects.get_for_model(DeviceType),
            choice_value_field="id",
            choice_label_field="name",
            label="نوع دستگاه",
            order=3,
            is_active=True,
        )

        # ----------------------------------------------------------
        # Permissions (repeatable groups + fields)
        # ----------------------------------------------------------

        for group in (
            cls.list_group,
            cls.table_group,
        ):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=cls.step,
                user=cls.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )

            for field in group.fields.all():
                FieldAccess.objects.create(
                    field=field,
                    step=cls.step,
                    user=cls.user,
                    can_view=True,
                    can_edit=True,
                )

        for field in (
            cls.customer_field,
            cls.warranty_field,
            cls.device_choice_field,
        ):
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                user=cls.user,
                can_view=True,
                can_edit=True,
            )

    # ----------------------------------------------------------
    # Fixture helpers
    # ----------------------------------------------------------

    @classmethod
    def _make_repeatable_select(
        cls,
        *,
        group,
        code,
        label,
        choice_source,
        lookup_list=None,
        static_set=None,
        order=1,
    ):
        return FormField.objects.create(
            section=group.section,
            repeatable_group=group,
            name=label,
            code=code,
            field_type=FormField.FieldType.SELECT,
            choice_source=choice_source,
            choice_lookup_list=lookup_list,
            choice_static_set=static_set,
            label=label,
            order=order,
            is_active=True,
        )

    def create_instance(self):
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
        return instance

    def save_rows(self, instance, *, group_code, part, quality, quantity):
        submitted_data = {
            f"{group_code}_0_part": part,
            f"{group_code}_0_quality": quality,
            f"{group_code}_0_quantity": quantity,
        }
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

    def save_top_level(
        self,
        instance,
        *,
        customer_type,
        warranty,
        device_choice,
    ):
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "customer_type": customer_type,
                "warranty": warranty,
                "device_choice": device_choice,
            },
        )

    def get_group(self, result, code):
        for section in result["sections"]:
            for group in section["repeatable_groups"]:
                if group["group"].code == code:
                    return group
        return None

    def get_top_level_field(self, result, code):
        for section in result["sections"]:
            for item in section["fields"]:
                if item["field"].code == code:
                    return item
        return None

    def get_item_field(self, item, code):
        for item_field in item["fields"]:
            if item_field["field"].code == code:
                return item_field
        return None

    # ==========================================================
    # Context-building layer (get_form_for_step)
    # ==========================================================

    def test_repeatable_row_lookup_select_gets_label_display_value(self):
        """A saved LOOKUP SELECT row keeps value='sim' and resolves
        display_value='سیم' — for LIST and TABLE groups."""
        instance = self.create_instance()

        for group_code in ("parts_list", "parts_table"):
            with self.subTest(group_code=group_code):
                self.save_rows(
                    instance,
                    group_code=group_code,
                    part="sim",
                    quality="sahih",
                    quantity="2",
                )

                result = DynamicFormService.get_form_for_step(
                    instance=instance,
                    user=self.user,
                )

                group = self.get_group(result, group_code)
                self.assertIsNotNone(group)
                self.assertEqual(len(group["items"]), 1)

                part_field = self.get_item_field(
                    group["items"][0],
                    "part",
                )
                self.assertEqual(part_field["value"], "sim")
                self.assertEqual(part_field["display_value"], "سیم")

    def test_repeatable_row_static_select_gets_label_display_value(self):
        """STATIC SELECT rows resolve to their label as well."""
        instance = self.create_instance()
        self.save_rows(
            instance,
            group_code="parts_list",
            part="sim",
            quality="sahih",
            quantity="2",
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        group = self.get_group(result, "parts_list")
        quality_field = self.get_item_field(
            group["items"][0],
            "quality",
        )
        self.assertEqual(quality_field["value"], "sahih")
        self.assertEqual(quality_field["display_value"], "سالم")

    def test_top_level_lookup_select_gets_label_display_value(self):
        """Top-level (non-repeatable) LOOKUP SELECT gets a label."""
        instance = self.create_instance()
        self.save_top_level(
            instance,
            customer_type="retail",
            warranty="under_warranty",
            device_choice=str(self.device_type.pk),
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        customer = self.get_top_level_field(result, "customer_type")
        self.assertEqual(customer["value"], "retail")
        self.assertEqual(customer["display_value"], "خرده فروش")

    def test_top_level_static_and_model_selects_get_label_display_value(self):
        """Top-level STATIC and MODEL SELECTs resolve labels too."""
        instance = self.create_instance()
        self.save_top_level(
            instance,
            customer_type="retail",
            warranty="under_warranty",
            device_choice=str(self.device_type.pk),
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        warranty = self.get_top_level_field(result, "warranty")
        self.assertEqual(warranty["value"], "under_warranty")
        self.assertEqual(warranty["display_value"], "تحت گارانتی")

        device = self.get_top_level_field(result, "device_choice")
        self.assertEqual(
            device["value"],
            str(self.device_type.pk),
        )
        self.assertEqual(device["display_value"], "موبایل")

    def test_non_select_fields_keep_raw_display_value(self):
        """NUMBER/TEXT fields are unaffected: display_value == value."""
        instance = self.create_instance()
        self.save_rows(
            instance,
            group_code="parts_list",
            part="sim",
            quality="sahih",
            quantity="2",
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        group = self.get_group(result, "parts_list")
        qty_field = self.get_item_field(
            group["items"][0],
            "quantity",
        )
        self.assertEqual(qty_field["value"], "2")
        self.assertEqual(qty_field["display_value"], "2")

    def test_unresolved_select_value_falls_back_to_stored_value(self):
        """An unknown stored value is not blank: display_value falls
        back to the raw stored value."""
        instance = self.create_instance()
        self.save_rows(
            instance,
            group_code="parts_list",
            part="totally_unknown",
            quality="sahih",
            quantity="1",
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        group = self.get_group(result, "parts_list")
        part_field = self.get_item_field(
            group["items"][0],
            "part",
        )
        self.assertEqual(part_field["value"], "totally_unknown")
        self.assertEqual(
            part_field["display_value"],
            "totally_unknown",
        )

    # ==========================================================
    # Template rendering
    # ==========================================================

    def _render(self, *, instance, dynamic_form, edit_mode):
        request = RequestFactory().get("/")
        request.user = self.user

        context = {
            "instance": instance,
            "dynamic_form": dynamic_form,
            "edit_mode": edit_mode,
            "transitions": [],
            "error": None,
            "validation_errors": [],
            "has_saved_data": False,
            "current_step_execution": None,
        }

        return get_template(
            "operator_panel/workflow_instance.html"
        ).render(context, request)

    @staticmethod
    def _normalize(html):
        import re

        return re.sub(r"\s+", " ", html)

    def test_readonly_table_renders_label_not_value(self):
        """TABLE read-only cell shows 'سیم', never the raw 'sim'."""
        instance = self.create_instance()
        self.save_rows(
            instance,
            group_code="parts_table",
            part="sim",
            quality="sahih",
            quantity="2",
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        html = self._render(
            instance=instance,
            dynamic_form=result,
            edit_mode=False,
        )

        self.assertIn("سیم", html)
        self.assertNotIn(">sim<", html)
        # STATIC label shows too, and its raw value is not rendered.
        self.assertIn("سالم", html)
        self.assertNotIn(">sahih<", html)

    def test_readonly_list_renders_label_not_value(self):
        """LIST read-only rows show 'سیم', never the raw 'sim'."""
        instance = self.create_instance()
        self.save_rows(
            instance,
            group_code="parts_list",
            part="sim",
            quality="sahih",
            quantity="2",
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        html = self._render(
            instance=instance,
            dynamic_form=result,
            edit_mode=False,
        )

        self.assertIn("سیم", html)
        self.assertNotIn(">sim<", html)

    def test_top_level_readonly_renders_label_not_value(self):
        """Top-level read-only SELECT shows labels, not stored values."""
        instance = self.create_instance()
        self.save_top_level(
            instance,
            customer_type="retail",
            warranty="under_warranty",
            device_choice=str(self.device_type.pk),
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        html = self._render(
            instance=instance,
            dynamic_form=result,
            edit_mode=False,
        )

        self.assertIn("خرده فروش", html)
        self.assertIn("تحت گارانتی", html)
        self.assertIn("موبایل", html)
        self.assertNotIn(">retail<", html)
        self.assertNotIn(">under_warranty<", html)

    def test_readonly_unresolved_value_renders_raw_value(self):
        """Unresolved SELECT values still render (fallback), not blank."""
        instance = self.create_instance()
        self.save_rows(
            instance,
            group_code="parts_table",
            part="totally_unknown",
            quality="sahih",
            quantity="1",
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        html = self._render(
            instance=instance,
            dynamic_form=result,
            edit_mode=False,
        )

        self.assertIn("totally_unknown", html)

    def test_editable_select_keeps_machine_value_with_label_selected(self):
        """Editable SELECT keeps value='sim' as the option value and
        renders the label 'سیم' with the option selected."""
        instance = self.create_instance()
        self.save_rows(
            instance,
            group_code="parts_table",
            part="sim",
            quality="sahih",
            quantity="2",
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        html = self._render(
            instance=instance,
            dynamic_form=result,
            edit_mode=True,
        )

        normalized = self._normalize(html)

        self.assertIn('value="sim"', normalized)
        self.assertIn("سیم", normalized)
        self.assertIn(
            '<option value="sim" selected > سیم </option>',
            normalized,
        )

    def test_persisted_value_remains_machine_value(self):
        """The fix must not change what is persisted: FormData keeps the
        machine value 'sim', not the label."""
        instance = self.create_instance()
        self.save_rows(
            instance,
            group_code="parts_table",
            part="sim",
            quality="sahih",
            quantity="2",
        )

        rows = FormData.objects.get(instance=instance).data[
            "parts_table"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["part"], "sim")
        self.assertEqual(rows[0]["quality"], "sahih")
