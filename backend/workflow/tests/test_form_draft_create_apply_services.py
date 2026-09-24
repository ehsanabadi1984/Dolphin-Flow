from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_create_apply_services import FormDraftCreateApplyService
from workflow.form_draft_diff_services import FormDraftDiffService, RowChangeAction
from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
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


class FormDraftCreateApplyServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Create Apply Workflow",
            code="CREATE_APPLY_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Create Apply Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Create Apply Section",
            code="CREATE_APPLY_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    def create_group(
        self,
        *,
        code,
        field_type=FormField.FieldType.TEXT,
        parent_group=None,
        group_type=FormRepeatableGroup.GroupType.NORMAL,
        order=1,
    ):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name=code.title(),
            code=code,
            group_type=group_type,
            order=order,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=f"{code} name",
            code=f"{code}_name",
            label=f"{code} name",
            field_type=field_type,
        )
        return group, field

    @staticmethod
    def row(*, row_id=None, fields=None, child_groups=None):
        return NormalizedRow(
            row_id=row_id,
            fields=fields or {},
            child_groups=child_groups or {},
        )

    def build_diff(self, **groups):
        payload = NormalizedFormPayload(
            normal_fields={},
            repeatable_groups={
                code: tuple(rows)
                for code, rows in groups.items()
            },
        )
        return FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )

    def test_create_persists_row_and_values(self):
        group, field = self.create_group(code="items")

        diff = self.build_diff(
            items=[
                self.row(fields={"items_name": "First"}),
            ],
        )

        created = FormDraftCreateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        self.assertEqual(len(created), 1)
        row = next(iter(created.values()))

        self.assertEqual(row.instance_id, self.instance.pk)
        self.assertEqual(row.group_id, group.pk)
        self.assertEqual(row.row_order, 0)

        value = RepeatableRowValue.objects.get(
            row=row,
            field=field,
        )
        self.assertEqual(value.text_value, "First")

    def test_multiple_creates_receive_sequential_row_order(self):
        group, _ = self.create_group(code="items")

        diff = self.build_diff(
            items=[
                self.row(fields={"items_name": "First"}),
                self.row(fields={"items_name": "Second"}),
            ],
        )

        FormDraftCreateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        rows = list(
            RepeatableRow.objects
            .filter(instance=self.instance, group=group)
            .order_by("row_order", "id")
        )

        self.assertEqual(
            [row.row_order for row in rows],
            [0, 1],
        )

    def test_nested_create_resolves_new_parent_reference(self):
        parent_group, _ = self.create_group(
            code="parents",
            order=1,
        )
        child_group, child_field = self.create_group(
            code="children",
            parent_group=parent_group,
            order=2,
        )

        diff = self.build_diff(
            parents=[
                self.row(
                    fields={"parents_name": "Parent"},
                    child_groups={
                        "children": (
                            self.row(fields={"children_name": "Child"}),
                        ),
                    },
                ),
            ],
        )

        created = FormDraftCreateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        parent_row = next(
            row for row in created.values()
            if row.group_id == parent_group.pk
        )
        child_row = next(
            row for row in created.values()
            if row.group_id == child_group.pk
        )

        self.assertEqual(child_row.parent_row_id, parent_row.pk)
        self.assertEqual(child_row.row_order, 0)
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=child_row,
                field=child_field,
            ).text_value,
            "Child",
        )


    def test_nested_create_persists_parent_child_grandchild_chain(self):
        parent_group, parent_field = self.create_group(
            code="parents_depth_three",
            order=1,
        )
        child_group, child_field = self.create_group(
            code="children_depth_three",
            parent_group=parent_group,
            order=2,
        )
        grandchild_group, grandchild_field = self.create_group(
            code="grandchildren_depth_three",
            parent_group=child_group,
            order=3,
        )

        diff = self.build_diff(
            parents_depth_three=[
                self.row(
                    fields={"parents_depth_three_name": "Parent"},
                    child_groups={
                        "children_depth_three": (
                            self.row(
                                fields={"children_depth_three_name": "Child"},
                                child_groups={
                                    "grandchildren_depth_three": (
                                        self.row(
                                            fields={
                                                "grandchildren_depth_three_name": "Grandchild"
                                            }
                                        ),
                                    ),
                                },
                            ),
                        ),
                    },
                ),
            ],
        )

        created = FormDraftCreateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        parent_row = next(
            row for row in created.values()
            if row.group_id == parent_group.pk
        )
        child_row = next(
            row for row in created.values()
            if row.group_id == child_group.pk
        )
        grandchild_row = next(
            row for row in created.values()
            if row.group_id == grandchild_group.pk
        )

        self.assertEqual(child_row.parent_row_id, parent_row.pk)
        self.assertEqual(grandchild_row.parent_row_id, child_row.pk)
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=parent_row,
                field=parent_field,
            ).text_value,
            "Parent",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=child_row,
                field=child_field,
            ).text_value,
            "Child",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=grandchild_row,
                field=grandchild_field,
            ).text_value,
            "Grandchild",
        )

    def test_new_child_can_attach_to_existing_parent(self):
        parent_group, _ = self.create_group(
            code="parents",
            order=1,
        )
        child_group, _ = self.create_group(
            code="children",
            parent_group=parent_group,
            order=2,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
            row_order=0,
        )

        diff = self.build_diff(
            parents=[
                self.row(
                    row_id=parent_row.pk,
                    child_groups={
                        "children": (
                            self.row(fields={"children_name": "Child"}),
                        ),
                    },
                ),
            ],
        )

        created = FormDraftCreateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        child_row = next(
            row for row in created.values()
            if row.group_id == child_group.pk
        )
        self.assertEqual(child_row.parent_row_id, parent_row.pk)

    def test_update_and_delete_changes_are_not_applied(self):
        group, _ = self.create_group(code="items")
        existing_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        deleted_candidate = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=1,
        )

        diff = self.build_diff(
            items=[
                self.row(
                    row_id=existing_row.pk,
                    fields={"items_name": "Updated"},
                ),
                self.row(fields={"items_name": "New"}),
            ],
        )

        created = FormDraftCreateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        self.assertEqual(len(created), 1)
        self.assertTrue(
            RepeatableRow.objects.filter(pk=existing_row.pk).exists()
        )
        self.assertTrue(
            RepeatableRow.objects.filter(pk=deleted_candidate.pk).exists()
        )
        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).count(),
            3,
        )
        self.assertFalse(
            RepeatableRowValue.objects.filter(
                row=existing_row,
            ).exists()
        )

    def test_device_create_is_skipped_for_device_groups(self):
        group, _ = self.create_group(
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )

        diff = self.build_diff(
            devices=[
                self.row(fields={"devices_name": "Device"}),
            ],
        )

        FormDraftCreateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )


        self.assertFalse(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).exists()
        )

    def test_failed_create_rolls_back_all_previous_creates(self):
        group, _ = self.create_group(
            code="items",
            field_type=FormField.FieldType.BOOLEAN,
        )

        diff = self.build_diff(
            items=[
                self.row(fields={"items_name": True}),
                self.row(fields={"items_name": "not-a-boolean"}),
            ],
        )

        with self.assertRaises(ValidationError):
            FormDraftCreateApplyService.apply(
                instance=self.instance,
                diff=diff,
            )

        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).count(),
            0,
        )
        self.assertEqual(
            RepeatableRowValue.objects.filter(
                row__instance=self.instance,
            ).count(),
            0,
        )
