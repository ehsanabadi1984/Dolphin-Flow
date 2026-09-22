from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_save_services import FormDraftSaveService
from workflow.models import (
    FieldAccess,
    FormField,
    FormRepeatableGroup,
    RepeatableGroupAccess,
    RepeatableRow,
    RepeatableRowValue,
)
from workflow.tests.test_form_draft_save_services import (
    FormDraftSaveServiceContractTests,
)


class NestedRepeatablePermissionSaveIntegrationTests(
    FormDraftSaveServiceContractTests,
):
    def setUp(self):
        super().setUp()

        self.parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Nested Parents",
            code="nested_parents_integration",
            order=20,
        )
        self.parent_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.parent_group,
            name="Parent Name",
            code="nested_parent_name_integration",
            label="Parent Name",
            field_type=FormField.FieldType.TEXT,
        )
        self.child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.parent_group,
            name="Nested Children",
            code="nested_children_integration",
            order=21,
        )
        self.child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.child_group,
            name="Child Name",
            code="nested_child_name_integration",
            label="Child Name",
            field_type=FormField.FieldType.TEXT,
        )

        self.parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.parent_group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=self.parent_row,
            field=self.parent_field,
            text_value="Parent",
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
            text_value="Old Child",
        )

    def grant_nested_permissions(
        self,
        *,
        parent_can_edit=False,
        child_can_edit=True,
        child_can_add=True,
        child_can_delete=True,
    ):
        RepeatableGroupAccess.objects.create(
            group=self.parent_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=parent_can_edit,
            can_add=True,
            can_delete=True,
        )
        RepeatableGroupAccess.objects.create(
            group=self.child_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=child_can_edit,
            can_add=child_can_add,
            can_delete=child_can_delete,
        )
        FieldAccess.objects.create(
            field=self.parent_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=self.child_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

    def nested_payload(self, *, child_rows):
        return {
            self.parent_group.code: [
                {
                    "row_id": self.parent_row.pk,
                    self.parent_field.code: "Parent",
                    self.child_group.code: child_rows,
                },
            ],
        }

    def test_child_create_is_saved_without_parent_edit_permission(self):
        self.grant_nested_permissions(
            parent_can_edit=False,
            child_can_add=True,
        )

        result = self.call(
            submitted_data=self.nested_payload(
                child_rows=[
                    {
                        "row_id": self.child_row.pk,
                        self.child_field.code: "Old Child",
                    },
                    {
                        "row_id": None,
                        self.child_field.code: "New Child",
                    },
                ],
            ),
        )

        self.assertTrue(result.saved)
        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=self.child_group,
            ).count(),
            2,
        )
        created_child = RepeatableRow.objects.get(
            instance=self.instance,
            group=self.child_group,
            values__field=self.child_field,
            values__text_value="New Child",
        )
        self.assertEqual(created_child.parent_row_id, self.parent_row.pk)
        self.assertEqual(
            self.child_row.values.get(field=self.child_field).text_value,
            "Old Child",
        )

    def test_child_update_is_saved_without_parent_edit_permission(self):
        self.grant_nested_permissions(
            parent_can_edit=False,
            child_can_edit=True,
        )

        result = self.call(
            submitted_data=self.nested_payload(
                child_rows=[
                    {
                        "row_id": self.child_row.pk,
                        self.child_field.code: "Updated Child",
                    },
                ],
            ),
        )

        self.assertTrue(result.saved)
        self.child_row.refresh_from_db()
        self.assertEqual(
            self.child_row.values.get(field=self.child_field).text_value,
            "Updated Child",
        )

    def test_child_delete_is_saved_without_parent_edit_permission(self):
        self.grant_nested_permissions(
            parent_can_edit=False,
            child_can_delete=True,
        )

        result = self.call(
            submitted_data=self.nested_payload(child_rows=[]),
        )

        self.assertTrue(result.saved)
        self.assertFalse(
            RepeatableRow.objects.filter(pk=self.child_row.pk).exists()
        )
        self.assertTrue(
            RepeatableRow.objects.filter(pk=self.parent_row.pk).exists()
        )

    def test_child_create_is_rejected_without_child_add_permission(self):
        self.grant_nested_permissions(
            parent_can_edit=False,
            child_can_add=False,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data=self.nested_payload(
                    child_rows=[
                        {
                            "row_id": None,
                            self.child_field.code: "New Child",
                        },
                    ],
                ),
            )

        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=self.child_group,
            ).count(),
            1,
        )

    def test_child_update_is_rejected_without_child_edit_permission(self):
        self.grant_nested_permissions(
            parent_can_edit=False,
            child_can_edit=False,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data=self.nested_payload(
                    child_rows=[
                        {
                            "row_id": self.child_row.pk,
                            self.child_field.code: "Updated Child",
                        },
                    ],
                ),
            )

        self.child_row.refresh_from_db()
        self.assertEqual(
            self.child_row.values.get(field=self.child_field).text_value,
            "Old Child",
        )

    def test_child_delete_is_rejected_without_child_delete_permission(self):
        self.grant_nested_permissions(
            parent_can_edit=False,
            child_can_delete=False,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data=self.nested_payload(child_rows=[]),
            )

        self.assertTrue(
            RepeatableRow.objects.filter(pk=self.child_row.pk).exists()
        )

    def test_parent_change_is_rejected_without_parent_edit_permission(self):
        self.grant_nested_permissions(
            parent_can_edit=False,
            child_can_edit=True,
        )

        with self.assertRaises(ValidationError):
            self.call(
                submitted_data={
                    self.parent_group.code: [
                        {
                            "row_id": self.parent_row.pk,
                            self.parent_field.code: "Changed Parent",
                            self.child_group.code: [
                                {
                                    "row_id": self.child_row.pk,
                                    self.child_field.code: "Old Child",
                                },
                            ],
                        },
                    ],
                },
            )

        self.parent_row.refresh_from_db()
        self.assertEqual(
            self.parent_row.values.get(field=self.parent_field).text_value,
            "Parent",
        )
