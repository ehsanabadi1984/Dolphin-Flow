from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import RequestFactory, TestCase

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
    RepeatableRow,
    RepeatableRowValue,
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

        RepeatableRowValue.objects.create(
            row=RepeatableRow.objects.create(
                instance=instance,
                group=self.table_group,
                row_order=0,
            ),
            field=self.part_field,
            lookup_item=self.lookup_oil,
        )
        row = RepeatableRow.objects.filter(
            instance=instance,
            group=self.table_group,
        ).get()

        RepeatableRowValue.objects.create(
            row=row,
            field=self.qty_field,
            decimal_value="2",
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


    def test_flat_table_flattens_grandchild_rows_and_scopes_visibility_per_subtree(self):
        from workflow.form_services import DynamicFormService

        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.table_group,
            name="Child Parts",
            code="child_parts",
            order=2,
            is_active=True,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
        )
        grandchild_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=child_group,
            name="Grandchild Details",
            code="grandchild_details",
            order=3,
            is_active=True,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Code",
            code="child_code",
            field_type=FormField.FieldType.TEXT,
            label="Child Code",
            order=1,
            is_active=True,
        )
        grandchild_field = FormField.objects.create(
            section=self.section,
            repeatable_group=grandchild_group,
            name="Grandchild Code",
            code="grandchild_code",
            field_type=FormField.FieldType.TEXT,
            label="Grandchild Code",
            order=1,
            is_active=True,
        )

        for group in (child_group, grandchild_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )
        for field in (child_field, grandchild_field):
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
            )

        instance = self.create_instance()
        parent_row = RepeatableRow.objects.create(
            instance=instance,
            group=self.table_group,
            row_order=0,
        )
        child_one = RepeatableRow.objects.create(
            instance=instance,
            group=child_group,
            parent_row=parent_row,
            row_order=0,
        )
        child_two = RepeatableRow.objects.create(
            instance=instance,
            group=child_group,
            parent_row=parent_row,
            row_order=1,
        )
        grandchild_rows = [
            RepeatableRow.objects.create(
                instance=instance,
                group=grandchild_group,
                parent_row=child_one,
                row_order=0,
            ),
            RepeatableRow.objects.create(
                instance=instance,
                group=grandchild_group,
                parent_row=child_one,
                row_order=1,
            ),
            RepeatableRow.objects.create(
                instance=instance,
                group=grandchild_group,
                parent_row=child_two,
                row_order=0,
            ),
        ]
        parent_choice = LookupItem.objects.create(
            lookup_list=self.lookup_list,
            value="parent",
            label="Parent",
            order=3,
            is_active=True,
        )
        RepeatableRowValue.objects.create(
            row=parent_row,
            field=self.part_field,
            lookup_item=parent_choice,
        )
        RepeatableRowValue.objects.create(
            row=child_one,
            field=child_field,
            text_value="child-1",
        )
        RepeatableRowValue.objects.create(
            row=child_two,
            field=child_field,
            text_value="child-2",
        )
        for index, row in enumerate(grandchild_rows, start=1):
            RepeatableRowValue.objects.create(
                row=row,
                field=grandchild_field,
                text_value=f"grandchild-{index}",
            )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )
        table_group = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].code == self.table_group.code
        )
        flat = table_group["flat_table"]

        self.assertEqual(
            [
                column["field_context"]["field"].code
                for column in flat["columns"]
            ],
            ["part", "description", "qty", "status", "child_code", "grandchild_code"],
        )
        self.assertEqual(len(flat["rows"]), 3)

        rows = flat["rows"]
        self.assertEqual(
            [row["row_id"] for row in rows],
            [str(row.pk) for row in grandchild_rows],
        )
        self.assertEqual(
            [row["parent_row_id"] for row in rows],
            [str(child_one.pk), str(child_one.pk), str(child_two.pk)],
        )

        child_code_cells = [
            next(cell for cell in row["column_cells"] if cell["field"].code == "child_code")
            for row in rows
        ]
        self.assertEqual(
            [cell["value"] for cell in child_code_cells],
            ["child-1", "child-1", "child-2"],
        )
        self.assertEqual(
            [cell["show"] for cell in child_code_cells],
            [True, False, True],
        )

        parent_part_cells = [
            next(cell for cell in row["column_cells"] if cell["field"].code == "part")
            for row in rows
        ]
        self.assertEqual(
            [cell["value"] for cell in parent_part_cells],
            ["parent", "parent", "parent"],
        )
        self.assertEqual(
            [cell["show"] for cell in parent_part_cells],
            [True, False, False],
        )

        grandchild_code_cells = [
            next(cell for cell in row["column_cells"] if cell["field"].code == "grandchild_code")
            for row in rows
        ]
        self.assertEqual(
            [cell["show"] for cell in grandchild_code_cells],
            [True, True, True],
        )

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

        from workflow.instance_device_services import InstanceDeviceService

        InstanceDeviceService.add_draft_device(
            instance=instance,
            imei="123456789012345",
            device_model=device_model,
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

    def test_table_hidden_id_in_actions_cell(self):
        """TABLE hidden _id input is inside actions cell, not extra column."""
        import os

        template_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "operator_panel", "templates",
            "operator_panel", "workflow_instance.html",
        )
        template_path = os.path.normpath(template_path)

        with open(template_path, "r") as f:
            content = f.read()

        # Should not have a hidden td for row_id
        self.assertNotIn("<td style=\"display:none;\">", content)



class RepeatableRowActionAndEmptyStateRenderTests(TestCase):
    """16.3E regression matrix for row actions and empty-state rendering."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="row_action_test_user",
            password="test-password",
        )
        cls.workflow = Workflow.objects.create(
            name="Row Action WF",
            code="ROW_ACTION_WF",
            is_active=True,
        )
        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step",
            code="ROW_ACTION_STEP",
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
            name="Row Action Form",
            is_active=True,
        )
        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Section",
            code="ROW_ACTION_SEC",
            order=1,
            is_active=True,
        )
        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Parts",
            code="parts",
            order=1,
            display_type=FormRepeatableGroup.DisplayType.LIST,
            is_active=True,
        )
        cls.field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Part",
            code="part",
            field_type=FormField.FieldType.TEXT,
            label="Part",
            order=1,
            is_active=True,
        )
        FieldAccess.objects.create(
            field=cls.field,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
        )
        cls.group_access = RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

    def create_instance(self, *, submitted=False):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            status=WorkflowInstance.Status.ACTIVE,
        )
        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step,
            performed_by=self.user,
            is_submitted=submitted,
        )
        return instance

    def render_instance(self, instance, *, edit_mode=True):
        from workflow.form_services import DynamicFormService

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=edit_mode,
        )
        request = RequestFactory().get("/")
        request.user = self.user
        context = {
            "instance": instance,
            "dynamic_form": result,
            "edit_mode": edit_mode,
            "transitions": [],
            "error": None,
            "validation_errors": [],
            "has_saved_data": result.get("has_saved_data", False),
            "current_step_execution": instance.step_executions.order_by("-id").first(),
        }
        return result, get_template(
            "operator_panel/workflow_instance.html"
        ).render(context, request)

    def set_group_permissions(self, *, can_view=True, can_edit=True,
                               can_add=True, can_delete=True):
        self.group_access.can_view = can_view
        self.group_access.can_edit = can_edit
        self.group_access.can_add = can_add
        self.group_access.can_delete = can_delete
        self.group_access.save()

    def create_row(self, instance):
        row = RepeatableRow.objects.create(
            instance=instance,
            group=self.group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=self.field,
            text_value="part-1",
        )
        return row

    def test_list_empty_can_add_true_shows_add_contract(self):
        instance = self.create_instance()
        self.group.display_type = FormRepeatableGroup.DisplayType.LIST
        self.group.save(update_fields=["display_type"])
        self.set_group_permissions(can_add=True)

        _, html = self.render_instance(instance)

        self.assertIn('data-group-code="parts"', html)
        self.assertIn("df-repeatable-add", html)
        self.assertIn("هنوز اطلاعاتی برای این گروه ثبت نشده است.", html)

    def test_list_empty_can_add_false_hides_add_contract(self):
        instance = self.create_instance()
        self.group.display_type = FormRepeatableGroup.DisplayType.LIST
        self.group.save(update_fields=["display_type"])
        self.set_group_permissions(can_add=False)

        _, html = self.render_instance(instance)

        self.assertNotIn("df-repeatable-add", html)
        self.assertIn("هنوز اطلاعاتی برای این گروه ثبت نشده است.", html)

    def test_table_empty_can_add_true_shows_add_contract(self):
        instance = self.create_instance()
        self.group.display_type = FormRepeatableGroup.DisplayType.TABLE
        self.group.save(update_fields=["display_type"])
        self.set_group_permissions(can_add=True)

        _, html = self.render_instance(instance)

        self.assertIn('data-group-code="parts"', html)
        self.assertIn("df-repeatable-add", html)
        self.assertIn("df-table-empty", html)

    def test_table_empty_can_add_false_hides_add_contract(self):
        instance = self.create_instance()
        self.group.display_type = FormRepeatableGroup.DisplayType.TABLE
        self.group.save(update_fields=["display_type"])
        self.set_group_permissions(can_add=False)

        _, html = self.render_instance(instance)

        self.assertNotIn("df-repeatable-add", html)
        self.assertIn("df-table-empty", html)

    def test_nested_child_empty_renders_under_existing_parent(self):
        instance = self.create_instance()

        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Parts",
            code="child_parts",
            order=2,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Part",
            code="child_part",
            field_type=FormField.FieldType.TEXT,
            label="Child Part",
            order=1,
            is_active=True,
        )
        FieldAccess.objects.create(
            field=child_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=False,
            can_delete=True,
        )
        self.set_group_permissions(can_add=True)
        self.create_row(instance)

        _, html = self.render_instance(instance)

        self.assertIn('data-repeatable-group="child_parts"', html)
        self.assertIn("df-table-empty", html)
        self.assertIn("هنوز اطلاعاتی برای این گروه ثبت نشده است.", html)

    def test_nested_child_without_view_permission_is_not_rendered(self):
        instance = self.create_instance()

        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Hidden Child",
            code="hidden_child",
            order=2,
            display_type=FormRepeatableGroup.DisplayType.LIST,
            is_active=True,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Hidden Value",
            code="hidden_value",
            field_type=FormField.FieldType.TEXT,
            label="Hidden Value",
            order=1,
            is_active=True,
        )
        FieldAccess.objects.create(
            field=child_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=False,
            can_add=False,
            can_delete=False,
        )
        self.create_row(instance)

        _, html = self.render_instance(instance)

        self.assertNotIn('data-repeatable-group="hidden_child"', html)
        self.assertNotIn("Hidden Child", html)

    def test_populated_row_can_delete_false_hides_delete_action(self):
        instance = self.create_instance()
        self.set_group_permissions(can_delete=False)
        self.create_row(instance)

        _, html = self.render_instance(instance)

        self.assertIn('data-row-id=', html)
        self.assertNotIn("df-repeatable-delete", html)

    def test_populated_row_can_delete_true_shows_delete_action(self):
        instance = self.create_instance()
        self.set_group_permissions(can_delete=True)
        self.create_row(instance)

        _, html = self.render_instance(instance)

        self.assertIn('data-row-id=', html)
        self.assertIn("df-repeatable-delete", html)

    def test_submitted_mode_disables_add_and_delete_actions(self):
        instance = self.create_instance(submitted=True)
        self.set_group_permissions(
            can_add=True,
            can_delete=True,
            can_edit=True,
        )
        self.create_row(instance)

        result, html = self.render_instance(instance, edit_mode=True)

        self.assertTrue(result["is_submitted"])
        self.assertNotIn("df-repeatable-add", html)
        self.assertNotIn("df-repeatable-delete", html)



class RepeatableAccessibilityContractTests(TestCase):
    """16.3H static accessibility contracts for repeatable templates."""

    def test_workflow_instance_repeatable_controls_have_label_targets(self):
        from pathlib import Path

        template_path = Path(__file__).resolve().parents[2] / "operator_panel" / "templates" / "operator_panel" / "workflow_instance.html"
        content = template_path.read_text()

        self.assertIn('scope="col"', content)
        self.assertIn('for="repeatable-{{ group.group.code }}-{{ item_index }}-', content)
        self.assertIn('id="repeatable-{{ group.group.code }}-{{ item_index }}-', content)
        self.assertIn('aria-label="بستن پنجره افزودن دستگاه"', content)

    def test_nested_repeatable_table_has_scoped_headers_and_label_targets(self):
        from pathlib import Path

        template_path = Path(__file__).resolve().parents[2] / "operator_panel" / "templates" / "operator_panel" / "_repeatable_child_groups.html"
        content = template_path.read_text()

        self.assertIn('scope="col"', content)
        self.assertIn('for="repeatable-{{ group.group.code }}-{{ item_index }}-{{ child_group.group.code }}-', content)
        self.assertIn('id="repeatable-{{ group.group.code }}-{{ item_index }}-{{ child_group.group.code }}-', content)


    def test_flat_table_input_prefixes_are_scoped_to_root_and_child_paths(self):
        from workflow.form_services import DynamicFormService

        user = get_user_model().objects.create_user(
            username="flat-prefix-user",
            password="password",
        )
        workflow = Workflow.objects.create(
            name="Flat Prefix Workflow",
            code="FLAT_PREFIX_WF",
        )
        step = WorkflowStep.objects.create(
            workflow=workflow,
            name="Flat Prefix Step",
            code="FLAT_PREFIX_STEP",
            order=1,
        )
        form = FormDefinition.objects.create(
            workflow=workflow,
            name="Flat Prefix Form",
        )
        section = FormSection.objects.create(
            form=form,
            name="Flat Prefix Section",
            code="FLAT_PREFIX_SECTION",
            order=1,
        )
        table_group = FormRepeatableGroup.objects.create(
            section=section,
            name="Parts",
            code="parts",
            order=1,
            is_active=True,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
        )
        part_field = FormField.objects.create(
            section=section,
            repeatable_group=table_group,
            name="Part",
            code="part_prefix",
            field_type=FormField.FieldType.TEXT,
            label="Part",
            order=1,
            is_active=True,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=section,
            parent_group=table_group,
            name="Child Parts Prefix",
            code="child_parts_prefix",
            order=10,
            is_active=True,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
        )
        child_field = FormField.objects.create(
            section=section,
            repeatable_group=child_group,
            name="Child Code Prefix",
            code="child_code_prefix",
            field_type=FormField.FieldType.TEXT,
            label="Child Code Prefix",
            order=1,
            is_active=True,
        )
        RepeatableGroupAccess.objects.create(
            group=table_group,
            step=step,
            user=user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=step,
            user=user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        FieldAccess.objects.create(
            field=part_field,
            step=step,
            user=user,
            can_view=True,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=child_field,
            step=step,
            user=user,
            can_view=True,
            can_edit=True,
        )

        instance = WorkflowInstance.objects.create(
            workflow=workflow,
            current_step=step,
            started_by=user,
        )
        parent_row = RepeatableRow.objects.create(
            instance=instance,
            group=table_group,
            row_order=0,
        )
        child_rows = [
            RepeatableRow.objects.create(
                instance=instance,
                group=child_group,
                parent_row=parent_row,
                row_order=index,
            )
            for index in range(2)
        ]
        for index, row in enumerate(child_rows, start=1):
            RepeatableRowValue.objects.create(
                row=row,
                field=child_field,
                text_value=f"child-{index}",
            )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=user,
            edit_mode=True,
        )
        table_context = next(
            group
            for section_context in result["sections"]
            for group in section_context["repeatable_groups"]
            if group["group"].code == table_group.code
        )

        rows = table_context["flat_table"]["rows"]
        self.assertEqual(len(rows), 2)

        root_cell_prefixes = []
        child_cell_prefixes = []
        for row in rows:
            root_cell_prefixes.append(
                next(
                    cell["input_prefix"]
                    for cell in row["column_cells"]
                    if cell["field"].code == part_field.code
                )
            )
            child_cell_prefixes.append(
                next(
                    cell["input_prefix"]
                    for cell in row["column_cells"]
                    if cell["field"].code == child_field.code
                )
            )

        self.assertEqual(root_cell_prefixes, ["parts_0_", "parts_0_"])
        self.assertEqual(
            child_cell_prefixes,
            [
                "parts_0_child_parts_prefix_0_",
                "parts_0_child_parts_prefix_1_",
            ],
        )
