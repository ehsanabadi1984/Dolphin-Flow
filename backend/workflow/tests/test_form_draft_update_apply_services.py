from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_diff_services import FormDraftDiffService
from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.form_draft_update_apply_services import FormDraftUpdateApplyService
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


class FormDraftUpdateApplyServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Update Apply Workflow",
            code="UPDATE_APPLY_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Update Apply Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Update Apply Section",
            code="UPDATE_APPLY_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    def create_group(
        self,
        *,
        code,
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
        fields = {}
        for field_order, (field_code, field_type) in enumerate(
            (
                (f"{code}_name", FormField.FieldType.TEXT),
                (f"{code}_number", FormField.FieldType.NUMBER),
            )
        ):
            fields[field_code] = FormField.objects.create(
                section=self.section,
                repeatable_group=group,
                name=field_code,
                code=field_code,
                label=field_code,
                field_type=field_type,
                order=field_order,
            )
        return group, fields

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

    def test_update_persists_explicit_field_values(self):
        group, fields = self.create_group(code="items")
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=fields["items_name"],
            text_value="Old",
        )

        diff = self.build_diff(
            items=[
                self.row(
                    row_id=row.pk,
                    fields={
                        "items_name": "New",
                        "items_number": "12.50",
                    },
                )
            ],
        )

        updated = FormDraftUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[next(iter(updated))].pk, row.pk)

        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=row,
                field=fields["items_name"],
            ).text_value,
            "New",
        )
        self.assertEqual(
            str(
                RepeatableRowValue.objects.get(
                    row=row,
                    field=fields["items_number"],
                ).decimal_value
            ),
            "12.500000",
        )

    def test_omitted_field_is_preserved(self):
        group, fields = self.create_group(code="items")
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=fields["items_name"],
            text_value="Keep me",
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=fields["items_number"],
            decimal_value="7.25",
        )

        diff = self.build_diff(
            items=[
                self.row(
                    row_id=row.pk,
                    fields={"items_name": "Changed"},
                )
            ],
        )

        FormDraftUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=row,
                field=fields["items_name"],
            ).text_value,
            "Changed",
        )
        self.assertEqual(
            str(
                RepeatableRowValue.objects.get(
                    row=row,
                    field=fields["items_number"],
                ).decimal_value
            ),
            "7.250000",
        )

    def test_nested_existing_row_updates_its_own_values(self):
        parent_group, _ = self.create_group(code="parents", order=1)
        child_group, child_fields = self.create_group(
            code="children",
            parent_group=parent_group,
            order=2,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
            row_order=0,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=child_fields["children_name"],
            text_value="Old child",
        )

        diff = self.build_diff(
            parents=[
                self.row(
                    row_id=parent_row.pk,
                    child_groups={
                        "children": (
                            self.row(
                                row_id=child_row.pk,
                                fields={"children_name": "New child"},
                            ),
                        )
                    },
                )
            ],
        )

        FormDraftUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=child_row,
                field=child_fields["children_name"],
            ).text_value,
            "New child",
        )

    def test_update_does_not_change_row_order_or_parent(self):
        parent_group, _ = self.create_group(code="parents", order=1)
        child_group, fields = self.create_group(
            code="children",
            parent_group=parent_group,
            order=2,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
            row_order=3,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
            row_order=5,
        )

        diff = self.build_diff(
            parents=[
                self.row(
                    row_id=parent_row.pk,
                    child_groups={
                        "children": (
                            self.row(
                                row_id=child_row.pk,
                                fields={"children_name": "Updated"},
                            ),
                        )
                    },
                )
            ],
        )

        FormDraftUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        refreshed = RepeatableRow.objects.get(pk=child_row.pk)
        self.assertEqual(refreshed.parent_row_id, parent_row.pk)
        self.assertEqual(refreshed.row_order, 5)

    def test_device_update_is_skipped_for_device_groups(self):
        group, fields = self.create_group(
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        diff = self.build_diff(
            devices=[
                self.row(
                    row_id=row.pk,
                    fields={"devices_name": "Changed"},
                )
            ],
        )

        updated = FormDraftUpdateApplyService.apply(
            instance=self.instance,
            diff=diff,
        )

        self.assertEqual(updated, {})
        self.assertFalse(
            RepeatableRowValue.objects.filter(row=row).exists()
        )

    def test_failed_update_rolls_back_previous_updates(self):
        group, fields = self.create_group(code="items")
        first = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        second = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=1,
        )
        RepeatableRowValue.objects.create(
            row=first,
            field=fields["items_name"],
            text_value="First old",
        )
        RepeatableRowValue.objects.create(
            row=second,
            field=fields["items_name"],
            text_value="Second old",
        )

        diff = self.build_diff(
            items=[
                self.row(
                    row_id=first.pk,
                    fields={"items_name": "First new"},
                ),
                self.row(
                    row_id=second.pk,
                    fields={"items_number": ""},
                ),
            ],
        )

        with self.assertRaises(ValidationError):
            FormDraftUpdateApplyService.apply(
                instance=self.instance,
                diff=diff,
            )

        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=first,
                field=fields["items_name"],
            ).text_value,
            "First old",
        )
        self.assertFalse(
            RepeatableRowValue.objects.filter(
                row=second,
                field=fields["items_number"],
            ).exists()
        )
