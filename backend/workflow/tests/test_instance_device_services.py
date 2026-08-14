from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.device_services import DeviceService
from workflow.instance_device_services import InstanceDeviceService
from workflow.models import (
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
    InstanceDevice,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
)


User = get_user_model()


class InstanceDeviceServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="test_instance_device",
            password="test_password",
        )

        cls.workflow = Workflow.objects.create(
            name="Test Workflow",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Test Step",
            code="TEST_STEP",
            order=1,
            is_active=True,
        )

        cls.workflow.memberships.create(
            user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR,
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

    def create_instance(self):
        return WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            status=WorkflowInstance.Status.ACTIVE,
        )

    def test_add_device_by_imei_creates_new_device(self):
        instance = self.create_instance()

        instance_device, device_created = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance,
                imei="111111111111111",
                device_model=self.device_model,
                reported_problem="Test problem",
                warranty_status="UNKNOWN",
                status="RECEIVED",
            )
        )

        self.assertTrue(device_created)
        self.assertIsNotNone(instance_device.pk)

        self.assertEqual(
            instance_device.instance_id,
            instance.pk,
        )

        self.assertEqual(
            instance_device.device.device_model_id,
            self.device_model.pk,
        )

        identifier = DeviceIdentifier.objects.get(
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="111111111111111",
        )

        self.assertEqual(
            identifier.device_id,
            instance_device.device_id,
        )

    def test_same_imei_reuses_existing_device(self):
        instance_1 = self.create_instance()
        instance_2 = self.create_instance()

        instance_device_1, device_created_1 = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance_1,
                imei="222222222222222",
                device_model=self.device_model,
            )
        )

        instance_device_2, device_created_2 = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance_2,
                imei="222222222222222",
                device_model=self.device_model,
            )
        )

        self.assertTrue(device_created_1)
        self.assertFalse(device_created_2)

        self.assertEqual(
            instance_device_1.device_id,
            instance_device_2.device_id,
        )

        self.assertNotEqual(
            instance_device_1.instance_id,
            instance_device_2.instance_id,
        )

        self.assertEqual(
            DeviceIdentifier.objects.filter(
                identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                value="222222222222222",
            ).count(),
            1,
        )

    def test_same_device_can_be_attached_to_different_instances(self):
        instance_1 = self.create_instance()
        instance_2 = self.create_instance()

        instance_device_1, _ = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance_1,
                imei="333333333333333",
                device_model=self.device_model,
            )
        )

        instance_device_2, _ = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance_2,
                imei="333333333333333",
                device_model=self.device_model,
            )
        )

        self.assertEqual(
            instance_device_1.device_id,
            instance_device_2.device_id,
        )

        self.assertEqual(
            InstanceDevice.objects.filter(
                device_id=instance_device_1.device_id,
            ).count(),
            2,
        )

    def test_same_device_cannot_be_registered_twice_in_same_instance(self):
        instance = self.create_instance()

        first, created_first = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance,
                imei="444444444444444",
                device_model=self.device_model,
                reported_problem="First problem",
                status="RECEIVED",
            )
        )

        second, created_second = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance,
                imei="444444444444444",
                device_model=self.device_model,
                reported_problem="Updated problem",
                status="IN_REPAIR",
            )
        )

        self.assertTrue(created_first)
        self.assertFalse(created_second)

        self.assertEqual(
            first.pk,
            second.pk,
        )

        self.assertEqual(
            InstanceDevice.objects.filter(
                instance=instance,
                device=first.device,
            ).count(),
            1,
        )

        first.refresh_from_db()

        self.assertEqual(
            first.reported_problem,
            "Updated problem",
        )

        self.assertEqual(
            first.status,
            "IN_REPAIR",
        )

    def test_deactivate_device(self):
        instance = self.create_instance()

        instance_device, _ = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance,
                imei="555555555555555",
                device_model=self.device_model,
            )
        )

        self.assertTrue(instance_device.is_active)

        result = InstanceDeviceService.deactivate_device(
            instance_device=instance_device,
        )

        self.assertFalse(result.is_active)

        result.refresh_from_db()

        self.assertFalse(result.is_active)

        active_devices = list(
            InstanceDeviceService.get_devices_for_instance(
                instance=instance,
            )
        )

        self.assertEqual(active_devices, [])


    def test_reactivate_device(self):
        instance = self.create_instance()

        instance_device, _ = (
            InstanceDeviceService.add_device_by_imei(
                instance=instance,
                imei="666666666666666",
                device_model=self.device_model,
            )
        )

        InstanceDeviceService.deactivate_device(
            instance_device=instance_device,
        )

        instance_device.refresh_from_db()

        self.assertFalse(instance_device.is_active)

        result = InstanceDeviceService.reactivate_device(
            instance_device=instance_device,
        )

        self.assertTrue(result.is_active)

        result.refresh_from_db()

        self.assertTrue(result.is_active)

        active_devices = list(
            InstanceDeviceService.get_devices_for_instance(
                instance=instance,
            )
        )

        self.assertEqual(
            len(active_devices),
            1,
        )

        self.assertEqual(
            active_devices[0].pk,
            instance_device.pk,
        )