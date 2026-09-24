from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from workflow.admin import (
    FormRepeatableGroupAdmin,
    FormRepeatableGroupInline,
    FormSectionAdmin,
    dolphin_admin_site,
)
from workflow.form_workspace import (
    FormRepeatableGroupWorkspaceForm,
    build_repeatable_group_tree,
    form_workspace,
)
from workflow.models import (
    FormDefinition,
    FormRepeatableGroup,
    FormSection,
    Workflow,
)


class RepeatableGroupHierarchyAdminTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Hierarchy Admin Test",
            code="WF_HIER_ADMIN",
        )
        self.form_definition = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Hierarchy Admin Form",
        )
        self.section = FormSection.objects.create(
            form=self.form_definition,
            name="Main",
            code="MAIN",
            order=1,
        )
        self.other_section = FormSection.objects.create(
            form=self.form_definition,
            name="Other",
            code="OTHER",
            order=2,
        )
        self.root = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Root",
            code="ROOT",
            order=1,
        )
        self.child = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Child",
            code="CHILD",
            order=2,
            parent_group=self.root,
        )
        self.grandchild = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Grandchild",
            code="GRANDCHILD",
            order=3,
            parent_group=self.child,
        )
        self.sibling = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Sibling",
            code="SIBLING",
            order=4,
        )
        self.other_section_group = FormRepeatableGroup.objects.create(
            section=self.other_section,
            name="Other Root",
            code="OTHER_ROOT",
            order=1,
        )

    def test_workspace_group_tree_builds_root_child_grandchild_hierarchy(self):
        tree = build_repeatable_group_tree(
            FormRepeatableGroup.objects.filter(section=self.section).order_by("order")
        )

        self.assertEqual([node["group"] for node in tree], [self.root, self.sibling])
        self.assertEqual([node["group"] for node in tree[0]["children"]], [self.child])
        self.assertEqual(
            [node["group"] for node in tree[0]["children"][0]["children"]],
            [self.grandchild],
        )
        self.assertEqual(tree[1]["children"], [])

    def test_workspace_group_move_only_reorders_siblings(self):
        child_sibling = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Child Sibling",
            code="CHILD_SIBLING",
            order=5,
            parent_group=self.root,
        )

        request = RequestFactory().post(
            "/admin/",
            {
                "action": "move_group_down",
                "group_id": str(self.child.pk),
            },
        )

        with patch("workflow.form_workspace.messages.success"), patch(
            "workflow.form_workspace._redirect_designer",
            return_value=object(),
        ):
            form_workspace(request, self.workflow.pk)

        self.child.refresh_from_db()
        child_sibling.refresh_from_db()
        self.grandchild.refresh_from_db()
        self.sibling.refresh_from_db()

        self.assertEqual(self.child.order, 5)
        self.assertEqual(child_sibling.order, 2)
        self.assertEqual(self.grandchild.order, 3)
        self.assertEqual(self.sibling.order, 4)

    def test_workspace_root_move_does_not_reorder_child_groups(self):
        root_sibling = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Root Sibling",
            code="ROOT_SIBLING",
            order=5,
        )

        request = RequestFactory().post(
            "/admin/",
            {
                "action": "move_group_down",
                "group_id": str(self.root.pk),
            },
        )

        with patch("workflow.form_workspace.messages.success"), patch(
            "workflow.form_workspace._redirect_designer",
            return_value=object(),
        ):
            form_workspace(request, self.workflow.pk)

        self.root.refresh_from_db()
        root_sibling.refresh_from_db()
        self.child.refresh_from_db()
        self.grandchild.refresh_from_db()

        self.assertEqual(self.root.order, 4)
        self.assertEqual(root_sibling.order, 5)
        self.assertEqual(self.child.order, 2)
        self.assertEqual(self.grandchild.order, 3)

    def test_workspace_context_exposes_recursive_group_tree(self):
        request = RequestFactory().get("/admin/")
        with patch("workflow.form_workspace.render") as render:
            render.return_value = object()
            from workflow.form_workspace import form_workspace

            form_workspace(request, self.workflow.pk)

        context = render.call_args.args[2]
        tree = context["sections"][0].active_group_tree

        self.assertEqual([node["group"] for node in tree], [self.root, self.sibling])
        self.assertEqual([node["group"] for node in tree[0]["children"]], [self.child])
        self.assertEqual(
            [node["group"] for node in tree[0]["children"][0]["children"]],
            [self.grandchild],
        )
        self.assertEqual(tree[1]["children"], [])

    def test_workspace_form_exposes_parent_group(self):
        form = FormRepeatableGroupWorkspaceForm(section=self.section)

        self.assertIn("parent_group", form.fields)
        self.assertEqual(
            set(form.fields["parent_group"].queryset.values_list("pk", flat=True)),
            {
                self.root.pk,
                self.child.pk,
                self.grandchild.pk,
                self.sibling.pk,
            },
        )
        self.assertNotIn(
            self.other_section_group.pk,
            form.fields["parent_group"].queryset.values_list("pk", flat=True),
        )

    def test_workspace_add_group_defaults_selected_group_as_parent(self):
        form = FormRepeatableGroupWorkspaceForm(
            section=self.section,
            parent_group=self.root,
        )

        self.assertEqual(form.initial["parent_group"], self.root)

        form = FormRepeatableGroupWorkspaceForm(section=self.section)
        self.assertNotIn("parent_group", form.initial)

        bound = FormRepeatableGroupWorkspaceForm(
            data={
                "name": "New Child",
                "code": "NEW_CHILD",
                "group_type": FormRepeatableGroup.GroupType.NORMAL,
                "display_type": FormRepeatableGroup.DisplayType.LIST,
                "description": "",
                "parent_group": "",
                "is_required": False,
                "is_active": True,
            },
            section=self.section,
            parent_group=self.root,
        )

        self.assertTrue(bound.is_valid(), bound.errors)
        self.assertIsNone(bound.cleaned_data["parent_group"])

    def test_workspace_add_group_form_uses_selected_group_as_parent(self):
        request = RequestFactory().get(
            "/admin/",
            {"section": self.section.pk, "group": self.root.pk},
        )

        with patch("workflow.form_workspace.render") as render:
            render.return_value = object()
            form_workspace(request, self.workflow.pk)

        context = render.call_args.args[2]
        self.assertEqual(
            context["group_form"].initial["parent_group"],
            self.root,
        )

    def test_workspace_edit_excludes_self_and_all_descendants(self):
        form = FormRepeatableGroupWorkspaceForm(
            instance=self.root,
            section=self.section,
        )

        parent_ids = set(
            form.fields["parent_group"].queryset.values_list("pk", flat=True)
        )

        self.assertNotIn(self.root.pk, parent_ids)
        self.assertNotIn(self.child.pk, parent_ids)
        self.assertNotIn(self.grandchild.pk, parent_ids)
        self.assertIn(self.sibling.pk, parent_ids)

    def test_workspace_child_can_change_parent_to_valid_sibling(self):
        form = FormRepeatableGroupWorkspaceForm(
            data={
                "name": self.child.name,
                "code": self.child.code,
                "group_type": self.child.group_type,
                "display_type": self.child.display_type,
                "description": self.child.description,
                "parent_group": self.sibling.pk,
                "is_required": self.child.is_required,
                "is_active": self.child.is_active,
            },
            instance=self.child,
            section=self.section,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["parent_group"], self.sibling)

    def test_workspace_rejects_parent_from_other_section(self):
        form = FormRepeatableGroupWorkspaceForm(
            data={
                "name": self.sibling.name,
                "code": self.sibling.code,
                "group_type": self.sibling.group_type,
                "display_type": self.sibling.display_type,
                "description": self.sibling.description,
                "parent_group": self.other_section_group.pk,
                "is_required": self.sibling.is_required,
                "is_active": self.sibling.is_active,
            },
            instance=self.sibling,
            section=self.section,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("parent_group", form.errors)

    def test_admin_form_scopes_parent_group_and_excludes_descendants(self):
        model_admin = FormRepeatableGroupAdmin(
            FormRepeatableGroup,
            dolphin_admin_site,
        )
        request = RequestFactory().get("/admin/")
        request.user = AnonymousUser()
        form_class = model_admin.get_form(request, self.root)
        form = form_class(instance=self.root)

        parent_ids = set(
            form.fields["parent_group"].queryset.values_list("pk", flat=True)
        )

        self.assertNotIn(self.root.pk, parent_ids)
        self.assertNotIn(self.child.pk, parent_ids)
        self.assertNotIn(self.grandchild.pk, parent_ids)
        self.assertIn(self.sibling.pk, parent_ids)
        self.assertNotIn(self.other_section_group.pk, parent_ids)

    def test_repeatable_group_inline_exposes_parent_group(self):
        self.assertIn("parent_group", FormRepeatableGroupInline.fields)

    def test_repeatable_group_inline_scopes_parent_group_per_row(self):
        inline = FormRepeatableGroupInline(
            FormSection,
            dolphin_admin_site,
        )
        request = RequestFactory().get("/admin/")
        request.user = AnonymousUser()
        formset_class = inline.get_formset(request, self.section)
        formset = formset_class(instance=self.section)

        root_form = next(
            form for form in formset.forms
            if form.instance.pk == self.root.pk
        )
        root_parent_ids = set(
            root_form.fields["parent_group"].queryset.values_list("pk", flat=True)
        )

        self.assertNotIn(self.root.pk, root_parent_ids)
        self.assertNotIn(self.child.pk, root_parent_ids)
        self.assertNotIn(self.grandchild.pk, root_parent_ids)
        self.assertIn(self.sibling.pk, root_parent_ids)
        self.assertNotIn(self.other_section_group.pk, root_parent_ids)
