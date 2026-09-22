from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.form_draft_submit_validation_services import (
    FormDraftSubmitValidationService,
)
from workflow.models import (
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    RepeatableRow,
    Workflow,
    WorkflowInstance,
)


class FormDraftSubmitValidationServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Submit Workflow",
            code="SUBMIT_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Submit Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Submit Section",
            code="SUBMIT_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    def create_field(
        self,
        *,
        code,
        required=False,
        group=None,
    ):
        return FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=code.title(),
            code=code,
            label=code.title(),
            field_type=FormField.FieldType.TEXT,
            is_required=required,
        )

    def create_group(
        self,
        *,
        code,
        required=False,
        group_type=FormRepeatableGroup.GroupType.NORMAL,
        parent_group=None,
    ):
        return FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name=code.title(),
            code=code,
            order=1 if parent_group is None else 2,
            is_required=required,
            group_type=group_type,
        )

    def payload(self, *, normal=None, groups=None):
        return NormalizedFormPayload(
            normal_fields=normal or {},
            repeatable_groups=groups or {},
        )

    def test_required_normal_field_rejects_empty_value(self):
        field = self.create_field(code="name", required=True)

        with self.assertRaises(ValidationError):
            FormDraftSubmitValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                normalized_payload=self.payload(
                    normal={field.code: ""},
                ),
            )

    def test_required_normal_field_accepts_persisted_value_when_omitted(self):
        field = self.create_field(code="name", required=True)
        FormData.objects.create(
            instance=self.instance,
            data={field.code: "saved"},
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(),
        )

    def test_required_group_rejects_explicit_empty_group(self):
        group = self.create_group(code="items", required=True)
        self.create_field(code="name", group=group, required=True)

        with self.assertRaises(ValidationError):
            FormDraftSubmitValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                normalized_payload=self.payload(
                    groups={group.code: ()},
                ),
            )

    def test_required_group_accepts_omitted_group_when_rows_persist(self):
        group = self.create_group(code="items", required=True)
        self.create_field(code="name", group=group, required=True)
        RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(),
        )

    def test_required_repeatable_field_rejects_missing_new_row_value(self):
        group = self.create_group(code="items")
        field = self.create_field(
            code="name",
            group=group,
            required=True,
        )

        row = NormalizedRow(
            row_id=None,
            fields={},
            child_groups={},
        )

        with self.assertRaises(ValidationError):
            FormDraftSubmitValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                normalized_payload=self.payload(
                    groups={group.code: (row,)},
                ),
            )

    def test_required_repeatable_field_accepts_persisted_value_when_omitted(self):
        group = self.create_group(code="items")
        field = self.create_field(
            code="name",
            group=group,
            required=True,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        from workflow.models import RepeatableRowValue

        RepeatableRowValue.objects.create(
            row=row,
            field=field,
            text_value="saved",
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(),
        )

    def test_explicit_empty_required_existing_field_rejects_submit(self):
        group = self.create_group(code="items")
        field = self.create_field(
            code="name",
            group=group,
            required=True,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        with self.assertRaises(ValidationError):
            FormDraftSubmitValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                normalized_payload=self.payload(
                    groups={
                        group.code: (
                            NormalizedRow(
                                row_id=row.pk,
                                fields={field.code: ""},
                                child_groups={},
                            ),
                        )
                    },
                ),
            )

    def test_device_group_requires_at_least_one_row(self):
        group = self.create_group(
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )

        with self.assertRaises(ValidationError):
            FormDraftSubmitValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                normalized_payload=self.payload(
                    groups={group.code: ()},
                ),
            )

    def test_device_group_accepts_existing_row(self):
        group = self.create_group(
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        device_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(),
        )
