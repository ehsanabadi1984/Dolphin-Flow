from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_diff_services import FormDraftDiffService
from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.form_draft_permission_services import FormDraftPermissionService
from workflow.models import (
    DeviceType,
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
    WorkflowStep,
)
from workflow.permission_context import (
    FieldPermission,
    GroupPermission,
    PermissionContext,
)


class FormDraftPermissionServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Permission Draft Workflow",
            code="PERMISSION_DRAFT_WF",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Draft Step",
            code="DRAFT_STEP",
            order=1,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Permission Draft Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Draft Section",
            code="DRAFT_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
        )

    def create_group(
        self,
        *,
        code="items",
        group_type=FormRepeatableGroup.GroupType.NORMAL,
    ):
        return FormRepeatableGroup.objects.create(
            section=self.section,
            name=code.title(),
            code=code,
            order=1,
            group_type=group_type,
        )

    def create_field(
        self,
        group,
        *,
        code="item_name",
        field_type=FormField.FieldType.TEXT,
        system_key=FormField.SystemKey.NONE,
    ):
        return FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=code.title(),
            code=code,
            label=code.title(),
            field_type=field_type,
            system_key=system_key,
        )

    @staticmethod
    def payload(group, rows):
        return NormalizedFormPayload(
            normal_fields={},
            repeatable_groups={
                group.code: tuple(rows),
            },
        )

    @staticmethod
    def row(*, row_id=None, fields=None):
        return NormalizedRow(
            row_id=row_id,
            fields=fields or {},
            child_groups={},
        )

    @staticmethod
    def permission_context(*, group, field, group_permission, field_permission):
        return PermissionContext(
            roles=frozenset(),
            normal_fields={},
            repeatable_fields={
                field.pk: field_permission,
            },
            groups={
                group.pk: group_permission,
            },
        )

    def build_diff(self, group, rows):
        return FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=self.payload(group, rows),
        )

    def normal_permission_context(self, fields):
        return PermissionContext(
            roles=frozenset(),
            normal_fields={
                field.pk: permission
                for field, permission in fields
            },
            repeatable_fields={},
            groups={},
        )

    def test_normal_field_change_requires_can_edit(self):
        field = FormField.objects.create(
            section=self.section,
            name="Customer Name",
            code="customer_name_normal_permission",
            label="Customer Name",
            field_type=FormField.FieldType.TEXT,
        )
        FormData.objects.create(
            instance=self.instance,
            data={field.code: "old"},
        )

        payload = NormalizedFormPayload(
            normal_fields={field.code: "new"},
            repeatable_groups={},
        )
        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )
        context = self.normal_permission_context(
            [
                (
                    field,
                    FieldPermission(can_view=True, can_edit=False),
                )
            ]
        )

        self.assertEqual(len(diff.normal_fields), 1)
        self.assertTrue(diff.normal_fields[0].changed)

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

        self.assertEqual(
            FormData.objects.get(instance=self.instance).data[field.code],
            "old",
        )

    def test_normal_field_same_value_is_allowed_without_edit_permission(self):
        field = FormField.objects.create(
            section=self.section,
            name="Customer Name",
            code="customer_name_normal_same",
            label="Customer Name",
            field_type=FormField.FieldType.TEXT,
        )
        FormData.objects.create(
            instance=self.instance,
            data={field.code: "same"},
        )

        payload = NormalizedFormPayload(
            normal_fields={field.code: "same"},
            repeatable_groups={},
        )
        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )
        context = self.normal_permission_context(
            [
                (
                    field,
                    FieldPermission(can_view=True, can_edit=False),
                )
            ]
        )

        self.assertFalse(diff.normal_fields[0].changed)

        FormDraftPermissionService.validate(
            diff=diff,
            permission_context=context,
        )

    def test_normal_field_change_with_can_edit_is_allowed(self):
        field = FormField.objects.create(
            section=self.section,
            name="Customer Name",
            code="customer_name_normal_editable",
            label="Customer Name",
            field_type=FormField.FieldType.TEXT,
        )
        FormData.objects.create(
            instance=self.instance,
            data={field.code: "old"},
        )

        payload = NormalizedFormPayload(
            normal_fields={field.code: "new"},
            repeatable_groups={},
        )
        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )
        context = self.normal_permission_context(
            [
                (
                    field,
                    FieldPermission(can_view=True, can_edit=True),
                )
            ]
        )

        FormDraftPermissionService.validate(
            diff=diff,
            permission_context=context,
        )

    def test_multiple_normal_fields_validate_independently(self):
        editable = FormField.objects.create(
            section=self.section,
            name="Editable",
            code="editable_normal",
            label="Editable",
            field_type=FormField.FieldType.TEXT,
        )
        locked = FormField.objects.create(
            section=self.section,
            name="Locked",
            code="locked_normal",
            label="Locked",
            field_type=FormField.FieldType.TEXT,
        )
        FormData.objects.create(
            instance=self.instance,
            data={
                editable.code: "old-editable",
                locked.code: "old-locked",
            },
        )

        payload = NormalizedFormPayload(
            normal_fields={
                editable.code: "new-editable",
                locked.code: "new-locked",
            },
            repeatable_groups={},
        )
        diff = FormDraftDiffService.build(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )
        context = self.normal_permission_context(
            [
                (
                    editable,
                    FieldPermission(can_view=True, can_edit=True),
                ),
                (
                    locked,
                    FieldPermission(can_view=True, can_edit=False),
                ),
            ]
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_create_requires_group_can_add(self):
        group = self.create_group()
        field = self.create_field(group)

        diff = self.build_diff(
            group,
            [self.row(fields={"item_name": "new"})],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=True,
                can_add=False,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=True,
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_update_requires_group_can_edit(self):
        group = self.create_group()
        field = self.create_field(group)
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        diff = self.build_diff(
            group,
            [self.row(row_id=row.pk, fields={"item_name": "updated"})],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=False,
                can_add=True,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=True,
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_delete_requires_group_can_delete(self):
        group = self.create_group()
        field = self.create_field(group)
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )

        diff = self.build_diff(group, [])
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=False,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=True,
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_group_permission_does_not_imply_field_permission_for_existing_row(self):
        group = self.create_group()
        field = self.create_field(group)
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=field,
            text_value="old",
        )

        diff = self.build_diff(
            group,
            [self.row(row_id=row.pk, fields={"item_name": "new"})],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=False,
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_non_editable_existing_field_same_value_is_allowed(self):
        group = self.create_group()
        field = self.create_field(group)
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=field,
            text_value="same",
        )

        diff = self.build_diff(
            group,
            [self.row(row_id=row.pk, fields={"item_name": "same"})],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=False,
            ),
        )

        FormDraftPermissionService.validate(
            diff=diff,
            permission_context=context,
        )

    def test_non_editable_existing_field_different_value_is_rejected(self):
        group = self.create_group()
        field = self.create_field(group)
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=field,
            text_value="old",
        )

        diff = self.build_diff(
            group,
            [self.row(row_id=row.pk, fields={"item_name": "new"})],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=False,
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_non_editable_field_on_new_row_is_rejected(self):
        group = self.create_group()
        field = self.create_field(group)

        diff = self.build_diff(
            group,
            [self.row(fields={"item_name": "new"})],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=False,
                can_add=True,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=False,
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_non_editable_field_can_be_omitted_from_existing_update(self):
        group = self.create_group()
        field = self.create_field(group)
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=field,
            text_value="preserve",
        )

        diff = self.build_diff(
            group,
            [self.row(row_id=row.pk, fields={})],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=False,
            ),
        )

        FormDraftPermissionService.validate(
            diff=diff,
            permission_context=context,
        )

    def test_device_system_field_uses_field_permission_independently(self):
        group = self.create_group(
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        field = self.create_field(
            group,
            code="imei",
            system_key=FormField.SystemKey.IMEI,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            draft_imei="123456789012345",
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
            instance_device=instance_device,
        )

        diff = self.build_diff(
            group,
            [
                self.row(
                    row_id=row.pk,
                    fields={"imei": "999999999999999"},
                )
            ],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=False,
            ),
        )

        with self.assertRaises(ValidationError):
            FormDraftPermissionService.validate(
                diff=diff,
                permission_context=context,
            )

    def test_editable_device_system_field_is_allowed(self):
        group = self.create_group(
            code="devices_editable",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        field = self.create_field(
            group,
            code="imei",
            system_key=FormField.SystemKey.IMEI,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            draft_imei="123456789012345",
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
            instance_device=instance_device,
        )

        diff = self.build_diff(
            group,
            [
                self.row(
                    row_id=row.pk,
                    fields={"imei": "999999999999999"},
                )
            ],
        )
        context = self.permission_context(
            group=group,
            field=field,
            group_permission=GroupPermission(
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            ),
            field_permission=FieldPermission(
                can_view=True,
                can_edit=True,
            ),
        )

        FormDraftPermissionService.validate(
            diff=diff,
            permission_context=context,
        )
