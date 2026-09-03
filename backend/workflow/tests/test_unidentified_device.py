from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_services import DynamicFormService
from workflow.models import (
    Device,
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
    FieldAccess,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)

User = get_user_model()


class UnidentifiedDeviceTests(TestCase):
    """
    Devices without a unique identifier (blank IMEI) are stored as
    draft InstanceDevice records and must never be treated as an
    identified Device or resolved through an empty identifier lookup.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="unidentified_device_test",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="Unidentified Device Test WF",
            code="UNIDENTIFIED_DEVICE_TEST",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step",
            code="STEP",
            order=1,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=cls.workflow,
            user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        cls.form = FormDefinition.objects.create(
            workflow=cls.workflow,
            name="Repair Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Device Info",
            code="DEVICE_INFO",
            order=1,
            is_active=True,
        )

        cls.device_group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Devices",
            code="devices",
            order=1,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            is_active=True,
        )

        cls.device_type = DeviceType.objects.create(
            name="Test Phone",
            code="TEST_PHONE",
            is_active=True,
        )

        cls.device_model = DeviceModel.objects.create(
            device_type=cls.device_type,
            brand="Test Brand",
            name="Test Model",
            code="TEST_MODEL",
            is_active=True,
        )

        cls.device_model_2 = DeviceModel.objects.create(
            device_type=cls.device_type,
            brand="Other Brand",
            name="Other Model",
            code="OTHER_MODEL",
            is_active=True,
        )

        # -------------------------------------------------
        # Device group fields mirroring the device modal:
        # IMEI / DEVICE_TYPE / DEVICE_MODEL.
        # -------------------------------------------------

        cls.imei_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="IMEI",
            code="imei",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.IMEI,
            label="IMEI",
            order=1,
            is_required=False,
            is_active=True,
        )

        cls.device_type_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="Device Type",
            code="device_type",
            field_type=FormField.FieldType.SELECT,
            system_key=FormField.SystemKey.DEVICE_TYPE,
            label="نوع دستگاه",
            order=2,
            is_required=True,
            is_active=True,
        )

        cls.device_model_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="Device Model",
            code="device_model_id",
            field_type=FormField.FieldType.SELECT,
            system_key=FormField.SystemKey.DEVICE_MODEL,
            label="مدل دستگاه",
            order=3,
            is_required=True,
            is_active=True,
        )

        for field in cls.device_group.fields.all():
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                user=cls.user,
                can_view=True,
                can_edit=True,
            )

        RepeatableGroupAccess.objects.create(
            group=cls.device_group,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
            can_add=True,
        )

    def create_instance(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            status=WorkflowInstance.Status.ACTIVE,
        )

        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step,
            performed_by=self.user,
        )

        return instance

    # -------------------------------------------------
    # 1. Create an unidentified device without IMEI
    # -------------------------------------------------

    def test_create_unidentified_device_without_imei(self):
        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "",
                "devices_0_device_type": str(self.device_type.pk),
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        instance_devices = list(
            InstanceDevice.objects.filter(instance=instance)
        )

        self.assertEqual(len(instance_devices), 1)

        instance_device = instance_devices[0]

        self.assertIsNone(instance_device.device)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertEqual(
            instance_device.draft_device_model_id,
            self.device_model.pk,
        )

        # No persistent Device / identifier is created.
        self.assertEqual(Device.objects.count(), 0)
        self.assertEqual(DeviceIdentifier.objects.count(), 0)

    # -------------------------------------------------
    # 2. Two unidentified devices remain independent
    # -------------------------------------------------

    def test_two_unidentified_devices_without_imei_remain_independent(self):
        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "",
                "devices_0_device_model_id": str(self.device_model.pk),
                "devices_1_imei": "",
                "devices_1_device_model_id": str(self.device_model.pk),
            },
        )

        instance_devices = list(
            InstanceDevice.objects.filter(instance=instance).order_by("pk")
        )

        self.assertEqual(len(instance_devices), 2)

        self.assertNotEqual(
            instance_devices[0].pk,
            instance_devices[1].pk,
        )

        for instance_device in instance_devices:
            self.assertIsNone(instance_device.device)
            self.assertEqual(instance_device.draft_imei, "")

        # The second device must never resolve to the first one.
        self.assertIsNone(instance_devices[1].device_id)
        self.assertNotEqual(
            instance_devices[1].pk,
            instance_devices[0].pk,
        )

    # -------------------------------------------------
    # 3. No DeviceIdentifier for unidentified devices
    # -------------------------------------------------

    def test_no_device_identifier_created_for_unidentified_device(self):
        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "",
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        self.assertEqual(Device.objects.count(), 0)
        self.assertEqual(DeviceIdentifier.objects.count(), 0)

    # -------------------------------------------------
    # 4. Identified-device IMEI lookup still works
    # -------------------------------------------------

    def test_identified_device_imei_lookup_still_works(self):
        device = Device.objects.create(device_model=self.device_model)

        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="555555555555555",
        )

        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "555555555555555",
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)

        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model)

    def test_identified_device_imei_reused_across_instances(self):
        device = Device.objects.create(device_model=self.device_model)

        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="666666666666666",
        )

        instance_1 = self.create_instance()
        instance_2 = self.create_instance()

        for instance in (instance_1, instance_2):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "devices_0_imei": "666666666666666",
                    "devices_0_device_model_id": str(self.device_model.pk),
                },
            )

        device_1 = InstanceDevice.objects.get(instance=instance_1)
        device_2 = InstanceDevice.objects.get(instance=instance_2)

        self.assertEqual(device_1.device_id, device.pk)
        self.assertEqual(device_2.device_id, device.pk)

    def test_imei_model_mismatch_still_rejected(self):
        """Uniqueness rules for real identifiers must not weaken."""
        DeviceIdentifier.objects.create(
            device=Device.objects.create(device_model=self.device_model),
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="777777777777777",
        )

        instance = self.create_instance()

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "devices_0_imei": "777777777777777",
                    "devices_0_device_model_id": str(self.device_model_2.pk),
                },
            )

    # -------------------------------------------------
    # 5. Existing draft with blank IMEI must never
    #    resolve to an existing Device
    # -------------------------------------------------

    def test_existing_draft_with_blank_imei_does_not_resolve_to_device(self):
        # An identified Device with an IMEI exists in the database.
        identified_device = Device.objects.create(
            device_model=self.device_model,
        )

        DeviceIdentifier.objects.create(
            device=identified_device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="111111111111111",
        )

        instance = self.create_instance()

        # Create an unidentified draft device (blank IMEI).
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "",
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        draft = InstanceDevice.objects.get(instance=instance)

        self.assertIsNone(draft.device)
        self.assertEqual(draft.draft_imei, "")

        # Re-submit the same draft row with a blank IMEI.
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_instance_device_id": str(draft.pk),
                "devices_0_imei": "",
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        draft.refresh_from_db()

        # The draft must not resolve to the identified Device.
        self.assertIsNone(draft.device)
        self.assertEqual(draft.draft_imei, "")
        self.assertEqual(
            draft.draft_device_model_id,
            self.device_model.pk,
        )

    # -------------------------------------------------
    # 6. DeviceModel is preserved for unidentified devices
    # -------------------------------------------------

    def test_device_model_preserved_for_unidentified_device(self):
        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "",
                "devices_0_device_model_id": str(self.device_model.pk),
                "devices_1_imei": "",
                "devices_1_device_model_id": str(self.device_model_2.pk),
            },
        )

        instance_devices = list(
            InstanceDevice.objects.filter(instance=instance).order_by("pk")
        )

        self.assertEqual(len(instance_devices), 2)

        self.assertEqual(
            instance_devices[0].draft_device_model_id,
            self.device_model.pk,
        )

        self.assertEqual(
            instance_devices[1].draft_device_model_id,
            self.device_model_2.pk,
        )

    # -------------------------------------------------
    # An unidentified device with only a DeviceType (no IMEI,
    # no DeviceModel) is accepted and the type is preserved.
    # -------------------------------------------------

    def test_unidentified_device_with_only_type_is_accepted(self):
        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "",
                "devices_0_device_model_id": "",
                "devices_0_device_type": str(self.device_type.pk),
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)

        self.assertIsNone(instance_device.device)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model)
        self.assertEqual(
            instance_device.draft_device_type_id,
            self.device_type.pk,
        )

        # No persistent Device / identifier is created.
        self.assertEqual(Device.objects.count(), 0)
        self.assertEqual(DeviceIdentifier.objects.count(), 0)

    # -------------------------------------------------
    # 7. DeviceType/DeviceModel rendering data remains
    #    available to the existing device modal
    # -------------------------------------------------

    def test_device_modal_rendering_data_available(self):
        instance = self.create_instance()

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        device_group = None

        for section in result["sections"]:
            for group in section["repeatable_groups"]:
                if group["group"].code == "devices":
                    device_group = group
                    break

        self.assertIsNotNone(device_group)

        device_type_info = None
        device_model_info = None

        for field_info in device_group["fields"]:
            if field_info["field"].system_key == FormField.SystemKey.DEVICE_TYPE:
                device_type_info = field_info
            elif field_info["field"].system_key == FormField.SystemKey.DEVICE_MODEL:
                device_model_info = field_info

        self.assertIsNotNone(device_type_info)
        self.assertIsNotNone(device_model_info)

        device_type_ids = [
            device_type.pk
            for device_type in device_type_info["device_types"]
        ]

        device_model_ids = [
            device_model.pk
            for device_model in device_model_info["device_models"]
        ]

        self.assertIn(self.device_type.pk, device_type_ids)
        self.assertIn(self.device_model.pk, device_model_ids)
        self.assertIn(self.device_model_2.pk, device_model_ids)