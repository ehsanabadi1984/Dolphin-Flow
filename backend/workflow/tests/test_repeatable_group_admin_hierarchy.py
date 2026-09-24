from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from workflow.admin import (
    FormRepeatableGroupAdmin,
    FormRepeatableGroupInline,
    dolphin_admin_site,
)
from workflow.form_workspace import FormRepeatableGroupWorkspaceForm
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
            FormRepeatableGroup,
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
