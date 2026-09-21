from django.test import TestCase

from workflow.form_draft_diff_services import (
    FormDraftDiffService,
    RowChangeAction,
    RowReferenceKind,
)
from workflow.form_draft_save_services import NormalizedFormPayload, NormalizedRow
from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableRow,
    Workflow,
    WorkflowInstance,
)


class FormDraftDiffServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Diff Workflow",
            code="DIFF_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Diff Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Diff Section",
            code="DIFF_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    def create_group(self, *, code, parent_group=None, order=1):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name=code.title(),
            code=code,
            order=order,
        )
        FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=f"{code} name",
            code=f"{code}_name",
            label=f"{code} name",
            field_type=FormField.FieldType.TEXT,
        )
        return group

    @staticmethod
    def row(*, row_id=None, fields=None, child_groups=None):
        return NormalizedRow(
            row_id=row_id,
            fields=fields or {},
            child_groups=child_groups or {},
        )

    def payload(self, **groups):
        return NormalizedFormPayload(
            normal_fields={},
            repeatable_groups={
                code: tuple(rows)
                for code, rows in groups.items()
            },
        )

    def test_new_row_is_create(self):
        group = self.create_group(code="items")

        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                items=[self.row(fields={"items_name": "new"})],
            ),
        )

        changes = diff.groups[0].changes
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].action, RowChangeAction.CREATE)
        self.assertIsNone(changes[0].row_id)
        self.assertEqual(
            changes[0].row_reference.kind,
            RowReferenceKind.CREATE,
        )
        self.assertEqual(changes[0].desired_row.fields["items_name"], "new")

    def test_existing_row_is_update(self):
        group = self.create_group(code="items")
        persisted = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                items=[
                    self.row(
                        row_id=persisted.pk,
                        fields={"items_name": "updated"},
                    )
                ],
            ),
        )

        changes = diff.groups[0].changes
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].action, RowChangeAction.UPDATE)
        self.assertEqual(changes[0].row_id, persisted.pk)
        self.assertEqual(
            changes[0].row_reference.value,
            persisted.pk,
        )

    def test_omitted_existing_row_is_delete(self):
        group = self.create_group(code="items")
        persisted = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(items=[]),
        )

        changes = diff.groups[0].changes
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].action, RowChangeAction.DELETE)
        self.assertEqual(changes[0].row_id, persisted.pk)
        self.assertIsNone(changes[0].desired_row)

    def test_group_absent_from_payload_is_untouched(self):
        group = self.create_group(code="items")
        persisted = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=NormalizedFormPayload(
                normal_fields={},
                repeatable_groups={},
            ),
        )

        self.assertEqual(diff.groups, ())
        self.assertTrue(
            RepeatableRow.objects.filter(pk=persisted.pk).exists()
        )

    def test_nested_new_rows_keep_create_parent_reference(self):
        parent = self.create_group(code="parents", order=1)
        child = self.create_group(
            code="children",
            parent_group=parent,
            order=2,
        )

        parent_row = self.row(
            fields={"parents_name": "parent"},
            child_groups={
                "children": (
                    self.row(fields={"children_name": "child"}),
                )
            },
        )

        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                parents=[parent_row],
            ),
        )

        changes = diff.groups[0].changes
        self.assertEqual(len(changes), 2)
        parent_change, child_change = changes

        self.assertEqual(parent_change.action, RowChangeAction.CREATE)
        self.assertEqual(child_change.action, RowChangeAction.CREATE)
        self.assertEqual(
            child_change.parent_reference,
            parent_change.row_reference,
        )
        self.assertEqual(
            child_change.parent_reference.kind,
            RowReferenceKind.CREATE,
        )

    def test_nested_existing_rows_are_updated_under_existing_parent(self):
        parent = self.create_group(code="parents", order=1)
        child = self.create_group(
            code="children",
            parent_group=parent,
            order=2,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent,
            row_order=0,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child,
            parent_row=parent_row,
            row_order=0,
        )

        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                parents=[
                    self.row(
                        row_id=parent_row.pk,
                        child_groups={
                            "children": (
                                self.row(row_id=child_row.pk),
                            )
                        },
                    )
                ],
            ),
        )

        changes = diff.groups[0].changes
        self.assertEqual(
            [change.action for change in changes],
            [RowChangeAction.UPDATE, RowChangeAction.UPDATE],
        )
        self.assertEqual(
            changes[1].parent_reference.value,
            parent_row.pk,
        )

    def test_deleting_parent_produces_child_delete_before_parent_delete(self):
        parent = self.create_group(code="parents", order=1)
        child = self.create_group(
            code="children",
            parent_group=parent,
            order=2,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent,
            row_order=0,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child,
            parent_row=parent_row,
            row_order=0,
        )

        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(parents=[]),
        )

        changes = diff.groups[0].changes
        self.assertEqual(
            [change.row_id for change in changes],
            [child_row.pk, parent_row.pk],
        )
        self.assertEqual(
            [change.action for change in changes],
            [RowChangeAction.DELETE, RowChangeAction.DELETE],
        )
