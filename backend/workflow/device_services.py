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
    def create_device(*, device_model):
        """
        Create a persistent Device without requiring an identifier.
        """

        if not device_model:
            raise ValidationError(
                "مدل دستگاه الزامی است."
            )

        return Device.objects.create(
            device_model=device_model,
        )

    @staticmethod
    @transaction.atomic
    def attach_identifier(*, device, identifier_type, value):
        """
        Attach an identifier to an existing Device.

        An identifier already attached to this Device is returned as-is.
        An identifier owned by another Device is rejected.
        """

        if not device:
            raise ValidationError(
                "دستگاه مشخص نشده است."
            )

        if not identifier_type:
            raise ValidationError(
                "نوع شناسه دستگاه مشخص نشده است."
            )

        if not value:
            raise ValidationError(
                "مقدار شناسه دستگاه الزامی است."
            )

        value = str(value).strip()

        if not value:
            raise ValidationError(
                "مقدار شناسه دستگاه الزامی است."
            )

        existing_identifier = (
            DeviceIdentifier.objects
            .select_related("device")
            .filter(
                identifier_type=identifier_type,
                value=value,
            )
            .first()
        )

        if existing_identifier is not None:
            if existing_identifier.device_id != device.pk:
                raise ValidationError(
                    "این شناسه قبلاً برای دستگاه دیگری ثبت شده است."
                )
            return existing_identifier

        return DeviceIdentifier.objects.create(
            device=device,
            identifier_type=identifier_type,
            value=value,
        )

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

