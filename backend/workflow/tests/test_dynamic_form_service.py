from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.exceptions import ValidationError
from workflow.instance_device_services import InstanceDeviceService
from workflow.device_services import DeviceService

from workflow.form_services import DynamicFormService
from workflow.form_draft_save_services import FormDraftSaveService
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
    WorkflowStepExecution,
    RepeatableGroupAccess,
    RepeatableRow,
    RepeatableRowValue,
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
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            is_active=True,
        )

        RepeatableGroupAccess.objects.create(
            group=cls.device_group,
            step=cls.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

        cls.device_imei_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="IMEI",
            code="imei",
            system_key=FormField.SystemKey.IMEI,
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
            system_key=FormField.SystemKey.DEVICE_MODEL,
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
            system_key=FormField.SystemKey.REPORTED_PROBLEM,
            field_type=FormField.FieldType.TEXTAREA,
            label="شرح مشکل",
            order=3,
            is_required=True,
            is_active=True,
        )

        cls.warranty_status_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="Warranty Status",
            code="warranty_status",
            system_key=FormField.SystemKey.WARRANTY_STATUS,
            field_type=FormField.FieldType.TEXT,
            label="وضعیت گارانتی",
            order=4,
            is_required=False,
            is_active=True,
        )

        cls.device_status_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.device_group,
            name="Status",
            code="status",
            system_key=FormField.SystemKey.STATUS,
            field_type=FormField.FieldType.TEXT,
            label="وضعیت دستگاه",
            order=5,
            is_required=False,
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

        FieldAccess.objects.create(
            field=cls.warranty_status_field,
            step=cls.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        FieldAccess.objects.create(
            field=cls.device_status_field,
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

    def save_form_for_step(self, *, instance, user, submitted_data, edit_mode):
        payload = self.normalize_test_submission(
            instance=instance,
            submitted_data=submitted_data,
        )
        result = FormDraftSaveService.save(
            instance=instance,
            step=self.step_one,
            user=user,
            submitted_data=payload,
            edit_mode=edit_mode,
        )
        return result.form_data

    @staticmethod
    def normalize_test_submission(*, instance, submitted_data):
        payload = dict(submitted_data)
        groups = payload.get("devices")
        if groups is not None:
            payload["devices"] = [
                {
                    **row,
                    **(
                        {
                            "row_id": (
                                RepeatableRow.objects
                                .filter(
                                    instance=instance,
                                    group=DynamicFormServiceTests.device_group,
                                    instance_device_id=row["instance_device_id"],
                                )
                                .values_list("pk", flat=True)
                                .first()
                            )
                        }
                        if row.get("instance_device_id")
                        else {}
                    ),
                }
                for row in groups
            ]
            for row in payload["devices"]:
                row.pop("instance_device_id", None)
        return payload

    def create_instance(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_one,
            status=WorkflowInstance.Status.ACTIVE,
        )

        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step_one,
            performed_by=self.user,
        )

        return instance

    def create_persistent_device(self, imei, device_model=None):
        device = Device.objects.create(
            device_model=device_model or self.device_model,
        )

        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value=imei,
        )

        return device

    def test_get_form_for_step_uses_repeatable_row_id_for_device_rows(self):
        instance = self.create_instance()

        instance_device = InstanceDevice.objects.create(
            instance=instance,
            draft_imei="111111111111111",
            draft_device_model=self.device_model,
            draft_device_type=self.device_model.device_type,
        )
        row = RepeatableRow.objects.create(
            instance=instance,
            group=self.device_group,
            row_order=0,
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
            if group["group"].pk == self.device_group.pk
        )
        item = device_group["items"][0]

        self.assertEqual(item["row_id"], str(row.pk))
        self.assertNotEqual(item["row_id"], str(instance_device.pk))

    def test_get_form_for_step_builds_nested_repeatable_context_per_parent_row(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Customers",
            code="customers",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            order=4,
            is_active=True,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name="Contacts",
            code="contacts",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            order=5,
            is_active=True,
        )

        parent_name = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Customer Name",
            code="customer_name",
            field_type=FormField.FieldType.TEXT,
            label="Customer",
            order=1,
            is_active=True,
        )
        child_name = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Contact Name",
            code="contact_name",
            field_type=FormField.FieldType.TEXT,
            label="Contact",
            order=1,
            is_active=True,
        )

        for group in (parent_group, child_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=self.step_one,
                role=WorkflowMembership.Role.EXECUTOR,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )

        for field in (parent_name, child_name):
            FieldAccess.objects.create(
                field=field,
                step=self.step_one,
                role=WorkflowMembership.Role.EXECUTOR,
                can_view=True,
                can_edit=True,
            )

        instance = self.create_instance()

        parent_rows = [
            RepeatableRow.objects.create(
                instance=instance,
                group=parent_group,
                row_order=index,
            )
            for index in range(2)
        ]

        RepeatableRowValue.objects.create(
            row=parent_rows[0],
            field=parent_name,
            text_value="Parent 1",
        )
        RepeatableRowValue.objects.create(
            row=parent_rows[1],
            field=parent_name,
            text_value="Parent 2",
        )

        child_values = (
            ("Child 1", parent_rows[0]),
            ("Child 2", parent_rows[1]),
        )
        for row_order, (value, parent_row) in enumerate(child_values):
            child_row = RepeatableRow.objects.create(
                instance=instance,
                group=child_group,
                parent_row=parent_row,
                row_order=0,
            )
            RepeatableRowValue.objects.create(
                row=child_row,
                field=child_name,
                text_value=value,
            )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        top_level_groups = [
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
        ]
        customers = next(
            group for group in top_level_groups
            if group["group"].code == "customers"
        )

        self.assertEqual(
            [group["group"].code for group in top_level_groups],
            ["devices", "customers"],
        )
        self.assertEqual(len(customers["items"]), 2)

        first_item, second_item = customers["items"]

        self.assertEqual(first_item["fields"][0]["value"], "Parent 1")
        self.assertEqual(second_item["fields"][0]["value"], "Parent 2")

        self.assertEqual(
            [group["group"].code for group in first_item["child_groups"]],
            ["contacts"],
        )
        self.assertEqual(
            [group["group"].code for group in second_item["child_groups"]],
            ["contacts"],
        )
        self.assertEqual(
            first_item["child_groups"][0]["items"][0]["fields"][0]["value"],
            "Child 1",
        )
        self.assertEqual(
            second_item["child_groups"][0]["items"][0]["fields"][0]["value"],
            "Child 2",
        )
        self.assertEqual(
            customers["flat_table"]["columns"][0]["field_context"]["field"].code,
            "customer_name",
        )
        self.assertEqual(
            customers["flat_table"]["columns"][1]["field_context"]["field"].code,
            "contact_name",
        )
        self.assertEqual(
            [
                row["row_group_code"]
                for row in customers["flat_table"]["rows"]
            ],
            ["contacts", "contacts"],
        )
        self.assertEqual(
            customers["flat_table"]["rows"][0]["column_cells"][0]["display_value"],
            "Parent 1",
        )
        self.assertEqual(
            customers["flat_table"]["rows"][0]["column_cells"][1]["display_value"],
            "Child 1",
        )
        self.assertFalse(
            customers["flat_table"]["rows"][1]["column_cells"][0]["show"],
        )
        self.assertEqual(
            customers["flat_table"]["rows"][1]["column_cells"][1]["display_value"],
            "Child 2",
        )

    def test_get_form_for_step_applies_nested_group_and_field_permissions(self):
        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Customers",
            code="customers_permissions",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            order=4,
            is_active=True,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name="Contacts",
            code="contacts_permissions",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            order=5,
            is_active=True,
        )

        parent_name = FormField.objects.create(
            section=self.section,
            repeatable_group=parent_group,
            name="Customer Name",
            code="customer_name_permissions",
            field_type=FormField.FieldType.TEXT,
            label="Customer",
            order=1,
            is_active=True,
        )
        child_name = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Contact Name",
            code="contact_name_permissions",
            field_type=FormField.FieldType.TEXT,
            label="Contact",
            order=1,
            is_active=True,
        )

        RepeatableGroupAccess.objects.create(
            group=parent_group,
            step=self.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        RepeatableGroupAccess.objects.create(
            group=child_group,
            step=self.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=False,
            can_edit=False,
            can_add=False,
            can_delete=False,
        )

        FieldAccess.objects.create(
            field=parent_name,
            step=self.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=child_name,
            step=self.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        instance = self.create_instance()

        parent_row = RepeatableRow.objects.create(
            instance=instance,
            group=parent_group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=parent_row,
            field=parent_name,
            text_value="Parent",
        )

        child_row = RepeatableRow.objects.create(
            instance=instance,
            group=child_group,
            parent_row=parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=child_name,
            text_value="Child",
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        customers = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].code == parent_group.code
        )

        self.assertEqual(len(customers["items"]), 1)
        self.assertEqual(customers["can_view"], True)
        self.assertEqual(customers["can_edit"], True)
        self.assertEqual(customers["can_add"], True)
        self.assertEqual(customers["can_delete"], True)

        parent_item = customers["items"][0]

        self.assertEqual(
            parent_item["fields"][0]["field"].code,
            parent_name.code,
        )
        self.assertTrue(parent_item["fields"][0]["can_edit"])

        self.assertEqual(parent_item["child_groups"], [])

        # Child group is hidden by group-level permission, even though
        # its field-level permission allows viewing/editing.
        self.assertNotIn(
            child_group.code,
            [
                group["group"].code
                for group in parent_item["child_groups"]
            ],
        )

        # The parent group remains visible and editable.
        self.assertTrue(customers["can_view"])
        self.assertTrue(customers["can_edit"])

        # Now make the child group visible but read-only. Its field
        # remains visible but must not be editable.
        child_access = RepeatableGroupAccess.objects.get(
            group=child_group,
            step=self.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        child_access.can_view = True
        child_access.can_edit = False
        child_access.can_add = False
        child_access.can_delete = False
        child_access.save(
            update_fields=[
                "can_view",
                "can_edit",
                "can_add",
                "can_delete",
            ]
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        customers = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].code == parent_group.code
        )
        parent_item = customers["items"][0]
        child_context = next(
            group
            for group in parent_item["child_groups"]
            if group["group"].code == child_group.code
        )

        self.assertTrue(child_context["can_view"])
        self.assertFalse(child_context["can_edit"])
        self.assertFalse(child_context["can_add"])
        self.assertFalse(child_context["can_delete"])
        self.assertEqual(len(child_context["items"]), 1)

        child_field = child_context["items"][0]["fields"][0]

        self.assertEqual(
            child_field["field"].code,
            child_name.code,
        )
        self.assertFalse(child_field["can_edit"])

        # Parent edit permission does not override a child group's
        # explicit read-only permission.
        self.assertTrue(customers["can_edit"])

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

    def test_get_form_for_step_uses_user_field_deny_over_role_allow(self):
        instance = self.create_instance()

        FieldAccess.objects.create(
            field=self.phone_field,
            step=self.step_one,
            user=self.user,
            can_view=False,
            can_edit=False,
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        field_codes = [
            item["field"].code
            for section in result["sections"]
            for item in section["fields"]
        ]

        self.assertNotIn(
            self.phone_field.code,
            field_codes,
        )

    def test_get_form_for_step_uses_user_group_deny_over_role_allow(self):
        instance = self.create_instance()

        RepeatableGroupAccess.objects.create(
            group=self.device_group,
            step=self.step_one,
            user=self.user,
            can_view=False,
            can_edit=False,
            can_add=False,
            can_delete=False,
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        device_groups = [
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].pk == self.device_group.pk
        ]

        self.assertEqual(
            device_groups,
            [],
        )

    def test_get_form_for_step_uses_user_device_field_deny_over_role_allow(self):
        instance = self.create_instance()

        FieldAccess.objects.create(
            field=self.device_model_field,
            step=self.step_one,
            user=self.user,
            can_view=False,
            can_edit=False,
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        device_group = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].pk == self.device_group.pk
        )

        field_codes = [
            item["field"].code
            for item in device_group["fields"]
        ]

        self.assertNotIn(
            self.device_model_field.code,
            field_codes,
        )
        self.assertIn(
            self.device_imei_field.code,
            field_codes,
        )

    def test_save_form_saves_normal_fields(self):
        instance = self.create_instance()

        group_access = RepeatableGroupAccess.objects.get(
            group=self.device_group,
            step=self.step_one,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        group_access.can_view = False
        group_access.save(update_fields=["can_view"])


        submitted_data = {
            "Phone": "09120000000",
            "customer_address": "آدرس تست - کد پستی 1234567890",
        }

        form_data = self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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

        form_data = self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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

        self.assertIsNone(instance_device.device_id)

        self.assertEqual(
            instance_device.draft_imei,
            "777777777777777",
        )

        self.assertIsNone(instance_device.device_id)

        self.assertEqual(
            instance_device.draft_imei,
            "777777777777777",
        )

        self.assertEqual(
            instance_device.draft_device_model_id,
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

        self.save_form_for_step(
            instance=instance_1,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance_2,
            user=self.user,
            submitted_data=submitted_data_2,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
            edit_mode=True,
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
                    "instance_device_id": instance_device.pk,
                    "imei": "999999999999999",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل به‌روزشده",
                    "warranty_status": "WARRANTY",
                    "status": "IN_REPAIR",
                },
            ],
        }

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_data,
            edit_mode=True,
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
    def test_save_form_allows_partial_normal_field_submission(self):
        instance = self.create_instance()

        submitted_data = {
            "Phone": "09120000000",
            "devices": [],
        }

        form_data = self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
        )

        self.assertEqual(
            form_data.data["Phone"],
            "09120000000",
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
            self.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=submitted_data,
                edit_mode=True,
            )

        self.assertFalse(
            InstanceDevice.objects.filter(
                instance=instance,
            ).exists()
        )

    def test_save_form_rejects_imei_for_different_model(self):
        instance = self.create_instance()

        self.create_persistent_device(
            imei="777777777777777",
            device_model=self.device_model,
        )

        device = DeviceService.get_device_by_identifier(
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="777777777777777",
        )

        self.assertIsNotNone(device)
        self.assertEqual(
            device.device_model_id,
            self.device_model.pk,
        )

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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
            edit_mode=True,
        )

        instance_device = InstanceDevice.objects.get(
            instance=instance,
        )

        self.assertIsNotNone(instance_device.device_id)

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
            self.save_form_for_step(
                instance=second_instance,
                user=self.user,
                submitted_data=second_data,
                edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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
        self.assertIsNone(instance_devices[0].device_id)
        self.assertEqual(
            instance_devices[0].draft_imei,
            "111111111111111",
        )
        self.assertEqual(
            instance_devices[0].draft_device_model_id,
            self.device_model.pk,
        )

        self.assertIsNone(instance_devices[1].device_id)
        self.assertEqual(
            instance_devices[1].draft_imei,
            "222222222222222",
        )
        self.assertEqual(
            instance_devices[1].draft_device_model_id,
            second_device_model.pk,
        )

        self.assertEqual(
            instance_devices[0].reported_problem,
            "مشکل دستگاه اول",
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
        device = self.create_persistent_device(
            imei="333333333333333",
            device_model=self.device_model,
        )
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
            edit_mode=True,
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
                    "instance_device_id": instance_device_id,
                    "imei": imei,
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل به‌روزشده",
                    "warranty_status": "WARRANTY",
                    "status": "IN_REPAIR",
                },
            ],
        }

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_submission,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
            edit_mode=True,
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
                    "imei": "777777777777777",
                    "device_model_id": self.device_model.pk,
                    "reported_problem": "مشکل دستگاه اول - UPDATED",
                    "warranty_status": "WARRANTY",
                    "status": "IN_REPAIR",
                },
            ],
        }

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_submission,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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
            self.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=submitted_data,
                edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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
            self.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=update_submission,
                edit_mode=True,
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

        persistent_device = self.create_persistent_device(
            imei="555555555555555",
            device_model=self.device_model,
        )

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
        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
            edit_mode=True,
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
            self.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=submitted_data,
                edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_submission,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
            edit_mode=True,
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_submission,
            edit_mode=True,
        )

        instance_device.refresh_from_db()

        self.assertIsNone(instance_device.device_id)

        self.assertEqual(
            instance_device.draft_imei,
            "444444444444444",
        )

        self.assertFalse(
            DeviceIdentifier.objects.filter(
                value="333333333333333",
            ).exists()
        )

        self.assertFalse(
            DeviceIdentifier.objects.filter(
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

        first_persistent_device = self.create_persistent_device(
            imei="111111111111111",
            device_model=self.device_model,
        )

        second_persistent_device = self.create_persistent_device(
            imei="222222222222222",
            device_model=self.device_model,
        )
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

        self.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_submission,
            edit_mode=True,
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
            self.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=second_submission,
                edit_mode=True,
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