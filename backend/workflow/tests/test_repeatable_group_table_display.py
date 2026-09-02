from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.models import (
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


class RepeatableGroupDisplayTypeTests(TestCase):
    """Tests for FormRepeatableGroup.display_type field."""

    def test_display_type_default_is_list(self):
        """display_type defaults to LIST."""
        workflow = Workflow.objects.create(
            name="Test WF", code="TEST_DT", is_active=True,
        )
        section = FormSection.objects.create(
            form=FormDefinition.objects.create(
                workflow=workflow, name="Form", is_active=True,
            ),
            name="Sec", code="SEC", order=1, is_active=True,
        )
        group = FormRepeatableGroup.objects.create(
            section=section, name="G", code="g", order=1,
        )
        self.assertEqual(group.display_type, FormRepeatableGroup.DisplayType.LIST)

    def test_display_type_can_be_table(self):
        """display_type can be set to TABLE."""
        workflow = Workflow.objects.create(
            name="Test WF 2", code="TEST_DT2", is_active=True,
        )
        section = FormSection.objects.create(
            form=FormDefinition.objects.create(
                workflow=workflow, name="Form", is_active=True,
            ),
            name="Sec", code="SEC", order=1, is_active=True,
        )
        group = FormRepeatableGroup.objects.create(
            section=section, name="G", code="g", order=1,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
        )
        group.refresh_from_db()
        self.assertEqual(group.display_type, FormRepeatableGroup.DisplayType.TABLE)


class TableModeRenderTests(TestCase):
    """Tests that TABLE mode renders correctly for NORMAL repeatable groups."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="table_test_user", password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="Table Test WF", code="TABLE_TST", is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow, name="Step", code="STEP",
            order=1, is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=cls.workflow, user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR, is_active=True,
        )

        cls.form = FormDefinition.objects.create(
            workflow=cls.workflow, name="Form", is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form, name="Sec", code="SEC", order=1, is_active=True,
        )

        # Lookup list
        cls.lookup_list = LookupList.objects.create(
            name="Parts", code="PARTS_LK", is_active=True,
        )
        cls.lookup_oil = LookupItem.objects.create(
            lookup_list=cls.lookup_list, value="oil_filter",
            label="فیلتر روغن", order=1, is_active=True,
        )
        cls.lookup_air = LookupItem.objects.create(
            lookup_list=cls.lookup_list, value="air_filter",
            label="فیلتر هوا", order=2, is_active=True,
        )

        # Static choice set
        cls.static_set = StaticChoiceSet.objects.create(
            name="Statuses", code="STATUSES", is_active=True,
        )
        StaticChoiceItem.objects.create(
            choice_set=cls.static_set, value="pending",
            label="در انتظار", order=1, is_active=True,
        )
        StaticChoiceItem.objects.create(
            choice_set=cls.static_set, value="completed",
            label="تکمیل شده", order=2, is_active=True,
        )

        # TABLE group
        cls.table_group = FormRepeatableGroup.objects.create(
            section=cls.section, name="Parts", code="parts",
            order=1, is_active=True,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
        )

        cls.part_field = FormField.objects.create(
            section=cls.section, repeatable_group=cls.table_group,
            name="Part", code="part",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=cls.lookup_list,
            label="Part", order=1, is_required=True, is_active=True,
        )

        cls.desc_field = FormField.objects.create(
            section=cls.section, repeatable_group=cls.table_group,
            name="Description", code="description",
            field_type=FormField.FieldType.TEXTAREA,
            label="Description", order=2, is_active=True,
        )

        cls.qty_field = FormField.objects.create(
            section=cls.section, repeatable_group=cls.table_group,
            name="Qty", code="qty",
            field_type=FormField.FieldType.NUMBER,
            label="Qty", order=3, is_active=True,
        )

        cls.status_field = FormField.objects.create(
            section=cls.section, repeatable_group=cls.table_group,
            name="Status", code="status",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.STATIC,
            choice_static_set=cls.static_set,
            label="Status", order=4, is_active=True,
        )

        # Permissions
        for field in cls.table_group.fields.all():
            FieldAccess.objects.create(
                field=field, step=cls.step,
                user=cls.user, can_view=True, can_edit=True,
            )

        RepeatableGroupAccess.objects.create(
            group=cls.table_group, step=cls.step,
            user=cls.user, can_view=True, can_edit=True, can_add=True,
        )

    def create_instance(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow, current_step=self.step,
            status=WorkflowInstance.Status.ACTIVE,
        )
        WorkflowStepExecution.objects.create(
            instance=instance, workflow_step=self.step,
            performed_by=self.user,
        )
        return instance

    def test_table_group_renders_in_template(self):
        """TABLE group is rendered with df-table-group class."""
        from workflow.form_services import DynamicFormService

        instance = self.create_instance()
        result = DynamicFormService.get_form_for_step(
            instance=instance, user=self.user,
        )

        # Find the table group
        groups = []
        for section in result["sections"]:
            for g in section["repeatable_groups"]:
                groups.append(g)

        table_groups = [g for g in groups if g["group"].display_type == "TABLE"]
        self.assertEqual(len(table_groups), 1)
        self.assertEqual(table_groups[0]["group"].code, "parts")

    def test_list_group_renders_in_template(self):
        """LIST group (default) is still rendered."""
        from workflow.form_services import DynamicFormService

        # Create a LIST group
        list_group = FormRepeatableGroup.objects.create(
            section=self.section, name="Notes", code="notes",
            order=2, is_active=True,
            display_type=FormRepeatableGroup.DisplayType.LIST,
        )
        FormField.objects.create(
            section=self.section, repeatable_group=list_group,
            name="Note", code="note",
            field_type=FormField.FieldType.TEXT,
            label="Note", order=1, is_active=True,
        )
        FieldAccess.objects.create(
            field=list_group.fields.first(), step=self.step,
            user=self.user, can_view=True, can_edit=True,
        )
        RepeatableGroupAccess.objects.create(
            group=list_group, step=self.step,
            user=self.user, can_view=True, can_edit=True, can_add=True,
        )

        instance = self.create_instance()
        result = DynamicFormService.get_form_for_step(
            instance=instance, user=self.user,
        )

        groups = []
        for section in result["sections"]:
            for g in section["repeatable_groups"]:
                groups.append(g)

        list_groups = [g for g in groups if g["group"].display_type == "LIST"]
        self.assertTrue(len(list_groups) >= 1)

    def test_table_renders_all_field_types(self):
        """TABLE mode renders TEXT, TEXTAREA, NUMBER, SELECT fields."""
        from workflow.form_services import DynamicFormService

        instance = self.create_instance()

        # Add a TEXT field
        text_field = FormField.objects.create(
            section=self.section, repeatable_group=self.table_group,
            name="Name", code="name",
            field_type=FormField.FieldType.TEXT,
            label="Name", order=5, is_active=True,
        )
        FieldAccess.objects.create(
            field=text_field, step=self.step,
            user=self.user, can_view=True, can_edit=True,
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance, user=self.user,
        )

        table_group = None
        for section in result["sections"]:
            for g in section["repeatable_groups"]:
                if g["group"].code == "parts":
                    table_group = g
                    break

        self.assertIsNotNone(table_group)

        field_types = [
            f["field"].field_type for f in table_group["fields"]
        ]
        self.assertIn(FormField.FieldType.SELECT, field_types)
        self.assertIn(FormField.FieldType.TEXTAREA, field_types)
        self.assertIn(FormField.FieldType.NUMBER, field_types)
        self.assertIn(FormField.FieldType.TEXT, field_types)

    def test_select_lookup_choices_available(self):
        """SELECT + LookupList fields have choices with correct labels."""
        from workflow.form_services import DynamicFormService

        instance = self.create_instance()
        result = DynamicFormService.get_form_for_step(
            instance=instance, user=self.user,
        )

        table_group = None
        for section in result["sections"]:
            for g in section["repeatable_groups"]:
                if g["group"].code == "parts":
                    table_group = g
                    break

        part_field_info = None
        for f in table_group["fields"]:
            if f["field"].code == "part":
                part_field_info = f
                break

        self.assertIsNotNone(part_field_info)
        self.assertTrue(len(part_field_info["choices"]) > 0)

        values = [c["value"] for c in part_field_info["choices"]]
        labels = [c["label"] for c in part_field_info["choices"]]

        self.assertIn("oil_filter", values)
        self.assertIn("فیلتر روغن", labels)
        self.assertIn("air_filter", values)
        self.assertIn("فیلتر هوا", labels)

    def test_select_static_choices_available(self):
        """SELECT + StaticChoiceSet fields have correct choices."""
        from workflow.form_services import DynamicFormService

        instance = self.create_instance()
        result = DynamicFormService.get_form_for_step(
            instance=instance, user=self.user,
        )

        table_group = None
        for section in result["sections"]:
            for g in section["repeatable_groups"]:
                if g["group"].code == "parts":
                    table_group = g
                    break

        status_field_info = None
        for f in table_group["fields"]:
            if f["field"].code == "status":
                status_field_info = f
                break

        self.assertIsNotNone(status_field_info)
        self.assertTrue(len(status_field_info["choices"]) > 0)

        values = [c["value"] for c in status_field_info["choices"]]
        labels = [c["label"] for c in status_field_info["choices"]]

        self.assertIn("pending", values)
        self.assertIn("در انتظار", labels)
        self.assertIn("completed", values)
        self.assertIn("تکمیل شده", labels)

    def test_table_row_id_available(self):
        """TABLE rows have row_id available in context."""
        from workflow.form_services import DynamicFormService

        instance = self.create_instance()

        # Save some data first
        submitted_data = {
            "parts_0_part": "oil_filter",
            "parts_0_qty": "2",
        }
        DynamicFormService.save_form_for_step(
            instance=instance, user=self.user,
            submitted_data=submitted_data,
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance, user=self.user,
        )

        table_group = None
        for section in result["sections"]:
            for g in section["repeatable_groups"]:
                if g["group"].code == "parts":
                    table_group = g
                    break

        self.assertEqual(len(table_group["items"]), 1)
        self.assertTrue(table_group["items"][0].get("row_id"))

    def test_device_groups_unaffected(self):
        """DEVICE repeatable groups continue to use InstanceDevice."""
        from workflow.form_services import DynamicFormService
        from workflow.instance_device_services import InstanceDeviceService
        from workflow.models import DeviceModel, DeviceType

        device_type = DeviceType.objects.create(
            name="Test Type", code="TBL_DEV_TYPE", is_active=True,
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type, brand="Test", name="Model",
            code="TBL_DEV_MODEL", is_active=True,
        )

        device_group = FormRepeatableGroup.objects.create(
            section=self.section, name="Devices", code="devices",
            order=3, group_type=FormRepeatableGroup.GroupType.DEVICE,
            is_active=True,
        )

        FormField.objects.create(
            section=self.section, repeatable_group=device_group,
            name="IMEI", code="imei",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.IMEI,
            label="IMEI", order=1, is_required=True, is_active=True,
        )
        FormField.objects.create(
            section=self.section, repeatable_group=device_group,
            name="Model", code="device_model_id",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.DEVICE_MODEL,
            label="Model", order=2, is_required=True, is_active=True,
        )

        for field in device_group.fields.all():
            FieldAccess.objects.create(
                field=field, step=self.step,
                user=self.user, can_view=True, can_edit=True,
            )
        RepeatableGroupAccess.objects.create(
            group=device_group, step=self.step,
            user=self.user, can_view=True, can_edit=True, can_add=True,
        )

        instance = self.create_instance()

        submitted_data = {
            "parts_0_part": "oil_filter",
            "parts_0_qty": "1",
            "devices_0_imei": "123456789012345",
            "devices_0_device_model_id": str(device_model.pk),
        }

        DynamicFormService.save_form_for_step(
            instance=instance, user=self.user,
            submitted_data=submitted_data,
        )

        from workflow.models import InstanceDevice
        self.assertTrue(
            InstanceDevice.objects.filter(instance=instance).exists()
        )

    def test_no_item_id_template_access(self):
        """No template accesses item._id directly (uses row_id)."""
        import os

        template_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "operator_panel", "templates",
            "operator_panel", "workflow_instance.html",
        )
        template_path = os.path.normpath(template_path)

        with open(template_path, "r") as f:
            content = f.read()

        # Should not contain item._id (Django template syntax)
        self.assertNotIn("item._id", content)
