from django.test import TestCase

from workflow.form_draft_current_state_payload_services import (
    FormDraftCurrentStatePayloadService,
)
from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.models import (
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
)


class FormDraftCurrentStatePayloadServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Current State Workflow",
            code="CURRENT_STATE_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Current State Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Current State Section",
            code="CURRENT_STATE_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    def create_field(
        self,
        *,
        code,
        group=None,
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
            order=1,
        )

    def create_group(
        self,
        *,
        code,
        group_type=FormRepeatableGroup.GroupType.NORMAL,
        parent_group=None,
        order=1,
    ):
        return FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name=code.title(),
            code=code,
            order=order,
            group_type=group_type,
        )

    def test_builds_all_normal_fields_from_form_data(self):
        name = self.create_field(code="name")
        phone = self.create_field(code="phone")

        FormData.objects.create(
            instance=self.instance,
            data={
                name.code: "Ehsan",
                phone.code: "0912",
            },
        )

        payload = FormDraftCurrentStatePayloadService.build(
            instance=self.instance,
            form=self.form,
        )

        self.assertIsInstance(payload, NormalizedFormPayload)
        self.assertEqual(
            payload.normal_fields,
            {
                "name": "Ehsan",
                "phone": "0912",
            },
        )

    def test_missing_normal_field_is_explicitly_empty(self):
        self.create_field(code="name")

        payload = FormDraftCurrentStatePayloadService.build(
            instance=self.instance,
            form=self.form,
        )

        self.assertEqual(payload.normal_fields, {"name": ""})

    def test_builds_repeatable_rows_and_values(self):
        group = self.create_group(code="items")
        name = self.create_field(code="name", group=group)

        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=name,
            text_value="saved",
        )

        payload = FormDraftCurrentStatePayloadService.build(
            instance=self.instance,
            form=self.form,
        )

        self.assertEqual(
            payload.repeatable_groups,
            {
                "items": (
                    NormalizedRow(
                        row_id=row.pk,
                        fields={"name": "saved"},
                        child_groups={},
                    ),
                )
            },
        )

    def test_empty_repeatable_group_is_explicitly_empty(self):
        group = self.create_group(code="items")

        payload = FormDraftCurrentStatePayloadService.build(
            instance=self.instance,
            form=self.form,
        )

        self.assertEqual(
            payload.repeatable_groups,
            {"items": ()},
        )

    def test_builds_nested_repeatable_groups(self):
        parent_group = self.create_group(code="orders")
        child_group = self.create_group(
            code="items",
            parent_group=parent_group,
            order=2,
        )
        parent_field = self.create_field(
            code="order_name",
            group=parent_group,
        )
        child_field = self.create_field(
            code="item_name",
            group=child_group,
        )

        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=parent_row,
            field=parent_field,
            text_value="Order 1",
        )

        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=child_field,
            text_value="Item 1",
        )

        payload = FormDraftCurrentStatePayloadService.build(
            instance=self.instance,
            form=self.form,
        )

        parent = payload.repeatable_groups["orders"][0]

        self.assertEqual(parent.fields, {"order_name": "Order 1"})
        self.assertEqual(
            parent.child_groups["items"][0].fields,
            {"item_name": "Item 1"},
        )

    def test_builds_device_system_fields_from_instance_device(self):
        group = self.create_group(
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        imei = self.create_field(
            code="imei",
            group=group,
            system_key=FormField.SystemKey.IMEI,
        )
        description = self.create_field(
            code="description",
            group=group,
            system_key=FormField.SystemKey.DESCRIPTION,
        )

        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_imei="123456789012345",
            description="Screen broken",
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
            instance_device=instance_device,
        )

        payload = FormDraftCurrentStatePayloadService.build(
            instance=self.instance,
            form=self.form,
        )

        self.assertEqual(
            payload.repeatable_groups["devices"][0].fields,
            {
                imei.code: "123456789012345",
                description.code: "Screen broken",
            },
        )
