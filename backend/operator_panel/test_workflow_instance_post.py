from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
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
    WorkflowTransition,
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

    @patch(
        "operator_panel.views.WorkflowExecutionService.execute_transition"
    )
    def test_transition_validation_errors_render_as_structured_edit_form(
        self,
        execute_transition,
    ):
        self.name_field.is_required = True
        self.name_field.save(update_fields=["is_required"])

        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step,
            to_step=None,
            name="Finish",
        )

        execute_transition.side_effect = __import__(
            "django.core.exceptions",
            fromlist=["ValidationError"],
        ).ValidationError(
            [
                {
                    "type": "field",
                    "code": self.name_field.code,
                    "label": self.name_field.label,
                    "message": f"فیلد «{self.name_field.label}» الزامی است.",
                }
            ]
        )

        response = self.client.post(
            reverse(
                "operator_panel:execute_transition",
                args=[self.instance.pk, transition.pk],
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context["edit_mode"])
        self.assertEqual(
            response.context["validation_errors"],
            [
                {
                    "type": "field",
                    "code": self.name_field.code,
                    "label": self.name_field.label,
                    "message": f"فیلد «{self.name_field.label}» الزامی است.",
                }
            ],
        )
        self.assertEqual(response.context["error"], "")
        self.assertContains(response, self.name_field.label)
        self.assertContains(
            response,
            f"فیلد «{self.name_field.label}» الزامی است.",
        )

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

    
    def test_workflow_file_save_failure_rolls_back_draft_transaction(self):
        file_field = FormField.objects.create(
            section=self.section,
            name="Attachment",
            code="attachment",
            label="Attachment",
            field_type=FormField.FieldType.FILE,
            order=3,
        )
        FieldAccess.objects.create(
            field=file_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        self.client.raise_request_exception = False

        with patch(
            "workflow.form_file_services.save_uploaded_form_files",
            side_effect=RuntimeError("forced file persistence failure"),
        ):
            response = self.client.post(
                reverse(
                    "operator_panel:workflow_instance",
                    args=[self.instance.pk],
                ),
                {
                    "customer_name": "Draft that must roll back",
                    "attachment": SimpleUploadedFile(
                        "rollback.txt",
                        b"rollback-content",
                        content_type="text/plain",
                    ),
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(
            FormData.objects.filter(instance=self.instance).exists()
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
            ) + "?edit=1",
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
            ) + "?edit=1",
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
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]) + "?edit=1",
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
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]) + "?edit=1",
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
        DeviceIdentifier.objects.create(            device=device,
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

    def test_normal_nested_table_add_child_after_root_was_persisted_preserves_root_address(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parts Lifecycle",
            code="parts_lifecycle",
            order=5,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Child Parts Lifecycle",
            code="child_parts_lifecycle",
            order=6,
            parent_group=parent_group,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        address_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Address",
            code="address_lifecycle",
            label="Address",
            field_type=FormField.FieldType.TEXT,
            order=0,
            is_active=True,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Name",
            code="child_name_lifecycle",
            label="Child Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
            is_active=True,
        )
        for group in (parent_group, child_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )
        for field in (address_field, child_field):
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
            )

        # Phase 1: create only the root row and persist it.
        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "parts_lifecycle_0__id": "root-create-0",
                "parts_lifecycle_0_address_lifecycle": "Tehran",
            },
        )
        self.assertEqual(response.status_code, 302)

        root_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=parent_group,
        )
        root_pk = root_row.pk
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=root_row,
                field=address_field,
            ).text_value,
            "Tehran",
        )

        # The next edit GET must expose the persisted integer DB PK, not the
        # client-generated UUID that was used when the root was first created.
        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {"edit": "1"},
        )
        self.assertEqual(response.status_code, 200)
        edit_html = response.content.decode()
        self.assertRegex(
            edit_html,
            rf'name="parts_lifecycle_0__id"\s+value="{root_pk}"',
        )
        self.assertRegex(
            edit_html,
            r'name="parts_lifecycle_0_address_lifecycle"\s+value="Tehran"',
        )

        # Phase 2: this is the real browser lifecycle after Add Child:
        # the persisted root keeps its integer PK while the child is new.
        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ) + "?edit=1",
            {
                "parts_lifecycle_0__id": str(root_pk),
                "parts_lifecycle_0_address_lifecycle": "Tehran",
                "parts_lifecycle_0_child_parts_lifecycle_0__id": "child-create-0",
                "parts_lifecycle_0_child_parts_lifecycle_0_child_name_lifecycle": "Child 1",
            },
        )
        self.assertEqual(response.status_code, 302)

        root_row.refresh_from_db()
        self.assertEqual(root_row.pk, root_pk)
        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=parent_group,
            ).count(),
            1,
        )
        child_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=child_group,
        )
        self.assertEqual(child_row.parent_row_id, root_pk)
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=root_row,
                field=address_field,
            ).text_value,
            "Tehran",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=child_row,
                field=child_field,
            ).text_value,
            "Child 1",
        )

        # Verify the saved canonical rows are reconstructed correctly after
        # the redirect, both in read-only mode and in the next edit GET.
        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tehran")
        self.assertContains(response, "Child 1")

        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {"edit": "1"},
        )
        self.assertEqual(response.status_code, 200)
        edit_html = response.content.decode()
        self.assertRegex(
            edit_html,
            r'name="parts_lifecycle_0_address_lifecycle"\s+value="Tehran"',
        )
        self.assertRegex(
            edit_html,
            rf'name="parts_lifecycle_0__id"\s+value="{root_pk}"',
        )
        self.assertRegex(
            edit_html,
            r'name="parts_lifecycle_0_child_parts_lifecycle_0__id"\s+value="\d+"',
        )

    def test_normal_nested_table_two_roots_preserve_both_roots_when_child_is_added_to_first(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parts Two Roots",
            code="parts_two_roots",
            order=5,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Child Parts Two Roots",
            code="child_parts_two_roots",
            order=6,
            parent_group=parent_group,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        name_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Owner Name",
            code="owner_name_two_roots",
            label="Owner Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
            is_active=True,
        )
        address_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Owner Address",
            code="owner_address_two_roots",
            label="Owner Address",
            field_type=FormField.FieldType.TEXT,
            order=1,
            is_active=True,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Owner Phone",
            code="owner_phone_two_roots",
            label="Owner Phone",
            field_type=FormField.FieldType.TEXT,
            order=0,
            is_active=True,
        )
        for group in (parent_group, child_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )
        for field in (name_field, address_field, child_field):
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
            )

        # Phase 1: create two independent roots.
        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {
                "parts_two_roots_0__id": "root-create-0",
                "parts_two_roots_0_owner_name_two_roots": "Ehsan",
                "parts_two_roots_0_owner_address_two_roots": "Isfahan",
                "parts_two_roots_1__id": "root-create-1",
                "parts_two_roots_1_owner_name_two_roots": "Sadeghi",
                "parts_two_roots_1_owner_address_two_roots": "Tehran",
            },
        )
        self.assertEqual(response.status_code, 302)

        roots = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=parent_group,
            ).order_by("row_order", "pk")
        )
        self.assertEqual(len(roots), 2)
        root0, root1 = roots

        self.assertEqual(
            RepeatableRowValue.objects.get(row=root0, field=name_field).text_value,
            "Ehsan",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(row=root0, field=address_field).text_value,
            "Isfahan",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(row=root1, field=name_field).text_value,
            "Sadeghi",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(row=root1, field=address_field).text_value,
            "Tehran",
        )

        # Phase 2: the browser reopens Edit, then Add Child is performed under
        # root 0 while root 1 remains an independent root.
        response = self.client.get(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {"edit": "1"},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk])
            + "?edit=1",
            {
                "parts_two_roots_0__id": str(root0.pk),
                "parts_two_roots_0_owner_name_two_roots": "Ehsan",
                "parts_two_roots_0_owner_address_two_roots": "Isfahan",
                "parts_two_roots_0_child_parts_two_roots_0__id": "child-create-0",
                "parts_two_roots_0_child_parts_two_roots_0_owner_phone_two_roots": "09120000000",
                "parts_two_roots_1__id": str(root1.pk),
                "parts_two_roots_1_owner_name_two_roots": "Sadeghi",
                "parts_two_roots_1_owner_address_two_roots": "Tehran",
            },
        )
        self.assertEqual(response.status_code, 302)

        # The critical invariant: adding a child to root 0 must not make root
        # 1 disappear from the canonical RepeatableRow tree.
        roots = list(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=parent_group,
            ).order_by("row_order", "pk")
        )
        self.assertEqual(len(roots), 2)
        self.assertEqual({root.pk for root in roots}, {root0.pk, root1.pk})

        root0.refresh_from_db()
        root1.refresh_from_db()
        child_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=child_group,
        )
        self.assertEqual(child_row.parent_row_id, root0.pk)

        self.assertEqual(
            RepeatableRowValue.objects.get(row=root0, field=address_field).text_value,
            "Isfahan",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(row=root1, field=address_field).text_value,
            "Tehran",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(row=child_row, field=child_field).text_value,
            "09120000000",
        )

        # The same invariant must survive reconstruction into the Edit form.
        response = self.client.get(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {"edit": "1"},
        )
        self.assertEqual(response.status_code, 200)
        edit_html = response.content.decode()
        self.assertRegex(
            edit_html,
            rf'name="parts_two_roots_0_owner_address_two_roots"\s+value="Isfahan"',
        )
        self.assertRegex(
            edit_html,
            rf'name="parts_two_roots_1_owner_address_two_roots"\s+value="Tehran"',
        )
        self.assertRegex(
            edit_html,
            rf'name="parts_two_roots_0_child_parts_two_roots_0_owner_phone_two_roots"\s+value="09120000000"',
        )

    def test_normal_nested_table_preserves_root_address_and_row_identity_on_edit_save(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parts",
            code="parts",
            order=5,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Child Parts",
            code="child_parts",
            order=6,
            parent_group=parent_group,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        address_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Address",
            code="address",
            label="Address",
            field_type=FormField.FieldType.TEXT,
            order=0,
            is_active=True,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Name",
            code="child_name",
            label="Child Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
            is_active=True,
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
        for field in (address_field, child_field):
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
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=parent_row,
            field=address_field,
            text_value="Tehran",
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=child_field,
            text_value="Child 1",
        )

        response = self.client.get(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk]),
            {"edit": "1"},
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="parts_0_address"', html)
        self.assertIn('value="Tehran"', html)

        self.assertRegex(
            html,
            rf'name="parts_0__id"\s+value="{parent_row.pk}"',
        )
        self.assertRegex(
            html,
            rf'name="parts_0_child_parts_0__id"\s+value="{child_row.pk}"',
        )

        parent_row_id = parent_row.pk
        child_row_id = child_row.pk

        response = self.client.post(
            reverse("operator_panel:workflow_instance", args=[self.instance.pk])
            + "?edit=1",
            {
                "parts_0_address": "Tehran",
                "parts_0__id": str(parent_row.pk),
                "parts_0_child_parts_0_child_name": "Child 1",
                "parts_0_child_parts_0__id": str(child_row.pk),
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            RepeatableRow.objects.filter(
                pk=parent_row_id,
                instance=self.instance,
                group=parent_group,
            ).exists()
        )
        self.assertTrue(
            RepeatableRow.objects.filter(
                pk=child_row_id,
                instance=self.instance,
                group=child_group,
            ).exists()
        )
        parent_row = RepeatableRow.objects.get(pk=parent_row_id)
        child_row = RepeatableRow.objects.get(pk=child_row_id)
        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=parent_group,
            ).count(),
            1,
        )
        self.assertEqual(
            RepeatableRow.objects.filter(
                instance=self.instance,
                group=child_group,
            ).count(),
            1,
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=parent_row,
                field=address_field,
            ).text_value,
            "Tehran",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=child_row,
                field=child_field,
            ).text_value,
            "Child 1",
        )

        # The real operator lifecycle is: save -> read-only GET -> Edit GET.
        # The POST/DB assertions above alone do not prove that the canonical
        # row data is reconstructed into the flat TABLE after the redirect.
        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
        )
        self.assertEqual(response.status_code, 200)
        read_html = response.content.decode()
        self.assertIn("Tehran", read_html)
        self.assertIn("Child 1", read_html)

        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {"edit": "1"},
        )
        self.assertEqual(response.status_code, 200)
        edit_html = response.content.decode()
        self.assertRegex(
            edit_html,
            r'name="parts_0_address"\s+value="Tehran"',
        )
        self.assertIn('class="df-table-input"', edit_html)

    def test_normal_nested_table_create_root_with_child_preserves_root_address_on_save(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parts Create",
            code="parts_create",
            order=5,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Child Parts Create",
            code="child_parts_create",
            order=6,
            parent_group=parent_group,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        address_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Address",
            code="address",
            label="Address",
            field_type=FormField.FieldType.TEXT,
            order=0,
            is_active=True,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Name",
            code="child_name",
            label="Child Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
            is_active=True,
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
        for field in (address_field, child_field):
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
            )

        from django.http import QueryDict

        payload = QueryDict("", mutable=True)
        payload.update({
            "parts_create_0__id": "root-create-0",
            "parts_create_0_child_parts_create_0__id": "child-create-0",
            "parts_create_0_child_parts_create_0_child_name": "Child 1",
        })
        payload["parts_create_0_address"] = "Tehran"

        response = self.client.post(            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            payload,
        )

        self.assertEqual(response.status_code, 302)

        parent_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=parent_group,
        )
        child_row = RepeatableRow.objects.get(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
        )

        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=parent_row,
                field=address_field,
            ).text_value,
            "Tehran",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=child_row,
                field=child_field,
            ).text_value,
            "Child 1",
        )

        response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tehran")
        self.assertContains(response, "Child 1")

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

        self.assertEqual(
            response.content.decode().count(
                'class="df-button df-button-secondary df-repeatable-add"'
            ),
            3,
        )
        self.assertEqual(
            response.content.decode().count(
                'data-group-code="contacts"'
            ),
            4,
        )
        self.assertEqual(
            response.content.decode().count(
                'data-group-code="contacts"'
            ),
            4,
        )


    def test_delete_device_rejects_without_group_delete_permission(self):
        group, fields = self._create_device_group(
            can_delete=False,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
        )
        row = RepeatableRow.objects.create(
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
                    row.pk,
                ],
            ) + "?edit=1",
        )

        self.assertEqual(response.status_code, 403)
        instance_device.refresh_from_db()
        self.assertTrue(instance_device.is_active)
        self.assertTrue(RepeatableRow.objects.filter(pk=row.pk).exists())

    def test_delete_device_uses_permission_context_group_delete_permission(self):
        group, fields = self._create_device_group(
            can_delete=True,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=None,
        )
        row = RepeatableRow.objects.create(
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
                    row.pk,
                ],
            ) + "?edit=1",
        )

        self.assertEqual(response.status_code, 302)
        instance_device.refresh_from_db()
        self.assertFalse(instance_device.is_active)
        self.assertFalse(RepeatableRow.objects.filter(pk=row.pk).exists())

        get_response = self.client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {"edit": "1"},
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertNotContains(
            get_response,
            f'data-row-id="{row.pk}"',
        )