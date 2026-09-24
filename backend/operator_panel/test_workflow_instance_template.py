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
        return SimpleNamespace(
            group=SimpleNamespace(
                code=code,
                name=code,
                group_type="NORMAL",
                display_type=display_type,
            ),
            fields=[SimpleNamespace(field=field)],
            items=[item],
            can_add=False,
            can_edit=False,
            can_delete=False,
        )

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

    def test_table_parent_renders_list_child(self):
        rendered = self._render("TABLE", "LIST")

        self.assertIn('data-repeatable-group="CHILD"', rendered)
        self.assertIn("df-repeatable-child-group", rendered)

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

    def test_table_parent_renders_table_child(self):
        rendered = self._render("TABLE", "TABLE")

        self.assertIn('data-repeatable-group="CHILD"', rendered)
        self.assertIn("df-table-group", rendered)
        self.assertIn("df-normal-table", rendered)
