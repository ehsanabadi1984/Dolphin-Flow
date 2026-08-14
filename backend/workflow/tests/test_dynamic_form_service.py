from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.exceptions import ValidationError
from workflow.instance_device_services import InstanceDeviceService

from workflow.form_services import DynamicFormService
from workflow.models import (
    Device,
    DeviceModel,
    DeviceType,
    FieldAccess,
    FormDefinition,
    FormField,
    FormSection,
    FormData,
    InstanceDevice,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    FormRepeatableGroup,
    DeviceIdentifier,
)


User = get_user_model()


class DynamicFormServiceTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="dynamic_form_test_user",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="Dynamic Form Service Test",
            code="DYNAMIC_FORM_SERVICE_TEST",
            is_active=True,
        )

        cls.step_one = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step One",
            code="STEP_ONE",
            order=1,
            is_active=True,
        )

        cls.step_two = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step Two",
            code="STEP_TWO",
            order=2,
            is_active=True,
        )

        cls.membership = WorkflowMembership.objects.create(
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
            name="Device Information",
            code="DEVICE_INFO",
            order=1,
            is_active=True,
        )

        cls.phone_field = FormField.objects.create(
            section=cls.section,
            name="Phone",
            code="Phone",
            field_type=FormField.FieldType.TEXT,
            label="شماره تماس",
            order=1,
            is_required=True,
            is_active=True,
        )

        cls.address_field = FormField.objects.create(
            section=cls.section,
            name="Address",
            code="customer_address",
            field_type=FormField.FieldType.TEXTAREA,
            label="آدرس و کد پستی",
            order=2,
            is_required=True,
            is_active=True,
        )

        cls.device_group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Devices",
            code="devices",
            order=3,
            is_active=True,
        )

        cls.device_imei_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="IMEI",
            code="imei",
            field_type=FormField.FieldType.TEXT,
            label="IMEI",
            order=1,
            is_required=True,
            is_active=True,
        )

        cls.device_model_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="Device Model",
            code="device_model_id",
            field_type=FormField.FieldType.TEXT,
            label="مدل دستگاه",
            order=2,
            is_required=True,
            is_active=True,
        )

        cls.problem_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="Problem",
            code="reported_problem",
            field_type=FormField.FieldType.TEXTAREA,
            label="شرح مشکل",
            order=3,
            is_required=True,
            is_active=True,
        )

        FieldAccess.objects.create(
            field=cls.phone_field,
            step=cls.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        FieldAccess.objects.create(
            field=cls.address_field,
            step=cls.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        FieldAccess.objects.create(
            field=cls.device_imei_field,
            step=cls.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        FieldAccess.objects.create(
            field=cls.device_model_field,
            step=cls.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        FieldAccess.objects.create(
            field=cls.problem_field,
            step=cls.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
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
            current_step=self.step_one,
            status=WorkflowInstance.Status.ACTIVE,
        )

    def test_get_form_for_step_returns_repeatable_device_group(self):
        instance = self.create_instance()

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["form"].pk,
            self.form.pk,
        )

        device_groups = [
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
        ]

        self.assertEqual(
            len(device_groups),
            1,
        )

        group = device_groups[0]

        self.assertEqual(
            group["group"].code,
            "devices",
        )

        field_codes = [
            item["field"].code
            for item in group["fields"]
        ]

        self.assertIn(
            "imei",
            field_codes,
        )

        self.assertIn(
            "device_model_id",
            field_codes,
        )

        self.assertIn(
            "reported_problem",
            field_codes,
        )

        self.assertEqual(
            group["items"],
            [],
        )

    def test_save_form_saves_normal_fields(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست - کد پستی 1234567890",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        self.assertEqual(
            form_data.data["Phone"],
            "09120000000",
        )

        self.assertEqual(
            form_data.data["customer_address"],
            "آدرس تست - کد پستی 1234567890",
        )

    def test_save_form_creates_device_from_repeatable_group(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست - کد پستی 1234567890",
            "devices": [
                {
                    "imei": "777777777777777",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه روشن نمی‌شود",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        self.assertEqual(
            form_data.data["Phone"],
            "09120000000",
        )

        self.assertNotIn(
            "devices",
            form_data.data,
        )

        instance_devices = InstanceDevice.objects.filter(
            instance=instance,
        )

        self.assertEqual(
            instance_devices.count(),
            1,
        )

        instance_device = instance_devices.first()

        self.assertEqual(
            instance_device.device.device_model_id,
            self.device_model.pk,
        )

        self.assertEqual(
            instance_device.reported_problem,
            "دستگاه روشن نمی‌شود",
        )

        self.assertEqual(
            instance_device.status,
            "RECEIVED",
        )

    def test_save_form_reuses_existing_device_by_imei(self):
        instance_1 = self.create_instance()
        instance_2 = self.create_instance()

        submitted_data = {
            "Phone": "09120000001",
            "customer_address": "آدرس اول",
            "devices": [
                {
                    "imei": "888888888888888",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل اول",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance_1,
            user=self.user,
            submitted_data=submitted_data,
        )

        submitted_data_2 = {
            "Phone": "09120000002",
            "customer_address": "آدرس دوم",
            "devices": [
                {
                    "imei": "888888888888888",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل دوم",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance_2,
            user=self.user,
            submitted_data=submitted_data_2,
        )

        device_1 = InstanceDevice.objects.get(
            instance=instance_1,
        )

        device_2 = InstanceDevice.objects.get(
            instance=instance_2,
        )

        self.assertEqual(
            device_1.device_id,
            device_2.device_id,
        )



    def test_save_form_updates_existing_instance_device(self):
        instance = self.create_instance()

        first_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "999999999999999",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل اولیه",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        self.assertEqual(
            instance_device.reported_problem,
            "مشکل اولیه",
        )

        self.assertEqual(
            instance_device.status,
            "RECEIVED",
        )

        second_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "999999999999999",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل به‌روزشده",
                    "warranty_status": "WARRANTY",
                    "status": "IN_REPAIR",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_data,
        )

        instance_device.refresh_from_db()

        self.assertEqual(
            InstanceDevice.objects.filter(
                instance=instance,
            ).count(),
            1,
        )

        self.assertEqual(
            instance_device.reported_problem,
            "مشکل به‌روزشده",
        )

        self.assertEqual(
            instance_device.warranty_status,
            "WARRANTY",
        )

        self.assertEqual(
            instance_device.status,
            "IN_REPAIR",
        )
    def test_save_form_rejects_missing_required_normal_field(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "devices": [],
        }

        with self.assertRaises(Exception):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=submitted_data,
            )

    def test_clear_form_does_not_delete_persistent_devices(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "123123123123123",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "تست پاک کردن فرم",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        device_id = instance_device.device_id

        form_data = FormData.objects.get(
            instance=instance,
        )

        self.assertEqual(
            form_data.data["Phone"],
            "09120000000",
        )

        DynamicFormService.clear_form_for_step(
            instance=instance,
            user=self.user,
        )

        form_data.refresh_from_db()

        self.assertNotIn(
            "Phone",
            form_data.data,
        )

        self.assertNotIn(
            "customer_address",
            form_data.data,
        )

        instance_device.refresh_from_db()

        self.assertEqual(
            instance_device.device_id,
            device_id,
        )

        self.assertTrue(
            InstanceDevice.objects.filter(
                pk=instance_device.pk,
            ).exists()
        )

        self.assertTrue(
            DeviceModel.objects.filter(
                pk=self.device_model.pk,
            ).exists()
        )

    def test_save_form_rejects_invalid_device_model(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "555555555555555",
                    "device_model_id": 999999,
                    "reported_problem": "تست مدل نامعتبر",
                },
            ],
        }

        with self.assertRaises(Exception):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=submitted_data,
            )

        self.assertFalse(
            InstanceDevice.objects.filter(
                instance=instance,
            ).exists()
        )

    def test_save_form_rejects_imei_for_different_model(self):
        instance = self.create_instance()

        first_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "777777777777777",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه اول",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        self.assertEqual(
            instance_device.device_id,
            instance_device.device_id,
        )

        other_device_model = DeviceModel.objects.create(
            device_type=self.device_model.device_type,
            brand="Test Brand 2",
            name="Other Model",
            code="OTHER_MODEL",
            is_active=True,
        )

        second_instance = self.create_instance()

        second_data = {
            "Phone": "09121111111",
            "customer_address": "آدرس تست دوم",
            "devices": [
                {
                    "imei": "777777777777777",
                    "device_model_id": other_device_model.pk,
                    "reported_problem": "تلاش با مدل متفاوت",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=second_instance,
                user=self.user,
                submitted_data=second_data,
            )

        self.assertFalse(
            InstanceDevice.objects.filter(
                instance=second_instance,
            ).exists()
        )

    def test_save_form_creates_multiple_devices(self):
        instance = self.create_instance()

        second_device_model = DeviceModel.objects.create(
            device_type=self.device_model.device_type,
            brand="Test Brand",
            name="Test Model 2",
            code="TEST_MODEL_2",
            is_active=True,
        )

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "111111111111111",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل دستگاه اول",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
                {
                    "imei": "222222222222222",
                    "device_model_id": second_device_model.pk,
                    "reported_problem": "مشکل دستگاه دوم",
                    "warranty_status": "WARRANTY",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        instance_devices = list(
            InstanceDevice.objects
            .filter(instance=instance)
            .select_related("device", "device__device_model")
            .order_by("id")
        )

        self.assertEqual(
            len(instance_devices),
            2,
        )

        self.assertEqual(
            instance_devices[0].device.device_model_id,
            self.device_model.pk,
        )

        self.assertEqual(
            instance_devices[0].reported_problem,
            "مشکل دستگاه اول",
        )

        self.assertEqual(
            instance_devices[1].device.device_model_id,
            second_device_model.pk,
        )

        self.assertEqual(
            instance_devices[1].reported_problem,
            "مشکل دستگاه دوم",
        )

        self.assertEqual(
            instance_devices[1].warranty_status,
            "WARRANTY",
        )

    def test_deactivate_instance_device(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "333333333333333",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "تست غیرفعال سازی",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        device = instance_device.device

        self.assertTrue(
            instance_device.is_active,
        )

        InstanceDeviceService.deactivate_device(
            instance_device=instance_device,
        )

        instance_device.refresh_from_db()

        self.assertFalse(
            instance_device.is_active,
        )

        self.assertTrue(
            Device.objects.filter(
                pk=device.pk,
            ).exists()
        )

        devices = list(
            InstanceDeviceService.get_devices_for_instance(
                instance=instance,
            )
        )

        self.assertEqual(
            len(devices),
            0,
        )

    def test_reactivate_instance_device(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "444444444444444",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "تست فعال سازی مجدد",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        InstanceDeviceService.deactivate_device(
            instance_device=instance_device,
        )

        instance_device.refresh_from_db()

        self.assertFalse(
            instance_device.is_active,
        )

        InstanceDeviceService.reactivate_device(
            instance_device=instance_device,
        )

        instance_device.refresh_from_db()

        self.assertTrue(
            instance_device.is_active,
        )

        devices = list(
            InstanceDeviceService.get_devices_for_instance(
                instance=instance,
            )
        )

        self.assertEqual(
            len(devices),
            1,
        )

        self.assertEqual(
            devices[0].pk,
            instance_device.pk,
        )
    def test_get_form_for_step_returns_persistent_devices(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "555555555555555",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل تست",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        device_groups = [
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].code == "devices"
        ]

        self.assertEqual(
            len(device_groups),
            1,
        )

        items = device_groups[0]["items"]

        self.assertEqual(
            len(items),
            1,
        )

        item = items[0]

        self.assertEqual(
            item["reported_problem"],
            "مشکل تست",
        )

        self.assertEqual(
            item["warranty_status"],
            "UNKNOWN",
        )

        self.assertEqual(
            item["status"],
            "RECEIVED",
        )

        self.assertEqual(
            item["device_model_id"],
            self.device_model.pk,
        )

        self.assertEqual(
            item["identifiers"][0]["value"],
            "555555555555555",
        )

    def test_save_form_updates_existing_device_from_form(self):
        instance = self.create_instance()

        imei = "666666666666666"

        first_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": imei,
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل اولیه",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        instance_device_id = instance_device.pk

        second_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": imei,
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل به‌روزشده",
                    "warranty_status": "WARRANTY",
                    "status": "IN_REPAIR",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_submission,
        )

        instance_devices = list(
            InstanceDevice.objects.filter(
                instance=instance,
            )
        )

        self.assertEqual(
            len(instance_devices),
            1,
        )

        updated_instance_device = instance_devices[0]

        self.assertEqual(
            updated_instance_device.pk,
            instance_device_id,
        )

        self.assertEqual(
            updated_instance_device.reported_problem,
            "مشکل به‌روزشده",
        )

        self.assertEqual(
            updated_instance_device.warranty_status,
            "WARRANTY",
        )

        self.assertEqual(
            updated_instance_device.status,
            "IN_REPAIR",
        )

    def test_save_form_updates_one_device_without_affecting_other_devices(self):
        instance = self.create_instance()

        first_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "777777777777777",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل دستگاه اول",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
                {
                    "imei": "888888888888888",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل دستگاه دوم",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
        )

        instance_devices = list(
            InstanceDevice.objects
            .filter(instance=instance)
            .order_by("pk")
        )

        self.assertEqual(
            len(instance_devices),
            2,
        )

        first_id = instance_devices[0].pk
        second_id = instance_devices[1].pk

        second_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "777777777777777",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل دستگاه اول - UPDATED",
                    "warranty_status": "WARRANTY",
                    "status": "IN_REPAIR",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_submission,
        )

        first_device = InstanceDevice.objects.get(
            pk=first_id,
        )

        second_device = InstanceDevice.objects.get(
            pk=second_id,
        )

        self.assertEqual(
            InstanceDevice.objects
            .filter(instance=instance)
            .count(),
            2,
        )

        self.assertEqual(
            first_device.reported_problem,
            "مشکل دستگاه اول - UPDATED",
        )

        self.assertEqual(
            first_device.warranty_status,
            "WARRANTY",
        )

        self.assertEqual(
            first_device.status,
            "IN_REPAIR",
        )

        self.assertEqual(
            second_device.reported_problem,
            "مشکل دستگاه دوم",
        )

        self.assertEqual(
            second_device.warranty_status,
            "UNKNOWN",
        )

        self.assertEqual(
            second_device.status,
            "RECEIVED",
        )

    def test_get_form_for_step_hides_deactivated_device(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "999999999999999",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه غیرفعال",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        device_group = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].code == "devices"
        )

        self.assertEqual(
            len(device_group["items"]),
            1,
        )

        InstanceDeviceService.deactivate_device(
            instance_device=instance_device,
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        device_group = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].code == "devices"
        )

        self.assertEqual(
            len(device_group["items"]),
            0,
        )

        self.assertTrue(
            Device.objects.filter(
                pk=instance_device.device_id,
            ).exists()
        )

    def test_save_form_rejects_device_group_without_edit_access(self):
        instance = self.create_instance()

        # Remove all device-group access rules for the current step.
        FieldAccess.objects.filter(
            field__repeatable_group__code="devices",
            step=instance.current_step,
        ).delete()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "101010101010101",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "تلاش غیرمجاز",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=submitted_data,
            )

        self.assertFalse(
            InstanceDevice.objects.filter(
                instance=instance,
            ).exists()
        )

    def test_device_group_view_only_cannot_be_edited(self):
        instance = self.create_instance()

        # Create the device first while the user has edit access.
        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "121212121212121",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل اولیه",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        # Change all device-group rules to VIEW ONLY.
        FieldAccess.objects.filter(
            field__repeatable_group__code="devices",
            step=instance.current_step,
        ).update(
            can_view=True,
            can_edit=False,
        )

        # Device must still be visible.
        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        device_group = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].code == "devices"
        )

        self.assertEqual(
            len(device_group["items"]),
            1,
        )

        # But attempting to modify it must fail.
        update_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "121212121212121",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "تلاش برای ویرایش غیرمجاز",
                    "warranty_status": "WARRANTY",
                    "status": "IN_REPAIR",
                },
            ],
        }

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=update_submission,
            )

        instance_device.refresh_from_db()

        self.assertEqual(
            instance_device.reported_problem,
            "مشکل اولیه",
        )

        self.assertEqual(
            instance_device.warranty_status,
            "UNKNOWN",
        )

        self.assertEqual(
            instance_device.status,
            "RECEIVED",
        )

    def test_save_form_rejects_device_field_without_edit_access(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "555555555555555",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل اولیه",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        # ابتدا دستگاه را با مجوز کامل ایجاد می‌کنیم.
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        instance_device = (
            InstanceDevice.objects
            .select_related(
                "device",
                "device__device_model",
            )
            .get(
                instance=instance,
            )
        )

        original_imei = (
            instance_device
            .device
            .identifiers
            .get(
                identifier_type="IMEI",
            )
            .value
        )

        original_model = (
            instance_device
            .device
            .device_model_id
        )

        # ---------------------------------------------------------
        # حالا دسترسی ویرایش گروه را محدود می‌کنیم:
        #
        # Problem -> قابل ویرایش
        # IMEI    -> فقط مشاهده
        # Model   -> فقط مشاهده
        # Warranty -> فقط مشاهده
        # Status   -> فقط مشاهده
        # ---------------------------------------------------------

        devices_group = (
            self.form
            .sections
            .filter(
                repeatable_groups__code="devices",
            )
            .first()
            .repeatable_groups
            .get(
                code="devices",
            )
        )

        for field in devices_group.fields.all():
            FieldAccess.objects.filter(
                field=field,
                step=instance.current_step,
            ).update(
                can_view=True,
                can_edit=(
                    field.code == "reported_problem"
                ),
            )

        # ---------------------------------------------------------
        # تلاش برای تغییر IMEI
        # ---------------------------------------------------------

        submitted_data["devices"][0]["imei"] = (
            "666666666666666"
        )

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=submitted_data,
            )

        instance_device.refresh_from_db()

        self.assertEqual(
            instance_device.device.device_model_id,
            original_model,
        )

        self.assertEqual(
            instance_device.device.identifiers.get(
                identifier_type="IMEI",
            ).value,
            original_imei,
        )

    def test_save_form_removing_device_from_submission_does_not_delete_instance_device(
        self,
    ):
        instance = self.create_instance()

        first_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "111111111111111",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه اول",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
                {
                    "imei": "222222222222222",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه دوم",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
        )

        instance_devices = list(
            InstanceDevice.objects
            .filter(instance=instance)
            .order_by("pk")
        )

        self.assertEqual(
            len(instance_devices),
            2,
        )

        first_id = instance_devices[0].pk
        second_id = instance_devices[1].pk

        second_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "instance_device_id": first_id,
                    "imei": "111111111111111",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه اول",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_submission,
        )

        self.assertTrue(
            InstanceDevice.objects.filter(
                pk=second_id,
                instance=instance,
            ).exists()
        )

        self.assertEqual(
            InstanceDevice.objects
            .filter(instance=instance)
            .count(),
            2,
        )
    def test_save_form_updates_existing_device_imei_when_editable(
        self,
    ):
        instance = self.create_instance()

        first_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "333333333333333",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل اولیه",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
        )

        instance_device = (
            InstanceDevice.objects
            .select_related(
                "device",
                "device__device_model",
            )
            .get(instance=instance)
        )

        instance_device_id = instance_device.pk

        second_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "instance_device_id": instance_device_id,
                    "imei": "444444444444444",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل اولیه",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_submission,
        )

        self.assertTrue(
            DeviceIdentifier.objects.filter(
                device=instance_device.device,
                identifier_type="IMEI",
                value="444444444444444",
            ).exists()
        )

        self.assertFalse(
            DeviceIdentifier.objects.filter(
                device=instance_device.device,
                identifier_type="IMEI",
                value="333333333333333",
            ).exists()
        )

        self.assertEqual(
            InstanceDevice.objects.filter(
                instance=instance,
            ).count(),
            1,
        )

    def test_save_form_rejects_imei_belonging_to_another_device(
        self,
    ):
        instance = self.create_instance()

        first_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "imei": "111111111111111",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه اول",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
                {
                    "imei": "222222222222222",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه دوم",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
        )

        instance_devices = list(
            InstanceDevice.objects
            .filter(instance=instance)
            .order_by("pk")
        )

        self.assertEqual(
            len(instance_devices),
            2,
        )

        first_device = instance_devices[0]
        second_device = instance_devices[1]

        first_device_id = first_device.device_id
        second_device_id = second_device.device_id

        second_submission = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست",
            "devices": [
                {
                    "instance_device_id": first_device.pk,
                    "imei": "222222222222222",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه اول",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
                {
                    "instance_device_id": second_device.pk,
                    "imei": "222222222222222",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "دستگاه دوم",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                },
            ],
        }

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=second_submission,
            )

        first_device.refresh_from_db()
        second_device.refresh_from_db()

        self.assertEqual(
            first_device.device_id,
            first_device_id,
        )

        self.assertEqual(
            second_device.device_id,
            second_device_id,
        )

        self.assertEqual(
            DeviceIdentifier.objects.get(
                device_id=first_device_id,
                identifier_type="IMEI",
            ).value,
            "111111111111111",
        )

        self.assertEqual(
            DeviceIdentifier.objects.get(
                device_id=second_device_id,
                identifier_type="IMEI",
            ).value,
            "222222222222222",
        )

        self.assertEqual(
            InstanceDevice.objects.filter(
                instance=instance,
            ).count(),
            2,
        )