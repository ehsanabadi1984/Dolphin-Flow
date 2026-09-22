from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_diff_services import FormDraftDiffService
from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.form_draft_permission_services import FormDraftPermissionService
from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableRow,
    RepeatableRowValue,
    Workflow,
    WorkflowInstance,
)
from workflow.permission_context import (
    FieldPermission,
    GroupPermission,
    PermissionContext,
)


class NestedRepeatablePermissionTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Nested Permission Workflow",
            code="NESTED_PERMISSION_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Nested Permission Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Nested Permission Section",
            code="NESTED_PERMISSION_SECTION",
            order=1,
        )
        self.parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parents",
            code="parents",
            order=1,
        )
        self.child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.parent_group,
            name="Children",
            code="children",
            order=2,
        )
        self.parent_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.parent_group,
            name="Parent Name",
            code="parent_name",
            label="Parent Name",
            field_type=FormField.FieldType.TEXT,
        )
        self.child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.child_group,
            name="Child Name",
            code="child_name",
            label="Child Name",
            field_type=FormField.FieldType.TEXT,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )
        self.parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.parent_group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=self.parent_row,
            field=self.parent_field,
            text_value="parent",
        )
        self.child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.child_group,
            parent_row=self.parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=self.child_row,
            field=self.child_field,
            text_value="old child",
        )

    @staticmethod
    def row(*, row_id=None, fields=None, child_groups=None):
        return NormalizedRow(
            row_id=row_id,
            fields=fields or {},
            child_groups=child_groups or {},
        )

    def payload(self, parent_row):
        return NormalizedFormPayload(
            normal_fields={},
            repeatable_groups={
                self.parent_group.code: (parent_row,),
            },
        )

    def permission_context(
        self,
        *,
        parent_permission,
        child_permission,
        parent_field_edit=True,
        child_field_edit=True,
    ):
        return PermissionContext(
            roles=frozenset(),
            normal_fields={},
            repeatable_fields={
                self.parent_field.pk: FieldPermission(
                    can_view=True,
                    can_edit=parent_field_edit,
                ),
                self.child_field.pk: FieldPermission(
                    can_view=True,
                    can_edit=child_field_edit,
                ),
            },
            groups={
                self.parent_group.pk: parent_permission,
                self.child_group.pk: child_permission,
            },
        )

    def build_diff(self, parent_row):
        return FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(parent_row),
        )

    def parent_permission(self, *, can_edit=True, can_add=True, can_delete=True):
        return GroupPermission(
            can_view=True,
            can_edit=can_edit,
            can_add=can_add,
            can_delete=can_delete,
        )

    def child_permission(self, *, can_edit=True, can_add=True, can_delete=True):
        return GroupPermission(
            can_view=True,
            can_edit=can_edit,
            can_add=can_add,
            can_delete=can_delete,
        )

    def test_child_create_does_not_require_parent_edit_permission(self):
        diff = self.build_diff(
            self.row(
                row_id=self.parent_row.pk,
                fields={"parent_name": "parent"},
                child_groups={
                    "children": (
                        self.row(fields={"child_name": "new child"}),
                    ),
                },
            )
        )
        context = self.permission_context(
            parent_permission=self.parent_permission(can_edit=False),
            child_permission=self.child_permission(can_add=True),
        )

        FormDraftPermissionService.validate(
            diff=diff,
            permission_context=context,
        )

    def test_child_update_does_not_require_parent_edit_permission(self):
        diff = self.build_diff(
            self.row(
                row_id=self.parent_row.pk,
                fields={"parent_name": "parent"},
                child_groups={
                    "children": (
                        self.row(
                            row_id=self.child_row.pk,
                            fields={"child_name": "changed child"},
                        ),
                    ),
                },
            )
        )
        context = self.permission_context(
            parent_permission=self.parent_permission(can_edit=False),
            child_permission=self.child_permission(can_edit=True),
        )

        FormDraftPermissionService.validate(
            diff=diff,
            permission_context=context,
        )

    def test_child_delete_does_not_require_parent_edit_permission(self):
        diff = self.build_diff(
            self.row(
                row_id=self.parent_row.pk,
                fields={"parent_name": "parent"},
                child_groups={"children": ()},
            )
        )
        context = self.permission_context(
            parent_permission=self.parent_permission(can_edit=False),
            child_permission=self.child_permission(can_delete=True),
        )

        FormDraftPermissionService.validate(
            diff=diff,
            permission_context=context,
        )

    def test_child_update_requires_child_edit_permission(self):
        diff = self.build_diff(
            self.row(
                row_id=self.parent_row.pk,
                fields={"parent_name": "parent"},
                child_groups={
                    "children": (
                        self.row(
                            row_id=self.child_row.pk,
                            fields={"child_name": "changed child"},
                        ),
                    ),
                },
            )
        )
        context = self.permission_context(
            parent_permission=self.parent_permission(can_edit=True),
            child_permission=self.child_permission(can_edit=False),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_child_create_requires_child_add_permission(self):
        diff = self.build_diff(
            self.row(
                row_id=self.parent_row.pk,
                fields={"parent_name": "parent"},
                child_groups={
                    "children": (
                        self.row(fields={"child_name": "new child"}),
                    ),
                },
            )
        )
        context = self.permission_context(
            parent_permission=self.parent_permission(can_edit=False),
            child_permission=self.child_permission(can_add=False),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_child_delete_requires_child_delete_permission(self):
        diff = self.build_diff(
            self.row(
                row_id=self.parent_row.pk,
                fields={"parent_name": "parent"},
                child_groups={"children": ()},
            )
        )
        context = self.permission_context(
            parent_permission=self.parent_permission(can_edit=False),
            child_permission=self.child_permission(can_delete=False),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_parent_change_still_requires_parent_edit_permission(self):
        diff = self.build_diff(
            self.row(
                row_id=self.parent_row.pk,
                fields={"parent_name": "changed parent"},
                child_groups={
                    "children": (
                        self.row(
                            row_id=self.child_row.pk,
                            fields={"child_name": "old child"},
                        ),
                    ),
                },
            )
        )
        context = self.permission_context(
            parent_permission=self.parent_permission(can_edit=False),
            child_permission=self.child_permission(can_edit=True),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )
