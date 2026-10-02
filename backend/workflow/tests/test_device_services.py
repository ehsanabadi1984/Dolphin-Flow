from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.device_services import DeviceService
from workflow.models import (
    Device,
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
)


class DeviceServiceIdentityLifecycleTests(TestCase):
    def setUp(self):
        self.device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE",
            is_active=True,
        )
        self.device_model = DeviceModel.objects.create(
            device_type=self.device_type,
            brand="Test",
            name="Phone X",
            code="PHONE_X",
            is_active=True,
        )

    def test_create_device_allows_missing_identifier(self):
        device = DeviceService.create_device(
            device_model=self.device_model,
        )

        self.assertIsNotNone(device.pk)
        self.assertEqual(device.device_model_id, self.device_model.pk)
        self.assertFalse(
            DeviceIdentifier.objects.filter(device=device).exists()
        )

    def test_create_device_requires_model(self):
        with self.assertRaises(ValidationError):
            DeviceService.create_device(device_model=None)

        self.assertEqual(Device.objects.count(), 0)

    def test_attach_identifier_adds_identifier_to_existing_device(self):
        device = DeviceService.create_device(
            device_model=self.device_model,
        )

        identifier = DeviceService.attach_identifier(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="123456789012345",
        )

        self.assertEqual(identifier.device_id, device.pk)
        self.assertEqual(
            identifier.identifier_type,
            DeviceIdentifier.IdentifierType.IMEI,
        )
        self.assertEqual(identifier.value, "123456789012345")
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(DeviceIdentifier.objects.count(), 1)

    def test_attach_identifier_normalizes_value(self):
        device = DeviceService.create_device(
            device_model=self.device_model,
        )

        identifier = DeviceService.attach_identifier(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value=" 123456789012345 ",
        )

        self.assertEqual(identifier.value, "123456789012345")

    def test_attach_existing_identifier_to_same_device_is_idempotent(self):
        device = DeviceService.create_device(
            device_model=self.device_model,
        )
        existing = DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="123456789012345",
        )

        identifier = DeviceService.attach_identifier(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="123456789012345",
        )

        self.assertEqual(identifier.pk, existing.pk)
        self.assertEqual(DeviceIdentifier.objects.count(), 1)

    def test_attach_identifier_rejects_identifier_owned_by_another_device(self):
        first_device = DeviceService.create_device(
            device_model=self.device_model,
        )
        second_device = DeviceService.create_device(
            device_model=self.device_model,
        )
        DeviceIdentifier.objects.create(
            device=first_device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="123456789012345",
        )

        with self.assertRaises(ValidationError):
            DeviceService.attach_identifier(
                device=second_device,
                identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                value="123456789012345",
            )

        identifier = DeviceIdentifier.objects.get(
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="123456789012345",
        )
        self.assertEqual(identifier.device_id, first_device.pk)

    def test_attach_identifier_requires_nonblank_value(self):
        device = DeviceService.create_device(
            device_model=self.device_model,
        )

        for value in ("", "   ", None):
            with self.assertRaises(ValidationError):
                DeviceService.attach_identifier(
                    device=device,
                    identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                    value=value,
                )

        self.assertEqual(DeviceIdentifier.objects.count(), 0)

    def test_attach_identifier_requires_device(self):
        with self.assertRaises(ValidationError):
            DeviceService.attach_identifier(
                device=None,
                identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                value="123456789012345",
            )

        self.assertEqual(DeviceIdentifier.objects.count(), 0)

    def test_attach_identifier_requires_identifier_type(self):
        device = DeviceService.create_device(
            device_model=self.device_model,
        )

        with self.assertRaises(ValidationError):
            DeviceService.attach_identifier(
                device=device,
                identifier_type=None,
                value="123456789012345",
            )

        self.assertEqual(DeviceIdentifier.objects.count(), 0)
