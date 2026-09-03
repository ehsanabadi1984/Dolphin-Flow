"""
Regression tests for the four RED Dynamic Form fixes:

1. NORMAL vs DEVICE permission identity
   - NORMAL rows are identified by `_id` (matched against persisted rows).
   - DEVICE rows are identified by `instance_device_id`.
   - Existing rows require can_edit; new rows require can_add.

2. POST-priority NORMAL rendering after a validation error
   - submitted POST state is authoritative for re-rendering.

3. True empty state for NORMAL repeatable groups
   - [] means genuinely empty; no synthetic blank row is fabricated.

4. Server-side can_delete enforcement for NORMAL groups
   - a persisted row omitted from the replace-all POST is a deletion
     and requires can_delete.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template.loader import get_template
from django.test import RequestFactory, TestCase

from workflow.form_services import DynamicFormService
from workflow.models import (
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
    FieldAccess,
    FormData,
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


class NormalRepeatablePermissionFixTests(TestCase):
    """
    RED #1 + #4: NORMAL repeatable rows are identified by `_id`
    and deletion requires can_delete.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="red_perm_test",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="RED Perm Workflow",
            code="RED_PERM_WF",
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
            name="Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Sec",
            code="SEC",
            order=1,
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Parts",
            code="parts",
            order=1,
            is_active=True,
        )

        cls.part_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Part",
            code="part",
            field_type=FormField.FieldType.TEXT,
            label="Part",
            order=1,
            is_active=True,
        )

        cls.qty_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Qty",
            code="qty",
            field_type=FormField.FieldType.NUMBER,
            label="Qty",
            order=2,
            is_active=True,
        )

        for field in cls.group.fields.all():
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                user=cls.user,
                can_view=True,
                can_edit=True,
            )

        cls.group_access = RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

    def set_group_perms(self, *, can_edit, can_add, can_delete):
        self.group_access.can_edit = can_edit
        self.group_access.can_add = can_add
        self.group_access.can_delete = can_delete
        self.group_access.save()

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

    def save_rows(self, instance, count):
        """Persist `count` NORMAL rows and return their _id values."""
        submitted_data = {}
        for i in range(count):
            submitted_data[f"parts_{i}_part"] = f"part-{i}"
            submitted_data[f"parts_{i}_qty"] = str(i + 1)

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        return [
            row["_id"]
            for row in form_data.data["parts"]
        ]

    # ----------------------------------------------------------
    # RED #1: NORMAL permission identity
    # ----------------------------------------------------------

    def test_existing_row_edit_with_can_edit_and_no_can_add_succeeds(self):
        """NORMAL existing row + can_edit=True + can_add=False -> save succeeds."""
        instance = self.create_instance()
        row_id = self.save_rows(instance, 1)[0]

        self.set_group_perms(
            can_edit=True,
            can_add=False,
            can_delete=True,
        )

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "part-0",
                "parts_0_qty": "99",
                "parts_0__id": row_id,
            },
        )

        rows = form_data.data["parts"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_id"], row_id)
        self.assertEqual(rows[0]["qty"], "99")

    def test_existing_row_edit_rejected_without_can_edit(self):
        """NORMAL existing row + can_edit=False -> edit is rejected."""
        instance = self.create_instance()
        row_id = self.save_rows(instance, 1)[0]

        self.set_group_perms(
            can_edit=False,
            can_add=True,
            can_delete=True,
        )

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "parts_0_part": "part-0",
                    "parts_0_qty": "99",
                    "parts_0__id": row_id,
                },
            )

        # Persisted data must be unchanged.
        persisted = FormData.objects.get(
            instance=instance
        ).data["parts"]
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["_id"], row_id)
        self.assertEqual(persisted[0]["qty"], "1")

    def test_new_row_with_can_add_succeeds(self):
        """NORMAL new row + can_add=True -> save succeeds."""
        instance = self.create_instance()

        self.set_group_perms(
            can_edit=False,
            can_add=True,
            can_delete=False,
        )

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "new-part",
                "parts_0_qty": "1",
            },
        )

        rows = form_data.data["parts"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("_id"))

    def test_new_row_rejected_without_can_add(self):
        """NORMAL new row + can_add=False -> save is rejected."""
        instance = self.create_instance()

        self.set_group_perms(
            can_edit=True,
            can_add=False,
            can_delete=False,
        )

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "parts_0_part": "new-part",
                    "parts_0_qty": "1",
                },
            )

        self.assertFalse(
            FormData.objects.filter(instance=instance).exists()
        )

    # ----------------------------------------------------------
    # RED #4: can_delete enforcement
    # ----------------------------------------------------------

    def test_delete_row_allowed_with_can_delete(self):
        """3 rows -> 2 rows with can_delete=True deletes the omitted row."""
        instance = self.create_instance()
        row_ids = self.save_rows(instance, 3)

        self.set_group_perms(
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "part-0",
                "parts_0_qty": "1",
                "parts_0__id": row_ids[0],
                "parts_1_part": "part-2",
                "parts_1_qty": "3",
                "parts_1__id": row_ids[2],
            },
        )

        rows = form_data.data["parts"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["_id"] for row in rows},
            {row_ids[0], row_ids[2]},
        )

    def test_delete_row_rejected_without_can_delete(self):
        """3 rows -> 2 rows with can_delete=False rejects and preserves data."""
        instance = self.create_instance()
        row_ids = self.save_rows(instance, 3)

        self.set_group_perms(
            can_edit=True,
            can_add=True,
            can_delete=False,
        )

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "parts_0_part": "part-0",
                    "parts_0_qty": "1",
                    "parts_0__id": row_ids[0],
                    "parts_1_part": "part-2",
                    "parts_1_qty": "3",
                    "parts_1__id": row_ids[2],
                },
            )

        persisted = FormData.objects.get(
            instance=instance
        ).data["parts"]
        self.assertEqual(len(persisted), 3)
        self.assertEqual(
            {row["_id"] for row in persisted},
            set(row_ids),
        )

    def test_delete_all_rows_rejected_without_can_delete(self):
        """Zero submitted rows with can_delete=False rejects and preserves data."""
        instance = self.create_instance()
        self.save_rows(instance, 3)

        self.set_group_perms(
            can_edit=True,
            can_add=True,
            can_delete=False,
        )

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={},
            )

        persisted = FormData.objects.get(
            instance=instance
        ).data["parts"]
        self.assertEqual(len(persisted), 3)

    def test_delete_all_rows_allowed_with_can_delete(self):
        """Zero submitted rows with can_delete=True persists []."""
        instance = self.create_instance()
        self.save_rows(instance, 3)

        self.set_group_perms(
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={},
        )

        self.assertEqual(form_data.data["parts"], [])

        # The GET view of the group is genuinely empty.
        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )
        group = None
        for section in result["sections"]:
            for g in section["repeatable_groups"]:
                if g["group"].code == "parts":
                    group = g
        self.assertIsNotNone(group)
        self.assertEqual(group["items"], [])

    def test_edit_without_can_delete_still_works(self):
        """Editing an existing row with can_delete=False succeeds when the
        row remains in the POST payload (no deletion)."""
        instance = self.create_instance()
        row_ids = self.save_rows(instance, 3)

        self.set_group_perms(
            can_edit=True,
            can_add=True,
            can_delete=False,
        )

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "part-0",
                "parts_0_qty": "10",
                "parts_0__id": row_ids[0],
                "parts_1_part": "part-1",
                "parts_1_qty": "2",
                "parts_1__id": row_ids[1],
                "parts_2_part": "part-2",
                "parts_2_qty": "3",
                "parts_2__id": row_ids[2],
            },
        )

        rows = form_data.data["parts"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["qty"], "10")


class DeviceRepeatablePermissionSemanticsTests(TestCase):
    """
    RED #1 (DEVICE side): DEVICE rows keep the instance_device_id
    identity semantics; can_add/can_edit gates are unchanged.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="red_device_perm_test",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="RED Device Perm WF",
            code="RED_DEV_PERM_WF",
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
            name="Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Sec",
            code="SEC",
            order=1,
            is_active=True,
        )

        cls.device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE",
            is_active=True,
        )

        cls.device_model = DeviceModel.objects.create(
            device_type=cls.device_type,
            brand="B",
            name="M",
            code="BM",
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Devices",
            code="devices",
            order=1,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            is_active=True,
        )

        cls.imei_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="IMEI",
            code="imei",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.IMEI,
            label="IMEI",
            order=1,
            is_active=True,
        )

        cls.model_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Model",
            code="device_model_id",
            field_type=FormField.FieldType.SELECT,
            system_key=FormField.SystemKey.DEVICE_MODEL,
            label="Model",
            order=2,
            is_active=True,
        )

        for field in cls.group.fields.all():
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                user=cls.user,
                can_view=True,
                can_edit=True,
            )

        cls.group_access = RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

    def set_group_perms(self, *, can_edit, can_add):
        self.group_access.can_edit = can_edit
        self.group_access.can_add = can_add
        self.group_access.save()

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

    def test_existing_device_edit_uses_instance_device_id_semantics(self):
        """A submitted instance_device_id is an existing row: requires
        can_edit (not can_add)."""
        instance = self.create_instance()

        # Create one unidentified (draft) device.
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "",
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)

        self.set_group_perms(can_edit=True, can_add=False)

        # Re-submitting the existing device row must NOT require can_add.
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_instance_device_id": str(instance_device.pk),
                "devices_0_imei": "",
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        instance_device.refresh_from_db()
        self.assertIsNone(instance_device.device)

    def test_new_device_requires_can_add(self):
        """A row without instance_device_id is a new device: requires can_add."""
        instance = self.create_instance()

        self.set_group_perms(can_edit=True, can_add=False)

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "devices_0_imei": "",
                    "devices_0_device_model_id": str(self.device_model.pk),
                },
            )

        self.assertFalse(
            InstanceDevice.objects.filter(instance=instance).exists()
        )

    def test_existing_device_edit_rejected_without_can_edit(self):
        """A submitted instance_device_id without can_edit is rejected."""
        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "",
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)

        self.set_group_perms(can_edit=False, can_add=True)

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "devices_0_instance_device_id": str(instance_device.pk),
                    "devices_0_imei": "",
                    "devices_0_device_model_id": str(self.device_model.pk),
                },
            )

        instance_device.refresh_from_db()
        self.assertIsNone(instance_device.device)

    def test_identified_device_imei_lookup_still_works(self):
        """Identified-device behavior is unchanged."""
        from workflow.models import Device

        device = Device.objects.create(device_model=self.device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="999999999999999",
        )

        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "999999999999999",
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)
        self.assertEqual(instance_device.device_id, device.pk)


class ValidationErrorRerenderTests(TestCase):
    """
    RED #2: after a validation error the form must re-render from the
    submitted POST state, not from persisted FormData.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="red_rerender_test",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="RED Rerender WF",
            code="RED_RERENDER_WF",
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
            name="Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Sec",
            code="SEC",
            order=1,
            is_active=True,
        )

        # A required NORMAL field used to trigger a validation error
        # "elsewhere" (outside the repeatable group).
        cls.note_field = FormField.objects.create(
            section=cls.section,
            name="Note",
            code="note",
            field_type=FormField.FieldType.TEXT,
            label="Note",
            order=1,
            is_required=True,
            is_active=True,
        )

        FieldAccess.objects.create(
            field=cls.note_field,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Parts",
            code="parts",
            order=2,
            is_active=True,
        )

        cls.part_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Part",
            code="part",
            field_type=FormField.FieldType.TEXT,
            label="Part",
            order=1,
            is_active=True,
        )

        cls.qty_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Qty",
            code="qty",
            field_type=FormField.FieldType.NUMBER,
            label="Qty",
            order=2,
            is_active=True,
        )

        for field in cls.group.fields.all():
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                user=cls.user,
                can_view=True,
                can_edit=True,
            )

        cls.group_access = RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
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

    def save_rows(self, instance, rows):
        """rows: list of (part, qty). Returns list of _id."""
        submitted_data = {"note": "ok"}
        for i, (part, qty) in enumerate(rows):
            submitted_data[f"parts_{i}_part"] = part
            submitted_data[f"parts_{i}_qty"] = qty

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        return [row["_id"] for row in form_data.data["parts"]]

    @staticmethod
    def get_group_items(result, code="parts"):
        for section in result["sections"]:
            for group in section["repeatable_groups"]:
                if group["group"].code == code:
                    return group["items"]
        return None

    @staticmethod
    def get_field_value(item, code):
        for item_field in item["fields"]:
            if item_field["field"].code == code:
                return item_field["value"]
        return None

    def test_existing_rows_keep_submitted_values_after_validation_error(self):
        """Existing row + validation error -> entered values remain."""
        instance = self.create_instance()
        row_id = self.save_rows(instance, [("oil_filter", "2")])[0]

        # The note field is blank -> validation error.
        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "parts_0_part": "oil_filter",
                    "parts_0_qty": "7",
                    "parts_0__id": row_id,
                    "note": "",
                },
            )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "oil_filter",
                "parts_0_qty": "7",
                "parts_0__id": row_id,
                "note": "",
            },
            edit_mode=True,
        )

        items = self.get_group_items(result)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["row_id"], row_id)
        self.assertEqual(
            self.get_field_value(items[0], "qty"),
            "7",
        )
        self.assertEqual(
            self.get_field_value(items[0], "part"),
            "oil_filter",
        )

    def test_new_row_stays_visible_after_validation_error(self):
        """A newly added row survives a validation error re-render."""
        instance = self.create_instance()

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "parts_0_part": "air_filter",
                    "parts_0_qty": "3",
                    "note": "",
                },
            )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "air_filter",
                "parts_0_qty": "3",
                "note": "",
            },
            edit_mode=True,
        )

        items = self.get_group_items(result)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            self.get_field_value(items[0], "part"),
            "air_filter",
        )
        self.assertEqual(
            self.get_field_value(items[0], "qty"),
            "3",
        )

    def test_deleted_row_does_not_reappear_after_validation_error(self):
        """A deleted row stays deleted after a validation error re-render."""
        instance = self.create_instance()
        row_ids = self.save_rows(instance, [("a", "1"), ("b", "2")])

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "parts_0_part": "a",
                    "parts_0_qty": "1",
                    "parts_0__id": row_ids[0],
                    "note": "",
                },
            )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "a",
                "parts_0_qty": "1",
                "parts_0__id": row_ids[0],
                "note": "",
            },
            edit_mode=True,
        )

        items = self.get_group_items(result)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["row_id"], row_ids[0])

    def test_reordering_keeps_id_identity_after_validation_error(self):
        """Reordering rows does not lose _id identity on re-render."""
        instance = self.create_instance()
        row_ids = self.save_rows(instance, [("a", "1"), ("b", "2")])

        submitted = {
            "parts_0_part": "b",
            "parts_0_qty": "2",
            "parts_0__id": row_ids[1],
            "parts_1_part": "a",
            "parts_1_qty": "1",
            "parts_1__id": row_ids[0],
            "note": "",
        }

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data=submitted,
            )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted,
            edit_mode=True,
        )

        items = self.get_group_items(result)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["row_id"], row_ids[1])
        self.assertEqual(items[1]["row_id"], row_ids[0])


class TrueEmptyStateTests(TestCase):
    """
    RED #3: [] is the genuine empty state for NORMAL repeatable groups.
    No synthetic blank row may be created by rendering or by saving an
    untouched form.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="red_empty_test",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="RED Empty WF",
            code="RED_EMPTY_WF",
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
            name="Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Sec",
            code="SEC",
            order=1,
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Parts",
            code="parts",
            order=1,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )

        cls.part_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Part",
            code="part",
            field_type=FormField.FieldType.TEXT,
            label="Part",
            order=1,
            is_active=True,
        )

        FieldAccess.objects.create(
            field=cls.part_field,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
        )

        cls.group_access = RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
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

    def get_group(self, result, code="parts"):
        for section in result["sections"]:
            for group in section["repeatable_groups"]:
                if group["group"].code == code:
                    return group
        return None

    def test_empty_optional_group_renders_zero_rows(self):
        """GET of an untouched optional NORMAL group -> zero real rows."""
        instance = self.create_instance()

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        group = self.get_group(result)
        self.assertIsNotNone(group)
        self.assertEqual(group["items"], [])
        self.assertTrue(group["can_add"])

    def test_submit_without_adding_persists_empty_group(self):
        """Saving an untouched optional group does not create a phantom row."""
        instance = self.create_instance()

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={},
        )

        self.assertEqual(form_data.data.get("parts", []), [])

        # No phantom _id row may appear just by saving.
        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )
        group = self.get_group(result)
        self.assertEqual(group["items"], [])

    def test_explicitly_added_row_gets_real_id(self):
        """An explicitly added row is persisted with a real _id."""
        instance = self.create_instance()

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "oil_filter",
            },
        )

        rows = form_data.data["parts"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("_id"))

    def test_delete_all_rows_persists_empty_when_allowed(self):
        """Deleting every row where the business rules allow it -> []."""
        instance = self.create_instance()

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "parts_0_part": "a",
                "parts_1_part": "b",
            },
        )

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={},
        )

        self.assertEqual(form_data.data["parts"], [])

    def test_required_group_behavior_unchanged(self):
        """A required NORMAL group with no rows is still rejected on save."""
        self.group.is_required = True
        self.group.save()

        instance = self.create_instance()

        try:
            with self.assertRaises(ValidationError):
                DynamicFormService.save_form_for_step(
                    instance=instance,
                    user=self.user,
                    submitted_data={},
                )
        finally:
            self.group.is_required = False
            self.group.save()

    def test_empty_group_ui_still_offers_add(self):
        """
        The empty group still renders the Add button and a hidden row
        template, so the JS can create the first row.
        """
        instance = self.create_instance()

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        request = RequestFactory().get("/")
        request.user = self.user

        context = {
            "instance": instance,
            "dynamic_form": result,
            "edit_mode": True,
            "transitions": [],
            "error": None,
            "validation_errors": [],
            "has_saved_data": False,
            "current_step_execution": None,
        }

        html = get_template(
            "operator_panel/workflow_instance.html"
        ).render(context, request)

        self.assertIn("+ افزودن", html)
        self.assertIn("data-repeatable-template", html)
        # The empty-state message is present.
        self.assertIn("هنوز اطلاعاتی برای این گروه ثبت نشده است.", html)
