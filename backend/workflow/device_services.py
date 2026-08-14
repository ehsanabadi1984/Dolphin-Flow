from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    Device,
    DeviceIdentifier,
    DeviceModel,
)


class DeviceService:
    """
    Business logic for finding and creating devices
    using their persistent identifiers.
    """

    @staticmethod
    def get_device_by_identifier(
        *,
        identifier_type,
        value,
    ):
        """
        Find an existing device by its identifier.

        Returns:
            Device instance or None
        """

        if not value:
            return None

        value = str(value).strip()

        if not value:
            return None

        identifier = (
            DeviceIdentifier.objects
            .select_related(
                "device",
                "device__device_model",
                "device__device_model__device_type",
            )
            .filter(
                identifier_type=identifier_type,
                value=value,
            )
            .first()
        )

        if identifier is None:
            return None

        return identifier.device

    @staticmethod
    @transaction.atomic
    def get_or_create_by_imei(
        *,
        imei,
        device_model,
    ):
        """
        Find an existing device by IMEI or create
        a new device when the IMEI does not exist.

        Existing devices are never silently reassigned
        to another device model.
        """

        if not imei:
            raise ValidationError(
                "IMEI الزامی است."
            )

        imei = str(imei).strip()

        if not imei:
            raise ValidationError(
                "IMEI الزامی است."
            )

        existing_identifier = (
            DeviceIdentifier.objects
            .select_related(
                "device",
                "device__device_model",
            )
            .filter(
                identifier_type=(
                    DeviceIdentifier.IdentifierType.IMEI
                ),
                value=imei,
            )
            .first()
        )

        if existing_identifier:
            device = existing_identifier.device

            if (
                device.device_model_id
                != device_model.pk
            ):
                raise ValidationError(
                    "این IMEI قبلاً برای مدل دیگری "
                    "ثبت شده است."
                )

            return device, False

        device = Device.objects.create(
            device_model=device_model,
        )

        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=(
                DeviceIdentifier.IdentifierType.IMEI
            ),
            value=imei,
        )

        return device, True

