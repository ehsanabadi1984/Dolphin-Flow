from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormSection,
    FormRepeatableGroup,
    InstanceDevice,
    RepeatableRow,
    RepeatableRowValue,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)


User = get_user_model()


class WorkflowInstancePostAdapterIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="operator-post-user",
            password="password",
        )
        self.workflow = Workflow.objects.create(
            name="Operator POST Workflow",
            code="OPERATOR_POST_WF",
            is_active=True,
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Operator POST Step",
            code="OPERATOR_POST_STEP",
            order=1,
            is_active=True,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Operator POST Form",
            is_active=True,
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Operator POST Section",
            code="OPERATOR_POST_SECTION",
            order=1,
        )
        self.name_field = FormField.objects.create(
            section=self.section,
            name="Customer Name",
            code="customer_name",
            label="Customer Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        self.enabled_field = FormField.objects.create(
            section=self.section,
            name="Enabled",
            code="enabled",
            label="Enabled",
            field_type=FormField.FieldType.BOOLEAN,
            order=1,
        )
        self.number_field = FormField.objects.create(
            section=self.section,
            name="Amount",
            code="amount",
            label="Amount",
            field_type=FormField.FieldType.NUMBER,
            order=2,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
        )
        self.execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        for field in (self.name_field, self.enabled_field, self.number_field):
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
            )
        self.client.force_login(self.user)

    def _create_device_group(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=3,
        )
        label_field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Label",
            code="label",
            label="Label",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        FieldAccess.objects.create(
            field=label_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        return group, label_field

    def test_workflow_instance_post_uses_draft_pipeline_and_persists_normal_fields(self):
        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "customer_name": "Ehsan",
                "enabled": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
        )

        form_data = FormData.objects.get(instance=self.instance)
        self.assertEqual(
            form_data.data,
            {
                "customer_name": "Ehsan",
                "enabled": True,
            },
        )

    
    def test_workflow_instance_post_validation_error_does_not_persist_invalid_value_and_preserves_posted_value(self):
        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "customer_name": "Ehsan",
                "enabled": "on",
                "amount": "not-a-number",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            FormData.objects.filter(instance=self.instance).count(),
            0,
        )

        dynamic_form = response.context["dynamic_form"]
        amount_item = next(
            item
            for section in dynamic_form["sections"]
            for item in section["fields"]
            if item["field"].code == "amount"
        )
        self.assertEqual(amount_item["value"], "not-a-number")

    def test_workflow_instance_post_creates_new_device_row(self):
        group, label_field = self._create_device_group()

        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "devices_0_label": "New device",
            },
        )

        self.assertEqual(response.status_code, 302)

        instance_device = InstanceDevice.objects.get(
            instance=self.instance,
            is_active=True,
        )
        row = RepeatableRow.objects.get(
            instance=self.instance,
            group=group,
        )

        self.assertEqual(row.instance_device_id, instance_device.pk)
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=row,
                field=label_field,
            ).text_value,
            "New device",
        )

    def test_workflow_instance_post_updates_existing_device_row(self):
        group, label_field = self._create_device_group()
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_imei="",
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=label_field,
            text_value="Old device",
        )

        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "devices_0_label": "Updated device",
                "devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            InstanceDevice.objects.filter(
                instance=self.instance,
                is_active=True,
            ).count(),
            1,
        )

        row.refresh_from_db()
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=row,
                field=label_field,
            ).text_value,
            "Updated device",
        )
