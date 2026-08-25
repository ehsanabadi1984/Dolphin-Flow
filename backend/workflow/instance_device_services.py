from django.core.exceptions import ValidationError
from django.db import transaction

from .device_services import DeviceService
from .models import (
    InstanceDevice,
    WorkflowInstance,
)


class InstanceDeviceService:
    """
    Business logic for attaching persistent Devices
    to WorkflowInstances.
    """

    @staticmethod
    @transaction.atomic
    def add_device(
        *,
        instance,
        device,
        reported_problem="",
        warranty_status="",
        status="",
    ):
        """
        Attach an existing Device to a WorkflowInstance.
        """

        if not instance:
            raise ValidationError(
                "Workflow Instance مشخص نشده است."
            )

        if not device:
            raise ValidationError(
                "دستگاه مشخص نشده است."
            )

        if instance.status != WorkflowInstance.Status.ACTIVE:
            raise ValidationError(
                "امکان افزودن دستگاه به یک فرآیند "
                "غیرفعال وجود ندارد."
            )

        return InstanceDevice.objects.create(
            instance=instance,
            device=device,
            reported_problem=reported_problem,
            warranty_status=warranty_status,
            status=status,
        )

    @staticmethod
    @transaction.atomic
    def add_draft_device(
        *,
        instance,
        imei,
        device_model,
        reported_problem="",
        warranty_status="",
        status="",
    ):
        """
        Create a temporary device record inside workflow.
        Persistent Device is created only after submit.
        """

        if not instance:
            raise ValidationError(
                "Workflow Instance مشخص نشده است."
            )

        if instance.status != WorkflowInstance.Status.ACTIVE:
            raise ValidationError(
                "امکان افزودن دستگاه به یک فرآیند غیرفعال وجود ندارد."
            )

        if not imei:
            raise ValidationError(
                "IMEI الزامی است."
            )

        if not device_model:
            raise ValidationError(
                "مدل دستگاه الزامی است."
            )

        imei = str(imei).strip()

        if not imei:
            raise ValidationError(
                "IMEI الزامی است."
            )

        instance_device = InstanceDevice.objects.create(
            instance=instance,
            device=None,
            draft_imei=imei,
            draft_device_model=device_model,
            reported_problem=reported_problem,
            warranty_status=warranty_status,
            status=status,
        )

        return instance_device
    @staticmethod
    def get_devices_for_instance(
        *,
        instance,
    ):
        """
        Return all devices attached to a workflow instance.
        """

        return (
            InstanceDevice.objects
            .filter(
                instance=instance,
                is_active=True,
            )
            .select_related(
                "device",
                "device__device_model",
                "device__device_model__device_type",
            )
            .prefetch_related(
                "device__identifiers",
            )
        )

    @staticmethod
    @transaction.atomic
    def deactivate_device(
        *,
        instance_device,
    ):
        """
        Deactivate a device from a workflow instance.

        The persistent Device itself is not modified.
        """

        if not instance_device:
            raise ValidationError(
                "Instance Device مشخص نشده است."
            )

        if not instance_device.is_active:
            return instance_device

        instance_device.is_active = False

        instance_device.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

        return instance_device

    @staticmethod
    @transaction.atomic
    def reactivate_device(
        *,
        instance_device,
    ):
        """
        Reactivate a previously deactivated
        device in a workflow instance.
        """

        if not instance_device:
            raise ValidationError(
                "Instance Device مشخص نشده است."
            )

        if instance_device.is_active:
            return instance_device

        instance_device.is_active = True

        instance_device.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

        return instance_device