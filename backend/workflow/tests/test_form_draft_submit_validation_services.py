from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.form_draft_submit_validation_services import (
    FormDraftSubmitValidationService,
)
from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    RepeatableRow,
    RepeatableRowValue,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
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
        self.user = get_user_model().objects.create_user(
            username="submit_validation_user",
            password="test-password",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Submit Step",
            code="SUBMIT_STEP",
            order=1,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        self.instance.current_step = self.step
        self.instance.save(update_fields=["current_step"])

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

    def permission_context(self):
        from workflow.permission_context import PermissionContext

        return PermissionContext.build(
            workflow=self.workflow,
            form=self.form,
            step=self.step,
            user=self.user,
        )

    def test_hidden_required_normal_field_does_not_block_submit(self):
        field = self.create_field(code="hidden_name", required=True)
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=False,
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                normal={field.code: ""},
            ),
            permission_context=self.permission_context(),
        )

    def test_visible_read_only_required_normal_field_does_not_block_submit(self):
        field = self.create_field(code="readonly_name", required=True)
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                normal={field.code: ""},
            ),
            permission_context=self.permission_context(),
        )

    def test_visible_editable_required_normal_field_blocks_submit(self):
        field = self.create_field(code="editable_name", required=True)
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        with self.assertRaises(ValidationError):
            FormDraftSubmitValidationService.validate_payload(
                instance=self.instance,
                form=self.form,
                normalized_payload=self.payload(
                    normal={field.code: ""},
                ),
                permission_context=self.permission_context(),
            )

    def test_hidden_required_repeatable_field_does_not_block_submit(self):
        group = self.create_group(code="items")
        field = self.create_field(code="name", group=group, required=True)
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=False,
        )
        from workflow.models import RepeatableGroupAccess
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        row = NormalizedRow(row_id=None, fields={}, child_groups={})

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                groups={group.code: (row,)},
            ),
            permission_context=self.permission_context(),
        )

    def test_visible_read_only_required_repeatable_field_does_not_block_submit(self):
        group = self.create_group(code="readonly_items")
        field = self.create_field(code="name", group=group, required=True)
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )
        from workflow.models import RepeatableGroupAccess
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
            can_add=True,
            can_delete=True,
        )
        row = NormalizedRow(row_id=None, fields={}, child_groups={})

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                groups={group.code: (row,)},
            ),
            permission_context=self.permission_context(),
        )

    def test_required_group_does_not_block_when_user_cannot_add_rows(self):
        group = self.create_group(code="readonly_group", required=True)
        self.create_field(code="name", group=group, required=True)
        from workflow.models import RepeatableGroupAccess
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
            can_add=False,
            can_delete=False,
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                groups={group.code: ()},
            ),
            permission_context=self.permission_context(),
        )

    def test_required_formula_is_not_checked_as_user_input(self):
        field = self.create_field(code="total", required=True)
        field.field_type = FormField.FieldType.FORMULA
        field.save(update_fields=["field_type"])

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(),
        )

    def test_required_repeatable_formula_is_not_checked_as_user_input(self):
        group = self.create_group(code="items")
        field = self.create_field(
            code="total",
            group=group,
            required=True,
        )
        field.field_type = FormField.FieldType.FORMULA
        field.save(update_fields=["field_type"])

        row = NormalizedRow(
            row_id=None,
            fields={},
            child_groups={},
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(
                groups={group.code: (row,)},
            ),
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
        field = self.create_field(code="name", group=group, required=True)
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
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
