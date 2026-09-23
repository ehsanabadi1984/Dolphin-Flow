from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from workflow.models import (
    Device,
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
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

    def _create_device_group(
        self,
        *,
        can_view=True,
        can_edit=True,
        can_add=True,
        can_delete=True,
        field_can_view=True,
        field_can_edit=True,
    ):
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
            can_view=can_view,
            can_edit=can_edit,
            can_add=can_add,
            can_delete=can_delete,
        )
        FieldAccess.objects.create(
            field=label_field,
            step=self.step,
            user=self.user,
            can_view=field_can_view,
            can_edit=field_can_edit,
        )
        return group, label_field

    def _create_device_system_fields(self, *, field_can_edit=True):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="System Devices",
            code="system_devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=4,
        )
        fields = {}
        definitions = (
            (FormField.SystemKey.IMEI, "system_imei", FormField.FieldType.TEXT),
            (FormField.SystemKey.DEVICE_TYPE, "system_type", FormField.FieldType.SELECT),
            (FormField.SystemKey.DEVICE_MODEL, "system_model", FormField.FieldType.SELECT),
        )
        for order, (system_key, code, field_type) in enumerate(definitions):
            field = FormField.objects.create(
                section=self.section,
                repeatable_group=group,
                name=code,
                code=code,
                label=code,
                field_type=field_type,
                system_key=system_key,
                order=order,
            )
            fields[system_key] = field
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=field_can_edit,
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
        return group, fields


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

    def test_workflow_instance_post_rejects_changed_device_type_without_field_edit_permission(self):
        group, fields = self._create_device_system_fields()
        FieldAccess.objects.filter(
            field=fields[FormField.SystemKey.DEVICE_TYPE],
            step=self.step,
            user=self.user,
        ).update(can_edit=False)
        original_type = DeviceType.objects.create(
            name="Phone",
            code="OP_POST_PHONE_TYPE",
            is_active=True,
        )
        target_type = DeviceType.objects.create(
            name="Tablet",
            code="OP_POST_TABLET_TYPE",
            is_active=True,
        )
        original_model = DeviceModel.objects.create(
            device_type=original_type,
            brand="Test",
            name="Phone X",
            code="OP_POST_PHONE_MODEL",
            is_active=True,
        )
        target_model = DeviceModel.objects.create(
            device_type=target_type,
            brand="Test",
            name="Tablet X",
            code="OP_POST_TABLET_MODEL",
            is_active=True,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_device_model=original_model,
            draft_device_type=original_type,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_type": str(target_type.pk),
                "system_devices_0_system_model": str(target_model.pk),
                "system_devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 400)
        instance_device.refresh_from_db()
        self.assertEqual(instance_device.draft_device_type_id, original_type.pk)
        self.assertEqual(instance_device.draft_device_model_id, original_model.pk)
        self.assertTrue(RepeatableRow.objects.filter(pk=row.pk).exists())

    def test_workflow_instance_post_rejects_changed_device_model_without_field_edit_permission(self):
        group, fields = self._create_device_system_fields()
        FieldAccess.objects.filter(
            field=fields[FormField.SystemKey.DEVICE_MODEL],
            step=self.step,
            user=self.user,
        ).update(can_edit=False)
        device_type = __import__("workflow.models", fromlist=["DeviceType"]).DeviceType.objects.create(
            name="Phone",
            code="OP_POST_MODEL_TYPE",
            is_active=True,
        )
        original_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Phone Original",
            code="OP_POST_MODEL_ORIGINAL",
            is_active=True,
        )
        target_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Phone Target",
            code="OP_POST_MODEL_TARGET",
            is_active=True,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_device_model=original_model,
            draft_device_type=device_type,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_type": str(device_type.pk),
                "system_devices_0_system_model": str(target_model.pk),
                "system_devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 400)
        instance_device.refresh_from_db()
        self.assertEqual(instance_device.draft_device_model_id, original_model.pk)
        self.assertEqual(instance_device.draft_device_type_id, device_type.pk)
        self.assertTrue(RepeatableRow.objects.filter(pk=row.pk).exists())

    def test_workflow_instance_post_rejects_imei_change_on_resolved_device(self):
        group, fields = self._create_device_system_fields()
        device_type = __import__("workflow.models", fromlist=["DeviceType"]).DeviceType.objects.create(
            name="Phone",
            code="OP_POST_IMEI_TYPE",
            is_active=True,
        )
        device_model = __import__("workflow.models", fromlist=["DeviceModel"]).DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Phone X",
            code="OP_POST_IMEI_MODEL",
            is_active=True,
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="111111111111111",
        )
        instance_device = InstanceDevice.objects.create(instance=self.instance, device=device)
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_imei": "222222222222222",
                "system_devices_0_system_type": str(device_type.pk),
                "system_devices_0_system_model": str(device_model.pk),
                "system_devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            DeviceIdentifier.objects.get(device=device).value,
            "111111111111111",
        )
        instance_device.refresh_from_db()
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertTrue(RepeatableRow.objects.filter(pk=row.pk).exists())

    def test_workflow_instance_post_rejects_new_device_without_group_add_permission(self):
        group, label_field = self._create_device_group(can_add=False)

        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "devices_0_label": "Unauthorized device",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            InstanceDevice.objects.filter(
                instance=self.instance,
                is_active=True,
            ).exists()
        )
        self.assertFalse(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).exists()
        )

    def test_workflow_instance_post_rejects_existing_device_without_group_edit_permission(self):
        group, label_field = self._create_device_group(can_edit=False)
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
            text_value="Original device",
        )

        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "devices_0_label": "Unauthorized update",
                "devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            InstanceDevice.objects.filter(
                instance=self.instance,
                is_active=True,
            ).count(),
            1,
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=row,
                field=label_field,
            ).text_value,
            "Original device",
        )

    def test_workflow_instance_post_rejects_new_device_field_without_field_edit_permission(self):
        group, label_field = self._create_device_group(field_can_edit=False)

        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "devices_0_label": "Unauthorized field value",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            InstanceDevice.objects.filter(
                instance=self.instance,
                is_active=True,
            ).exists()
        )
        self.assertFalse(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).exists()
        )

    def test_workflow_instance_post_allows_existing_noneditable_device_field_when_unchanged(self):
        group, label_field = self._create_device_group(field_can_edit=False)
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
            text_value="Protected device",
        )

        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "devices_0_label": "Protected device",
                "devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=row,
                field=label_field,
            ).text_value,
            "Protected device",
        )

    def test_workflow_instance_post_rejects_existing_noneditable_device_field_when_changed(self):
        group, label_field = self._create_device_group(field_can_edit=False)
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
            text_value="Protected device",
        )

        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "devices_0_label": "Changed protected device",
                "devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=row,
                field=label_field,
            ).text_value,
            "Protected device",
        )


    def test_workflow_instance_post_resolves_unresolved_device_by_existing_imei(self):
        group, fields = self._create_device_system_fields()
        device_type = DeviceType.objects.create(
            name="Resolution Phone",
            code="OP_POST_RESOLUTION_TYPE",
            is_active=True,
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Resolution Phone X",
            code="OP_POST_RESOLUTION_MODEL",
            is_active=True,
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="333333333333333",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_imei="999999999999999",
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_imei": "333333333333333",
                "system_devices_0_system_type": str(device_type.pk),
                "system_devices_0_system_model": str(device_model.pk),
                "system_devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        instance_device.refresh_from_db()
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model_id)
        self.assertIsNone(instance_device.draft_device_type_id)
        row.refresh_from_db()
        self.assertEqual(row.instance_device_id, instance_device.pk)

    def test_workflow_instance_post_reuses_existing_device_on_create(self):
        group, fields = self._create_device_system_fields()
        device_type = DeviceType.objects.create(
            name="Create Reuse Phone",
            code="OP_POST_CREATE_REUSE_TYPE",
            is_active=True,
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Create Reuse Phone X",
            code="OP_POST_CREATE_REUSE_MODEL",
            is_active=True,
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="444444444444444",
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_imei": "444444444444444",
                "system_devices_0_system_type": str(device_type.pk),
                "system_devices_0_system_model": str(device_model.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            InstanceDevice.objects.filter(instance=self.instance, is_active=True).count(),
            1,
        )
        instance_device = InstanceDevice.objects.get(
            instance=self.instance,
            is_active=True,
        )
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).count(),
            1,
        )

    def test_workflow_instance_post_rejects_existing_imei_with_wrong_model(self):
        group, fields = self._create_device_system_fields()
        device_type = DeviceType.objects.create(
            name="Existing IMEI Phone",
            code="OP_POST_EXISTING_IMEI_TYPE",
            is_active=True,
        )
        other_type = DeviceType.objects.create(
            name="Other Phone",
            code="OP_POST_WRONG_MODEL_TYPE",
            is_active=True,
        )
        existing_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Existing Model",
            code="OP_POST_EXISTING_MODEL",
            is_active=True,
        )
        wrong_model = DeviceModel.objects.create(
            device_type=other_type,
            brand="Test",
            name="Wrong Model",
            code="OP_POST_WRONG_MODEL",
            is_active=True,
        )
        device = Device.objects.create(device_model=existing_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="555555555555555",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
            draft_imei="555555555555555",
            draft_device_model=existing_model,
            draft_device_type=device_type,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_imei": "555555555555555",
                "system_devices_0_system_type": str(other_type.pk),
                "system_devices_0_system_model": str(wrong_model.pk),
                "system_devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 400)
        instance_device.refresh_from_db()
        self.assertIsNone(instance_device.device_id)
        self.assertEqual(instance_device.draft_imei, "555555555555555")
        self.assertEqual(instance_device.draft_device_model_id, existing_model.pk)
        self.assertEqual(instance_device.draft_device_type_id, device_type.pk)
        self.assertTrue(RepeatableRow.objects.filter(pk=row.pk).exists())

    def test_workflow_instance_post_allows_resolved_device_model_change_with_permission(self):
        group, fields = self._create_device_system_fields()
        device_type = DeviceType.objects.create(
            name="Model Change Phone",
            code="OP_POST_MODEL_CHANGE_TYPE",
            is_active=True,
        )
        original_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Original Model",
            code="OP_POST_MODEL_CHANGE_ORIGINAL",
            is_active=True,
        )
        target_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Target Model",
            code="OP_POST_MODEL_CHANGE_TARGET",
            is_active=True,
        )
        device = Device.objects.create(device_model=original_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="666666666666666",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_imei": "666666666666666",
                "system_devices_0_system_type": str(device_type.pk),
                "system_devices_0_system_model": str(target_model.pk),
                "system_devices_0_instance_device_id": str(instance_device.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        device.refresh_from_db()
        self.assertEqual(device.device_model_id, target_model.pk)
        instance_device.refresh_from_db()
        self.assertEqual(instance_device.device_id, device.pk)
        self.assertTrue(RepeatableRow.objects.filter(pk=row.pk).exists())

    def test_workflow_instance_post_rejects_device_model_type_mismatch(self):
        group, fields = self._create_device_system_fields()
        first_type = DeviceType.objects.create(
            name="Mismatch Phone",
            code="OP_POST_MISMATCH_TYPE_A",
            is_active=True,
        )
        second_type = DeviceType.objects.create(
            name="Mismatch Tablet",
            code="OP_POST_MISMATCH_TYPE_B",
            is_active=True,
        )
        model = DeviceModel.objects.create(
            device_type=first_type,
            brand="Test",
            name="Mismatch Model",
            code="OP_POST_MISMATCH_MODEL",
            is_active=True,
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_type": str(second_type.pk),
                "system_devices_0_system_model": str(model.pk),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            InstanceDevice.objects.filter(
                instance=self.instance,
                is_active=True,
            ).exists()
        )
        self.assertFalse(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).exists()
        )

    def test_workflow_instance_post_rejects_duplicate_existing_device_in_same_instance(self):
        group, fields = self._create_device_system_fields()
        device_type = DeviceType.objects.create(
            name="Duplicate Phone",
            code="OP_POST_DUPLICATE_TYPE",
            is_active=True,
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Duplicate Phone X",
            code="OP_POST_DUPLICATE_MODEL",
            is_active=True,
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="777777777777777",
        )
        existing_instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
        )
        RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=existing_instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "system_devices_0_system_imei": "777777777777777",
                "system_devices_0_system_type": str(device_type.pk),
                "system_devices_0_system_model": str(device_model.pk),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            InstanceDevice.objects.filter(
                instance=self.instance,
                is_active=True,
            ).count(),
            1,
        )
        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=group,
            ).count(),
            1,
        )

    def test_workflow_instance_renders_nested_repeatable_children(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Customers",
            code="customers",
            order=5,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Contacts",
            code="contacts",
            order=1,
            parent_group=parent_group,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
        )
        parent_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Customer Name",
            code="nested_customer_name",
            label="Customer Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Contact Name",
            code="contact_name",
            label="Contact Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        RepeatableGroupAccess.objects.create(
            group=parent_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        for field in (parent_field, child_field):
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
            )

        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
            row_order=0,
        )
        second_parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
            row_order=1,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
            row_order=0,
        )
        second_child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=second_parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=parent_row,
            field=parent_field,
            text_value="Parent 1",
        )
        RepeatableRowValue.objects.create(
            row=second_parent_row,
            field=parent_field,
            text_value="Parent 2",
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=child_field,
            text_value="Child 1",
        )
        RepeatableRowValue.objects.create(
            row=second_child_row,
            field=child_field,
            text_value="Child 2",
        )

        response = self.client.get(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {"edit": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Child 1")
        self.assertContains(response, "Child 2")
        self.assertContains(
            response,
            'name="customers_0_contacts_0_contact_name"',
        )
        self.assertContains(
            response,
            'name="customers_1_contacts_0_contact_name"',
        )

        self.assertContains(
            response,
            'class="df-button df-button-secondary df-repeatable-add" data-group-code="contacts"',
        )
        self.assertEqual(
            response.content.decode().count(
                'data-group-code="contacts"'
            ),
            2,
        )


    def test_delete_device_rejects_without_group_delete_permission(self):
        group, fields = self._create_device_group(
            can_delete=False,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
        )
        RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse(
                "operator_panel:delete_device",
                args=[
                    self.instance.pk,
                    group.code,
                    instance_device.pk,
                ],
            ),
        )

        self.assertEqual(response.status_code, 403)
        instance_device.refresh_from_db()
        self.assertTrue(instance_device.is_active)

    def test_delete_device_uses_permission_context_group_delete_permission(self):
        group, fields = self._create_device_group(
            can_delete=True,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
        )
        RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            instance_device=instance_device,
            row_order=0,
        )

        response = self.client.post(
            reverse(
                "operator_panel:delete_device",
                args=[
                    self.instance.pk,
                    group.code,
                    instance_device.pk,
                ],
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )
        instance_device.refresh_from_db()
        self.assertFalse(instance_device.is_active)

