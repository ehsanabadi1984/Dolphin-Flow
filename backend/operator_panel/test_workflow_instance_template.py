from types import SimpleNamespace

from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase
from django.contrib.auth.models import AnonymousUser


class WorkflowInstanceRepeatableDisplayTypeTemplateTests(SimpleTestCase):
    template_name = "operator_panel/workflow_instance.html"

    def _field(self, code, label):
        return SimpleNamespace(
            code=code,
            label=label,
            is_required=False,
            field_type="TEXT",
            pk=1,
        )

    def _item(self, field, value, row_id, child_groups=None):
        return SimpleNamespace(
            row_id=row_id,
            fields=[
                SimpleNamespace(
                    field=field,
                    value=value,
                    display_value=value,
                    can_edit=False,
                    choices=[],
                    parent_code=None,
                )
            ],
            child_groups=child_groups or [],
        )

    def _group(self, code, display_type, item):
        field = self._field(f"{code}_field", f"{code} field")
        group = SimpleNamespace(
            group=SimpleNamespace(
                code=code,
                name=f"internal_{code}",
                label=f"Label {code}",
                group_type="NORMAL",
                display_type=display_type,
            ),
            fields=[SimpleNamespace(field=field)],
            items=[item],
            can_add=False,
            can_edit=False,
            can_delete=False,
        )

        if display_type == "TABLE":
            rows = [
                SimpleNamespace(
                    row_group_code=code,
                    path=[(code, 0)],
                    path_key=f"{code}:0",
                    row_id=item.row_id,
                    parent_row_id=None,
                    column_cells=[
                        SimpleNamespace(
                            show=True,
                            group_code=code,
                            field=field,
                            field_context=SimpleNamespace(
                                field=field,
                                parent_code=None,
                                choices=[],
                            ),
                            can_edit=False,
                            value=item.fields[0].value,
                            display_value=item.fields[0].display_value,
                        )
                    ],
                    id_input_name=f"{code}_0__id",
                    add_children=[],
                    can_delete=False,
                    delete_group_name=code,
                    delete_group_code=code,
                )
            ]

            for child_group in item.child_groups:
                child_field = child_group.fields[0].field
                child_item = child_group.items[0]
                rows.append(
                    SimpleNamespace(
                        row_group_code=child_group.group.code,
                        path=[(code, 0), (child_group.group.code, 0)],
                        path_key=f"{code}:0/{child_group.group.code}:0",
                        row_id=child_item.row_id,
                        parent_row_id=item.row_id,
                        column_cells=[
                            SimpleNamespace(
                                show=True,
                                group_code=child_group.group.code,
                                field=child_field,
                                field_context=SimpleNamespace(
                                    field=child_field,
                                    parent_code=None,
                                    choices=[],
                                ),
                                can_edit=False,
                                value=child_item.fields[0].value,
                                display_value=child_item.fields[0].display_value,
                            )
                        ],
                        id_input_name=(
                            f"{code}_0_{child_group.group.code}_0__id"
                        ),
                        add_children=[],
                        can_delete=False,
                        delete_group_name=child_group.group.code,
                        delete_group_code=child_group.group.code,
                    )
                )

            group.flat_table = SimpleNamespace(
                columns=[
                    SimpleNamespace(
                        group_code=code,
                        field_context=SimpleNamespace(
                            field=field,
                            parent_code=None,
                            choices=[],
                        ),
                    )
                ],
                rows=rows,
            )

        return group

    def _context(self, parent_display_type, child_display_type):
        child_field = self._field("child_field", "Child Field")
        child_item = self._item(
            child_field,
            "child-value",
            "child-row-1",
        )
        child_group = self._group(
            "CHILD",
            child_display_type,
            child_item,
        )

        parent_field = self._field("parent_field", "Parent Field")
        parent_item = self._item(
            parent_field,
            "parent-value",
            "parent-row-1",
            child_groups=[child_group],
        )
        parent_group = self._group(
            "PARENT",
            parent_display_type,
            parent_item,
        )

        section = SimpleNamespace(
            section=SimpleNamespace(name="Section"),
            layout_items=[
                SimpleNamespace(type="group", item=parent_group),
            ],
        )

        dynamic_form = SimpleNamespace(
            form=SimpleNamespace(name="Form"),
            sections=[section],
            is_submitted=True,
            has_saved_data=False,
            can_reenter_edit_mode=False,
        )

        instance = SimpleNamespace(
            pk=1,
            workflow=SimpleNamespace(name="Workflow"),
            form_number="FORM-1",
            started_at=None,
            current_step=None,
            status="INACTIVE",
        )

        return {
            "instance": instance,
            "dynamic_form": dynamic_form,
            "edit_mode": False,
            "no_longer_my_task": False,
            "messages": [],
            "validation_errors": [],
            "transitions": [],
            "error": None,
            "can_view_device_history": False,
            "system_branding": SimpleNamespace(
                favicon=None,
                browser_title="Dolphin Flow",
            ),
        }

    def _render(self, parent_display_type, child_display_type):
        template = get_template(self.template_name)
        context = self._context(parent_display_type, child_display_type)
        request = RequestFactory().get("/operator/workflow/1/")
        request.user = AnonymousUser()
        context["request"] = request
        return template.render(context)


    def test_edit_action_section_is_not_rendered_in_edit_mode(self):
        template = get_template(self.template_name)
        context = self._context("LIST", "LIST")
        context["dynamic_form"].is_submitted = False
        context["dynamic_form"].has_saved_data = True
        context["dynamic_form"].can_reenter_edit_mode = True
        context["edit_mode"] = True

        request = RequestFactory().get("/operator/workflow/1/?edit=1")
        request.user = AnonymousUser()
        context["request"] = request

        rendered = template.render(context)

        self.assertNotIn(
            'href="?edit=1"',
            rendered,
        )

        context["edit_mode"] = False
        rendered = template.render(context)

        self.assertIn(
            'href="?edit=1"',
            rendered,
        )

    def test_transitions_are_disabled_in_edit_mode(self):
        template = get_template(self.template_name)
        context = self._context("LIST", "LIST")
        context["instance"].status = "ACTIVE"
        context["instance"].current_step = SimpleNamespace()
        context["edit_mode"] = True
        context["dynamic_form"].is_submitted = False
        context["transitions"] = [
            SimpleNamespace(
                pk=7,
                name="ارسال",
                description="انتقال به مرحله بعد",
            )
        ]

        request = RequestFactory().get("/operator/workflow/1/?edit=1")
        request.user = AnonymousUser()
        context["request"] = request

        rendered = template.render(context)

        self.assertIn(
            'type="submit" class="df-button df-button-secondary" disabled',
            rendered,
        )

        context["edit_mode"] = False
        rendered = template.render(context)

        self.assertIn(
            'type="submit" class="df-button df-button-secondary">ارسال</button>',
            rendered,
        )
        self.assertNotIn(
            'type="submit" class="df-button df-button-secondary" disabled',
            rendered,
        )

    def test_repeatable_group_uses_label_not_internal_name(self):
        rendered = self._render("LIST", "LIST")

        self.assertIn("Label PARENT", rendered)
        self.assertIn("Label CHILD", rendered)
        self.assertNotIn("internal_PARENT", rendered)
        self.assertNotIn("internal_CHILD", rendered)

    def test_list_parent_renders_list_child(self):
        rendered = self._render("LIST", "LIST")

        self.assertIn('data-repeatable-group="CHILD"', rendered)
        self.assertIn("df-repeatable-child-group", rendered)
        self.assertNotIn("df-table-group", rendered)

    def test_list_parent_renders_table_child(self):
        rendered = self._render("LIST", "TABLE")

        self.assertIn('data-repeatable-group="CHILD"', rendered)
        self.assertIn("df-table-group", rendered)
        self.assertIn("df-normal-table", rendered)

    def test_table_parent_renders_nested_child_as_flat_row(self):
        rendered = self._render("TABLE", "LIST")

        self.assertIn('data-repeatable-row-group="CHILD"', rendered)
        self.assertIn("df-repeatable-child-flat-row", rendered)

    def test_empty_nested_list_group_renders_add_row_template(self):
        context = self._context("LIST", "LIST")
        child_group = context["dynamic_form"].sections[0].layout_items[0].item.items[0].child_groups[0]
        child_group.items = []
        child_group.can_add = True
        context["edit_mode"] = True
        context["dynamic_form"].is_submitted = False

        template = get_template(self.template_name)
        request = RequestFactory().get("/operator/workflow/1/")
        request.user = AnonymousUser()
        context["request"] = request

        rendered = template.render(context)

        self.assertIn('data-repeatable-template', rendered)
        self.assertIn(
            'name="PARENT_0_CHILD_TEMPLATE_CHILD_field"',
            rendered,
        )

    def test_empty_nested_table_group_renders_add_row_template(self):
        context = self._context("LIST", "TABLE")
        child_group = context["dynamic_form"].sections[0].layout_items[0].item.items[0].child_groups[0]
        child_group.items = []
        child_group.can_add = True
        context["edit_mode"] = True
        context["dynamic_form"].is_submitted = False

        template = get_template(self.template_name)
        request = RequestFactory().get("/operator/workflow/1/")
        request.user = AnonymousUser()
        context["request"] = request

        rendered = template.render(context)

        self.assertIn('data-repeatable-template', rendered)
        self.assertIn(
            'name="PARENT_0_CHILD_TEMPLATE_CHILD_field"',
            rendered,
        )

    def test_table_parent_renders_nested_child_independent_of_child_display_type(self):
        context = self._context("TABLE", "TABLE")
        context["edit_mode"] = True
        context["dynamic_form"].is_submitted = False

        parent_group = context["dynamic_form"].sections[0].layout_items[0].item
        rows = parent_group.flat_table.rows
        parent_row, child_row = rows

        parent_row.column_cells[0].can_edit = True
        parent_row.add_children = [
            SimpleNamespace(
                can_add=True,
                group_code="CHILD",
                group_label="Label CHILD",
                parent_row_id="parent-row-1",
            )
        ]
        child_row.column_cells[0].can_edit = True
        child_row.can_delete = True
        child_row.delete_group_label = "Label CHILD"

        template = get_template(self.template_name)
        request = RequestFactory().get("/operator/workflow/1/")
        request.user = AnonymousUser()
        context["request"] = request
        rendered = template.render(context)

        self.assertIn('data-repeatable-row-group="CHILD"', rendered)
        self.assertIn("df-repeatable-child-flat-row", rendered)
        self.assertIn('data-parent-row-id="parent-row-1"', rendered)
        self.assertIn("+ افزودن Label CHILD", rendered)
        self.assertIn("حذف Label CHILD", rendered)
        self.assertNotIn("+ افزودن internal_CHILD", rendered)
        self.assertNotIn("حذف internal_CHILD", rendered)
