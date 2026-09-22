from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.form_draft_structural_validation_services import (
    FormDraftStructuralValidationService,
)
from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableRow,
    Workflow,
    WorkflowInstance,
)


class FormDraftStructuralValidationServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Structural Workflow",
            code="STRUCTURAL_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Structural Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Structural Section",
            code="STRUCTURAL_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    def create_group(self, *, code="items", parent_group=None):
        return FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name=code.title(),
            code=code,
            order=1,
        )

    def create_field(self, *, group=None, code="name"):
        return FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=code.title(),
            code=code,
            label=code.title(),
            field_type=FormField.FieldType.TEXT,
        )

    def test_rejects_unknown_root_key(self):
        self.create_field(code="name")

        with self.assertRaises(ValidationError):
            FormDraftStructuralValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                submitted_data={"unknown": "value"},
            )

    def test_rejects_unknown_row_field(self):
        group = self.create_group()
        self.create_field(group=group, code="name")

        with self.assertRaises(ValidationError):
            FormDraftStructuralValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                submitted_data={
                    "items": [
                        {"unknown": "value"},
                    ]
                },
            )

    def test_rejects_unknown_child_group(self):
        group = self.create_group()
        self.create_field(group=group, code="name")

        with self.assertRaises(ValidationError):
            FormDraftStructuralValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                submitted_data={
                    "items": [
                        {"unknown_children": []},
                    ]
                },
            )

    def test_rejects_duplicate_row_ids(self):
        group = self.create_group()
        self.create_field(group=group, code="name")
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            FormDraftStructuralValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                submitted_data={
                    "items": [
                        {"row_id": row.pk},
                        {"row_id": row.pk},
                    ]
                },
            )

    def test_rejects_row_from_another_instance(self):
        group = self.create_group()
        self.create_field(group=group, code="name")
        other_instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )
        row = RepeatableRow.objects.create(
            instance=other_instance,
            group=group,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            FormDraftStructuralValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                submitted_data={
                    "items": [{"row_id": row.pk}],
                },
            )

    def test_rejects_row_from_another_group(self):
        group = self.create_group(code="items")
        other_group = self.create_group(code="other")
        self.create_field(group=group, code="name")
        self.create_field(group=other_group, code="name")
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=other_group,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            FormDraftStructuralValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                submitted_data={
                    "items": [{"row_id": row.pk}],
                },
            )

    def test_rejects_root_row_that_is_actually_a_child(self):
        group = self.create_group(code="items")
        child_group = self.create_group(code="children", parent_group=group)
        self.create_field(group=group, code="name")
        self.create_field(group=child_group, code="name")
        parent = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        child = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            FormDraftStructuralValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                submitted_data={
                    "items": [{"row_id": child.pk}],
                },
            )

    def test_rejects_existing_child_under_new_parent(self):
        group = self.create_group(code="items")
        child_group = self.create_group(code="children", parent_group=group)
        self.create_field(group=group, code="name")
        self.create_field(group=child_group, code="name")
        parent = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        child = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            FormDraftStructuralValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                submitted_data={
                    "items": [
                        {
                            "name": "new",
                            "children": [{"row_id": child.pk}],
                        }
                    ]
                },
            )

    def test_accepts_new_nested_row_under_existing_parent(self):
        group = self.create_group(code="items_existing_parent")
        child_group = self.create_group(
            code="children_existing_parent",
            parent_group=group,
        )
        self.create_field(group=group, code="name")
        self.create_field(group=child_group, code="name")
        parent = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        FormDraftStructuralValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            submitted_data={
                "items_existing_parent": [
                    {
                        "row_id": parent.pk,
                        "name": "existing parent",
                        "children_existing_parent": [
                            {"name": "new child"},
                        ],
                    }
                ]
            },
        )

    def test_accepts_new_nested_row_tree(self):
        group = self.create_group(code="items")
        child_group = self.create_group(code="children", parent_group=group)
        self.create_field(group=group, code="name")
        self.create_field(group=child_group, code="name")

        FormDraftStructuralValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            submitted_data={
                "items": [
                    {
                        "name": "new",
                        "children": [
                            {"name": "child"},
                        ],
                    }
                ]
            },
        )

    def test_accepts_valid_existing_nested_row_tree(self):
        group = self.create_group(code="items")
        child_group = self.create_group(code="children", parent_group=group)
        self.create_field(group=group, code="name")
        self.create_field(group=child_group, code="name")
        parent = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        child = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent,
            row_order=0,
        )

        FormDraftStructuralValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            submitted_data={
                "items": [
                    {
                        "row_id": parent.pk,
                        "children": [{"row_id": child.pk}],
                    }
                ]
            },
        )

    def test_normalized_validation_keeps_identity_contract(self):
        group = self.create_group()
        self.create_field(group=group, code="name")
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        payload = NormalizedFormPayload(
            normal_fields={},
            repeatable_groups={
                group.code: (
                    NormalizedRow(
                        row_id=row.pk,
                        fields={},
                        child_groups={},
                    ),
                ),
            },
        )

        FormDraftStructuralValidationService.validate_normalized_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )
