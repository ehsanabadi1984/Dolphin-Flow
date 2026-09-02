import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.form_services import DynamicFormService
from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    LookupItem,
    LookupList,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)

User = get_user_model()


class NormalRepeatableRowIdTests(TestCase):
    """Tests for stable _id on NORMAL repeatable group rows."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="nrrid_test_user",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="NRRID Test Workflow",
            code="NRRID_TEST_WF",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Test Step",
            code="TEST_STEP",
            order=1,
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
            name="NRRID Test Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Test Section",
            code="TEST_SECTION",
            order=1,
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Parts Group",
            code="parts",
            order=1,
            is_active=True,
        )

        cls.part_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Part",
            code="part",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            label="Part",
            order=1,
            is_required=True,
            is_active=True,
        )

        cls.qty_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Quantity",
            code="quantity",
            field_type=FormField.FieldType.NUMBER,
            label="Quantity",
            order=2,
            is_required=True,
            is_active=True,
        )

        # Create lookup list and items for part field
        cls.lookup_list = LookupList.objects.create(
            name="Parts",
            code="PARTS",
            is_active=True,
        )

        cls.part_field.choice_lookup_list = cls.lookup_list
        cls.part_field.save()

        cls.lookup_item_oil = LookupItem.objects.create(
            lookup_list=cls.lookup_list,
            value="oil_filter",
            label="فیلتر روغن",
            order=1,
            is_active=True,
        )

        cls.lookup_item_air = LookupItem.objects.create(
            lookup_list=cls.lookup_list,
            value="air_filter",
            label="فیلتر هوا",
            order=2,
            is_active=True,
        )

        # Grant field permissions
        FieldAccess.objects.create(
            field=cls.part_field,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        FieldAccess.objects.create(
            field=cls.qty_field,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        # Grant repeatable group permissions
        RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
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

    # ==============================================================
    # A. New row gets _id
    # ==============================================================

    def test_new_row_gets_id(self):
        """Saving a new NORMAL repeatable row results in a non-empty _id."""
        instance = self.create_instance()

        submitted_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        rows = form_data.data.get("parts", [])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("_id"))
        self.assertIsInstance(rows[0]["_id"], str)
        self.assertTrue(len(rows[0]["_id"]) > 0)

    # ==============================================================
    # B. _id is unique
    # ==============================================================

    def test_two_new_rows_have_different_ids(self):
        """Two newly created rows have different IDs."""
        instance = self.create_instance()

        submitted_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
            "parts_1_part": "air_filter",
            "parts_1_quantity": "1",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        rows = form_data.data.get("parts", [])
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["_id"], rows[1]["_id"])

    # ==============================================================
    # C. Existing _id survives edit
    # ==============================================================

    def test_existing_id_survives_edit(self):
        """Given a row with _id, after editing its value, _id is preserved."""
        instance = self.create_instance()

        # First save: create a row
        first_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        original_id = form_data.data["parts"][0]["_id"]

        # Second save: edit the quantity, include the _id
        second_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "5",
            "parts_0__id": original_id,
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_data,
        )

        rows = form_data.data.get("parts", [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_id"], original_id)
        self.assertEqual(rows[0]["quantity"], "5")

    # ==============================================================
    # D. _id survives row reordering
    # ==============================================================

    def test_id_survives_reordering(self):
        """After reordering rows, existing _id values are preserved."""
        instance = self.create_instance()

        # Create 3 rows
        first_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "1",
            "parts_1_part": "air_filter",
            "parts_1_quantity": "2",
            "parts_2_part": "oil_filter",
            "parts_2_quantity": "3",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        rows = form_data.data["parts"]
        id_a = rows[0]["_id"]
        id_b = rows[1]["_id"]
        id_c = rows[2]["_id"]

        # Reorder: C, A, B
        reorder_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "3",
            "parts_0__id": id_c,
            "parts_1_part": "oil_filter",
            "parts_1_quantity": "1",
            "parts_1__id": id_a,
            "parts_2_part": "air_filter",
            "parts_2_quantity": "2",
            "parts_2__id": id_b,
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=reorder_data,
        )

        rows = form_data.data["parts"]
        self.assertEqual(rows[0]["_id"], id_c)
        self.assertEqual(rows[1]["_id"], id_a)
        self.assertEqual(rows[2]["_id"], id_b)

    # ==============================================================
    # E. Legacy rows without _id
    # ==============================================================

    def test_legacy_rows_load_successfully(self):
        """Existing JSON rows without _id load without errors."""
        instance = self.create_instance()

        # Manually create legacy data without _id
        form_data = FormData.objects.create(
            instance=instance,
            data={
                "parts": [
                    {"part": "oil_filter", "quantity": "2"},
                    {"part": "air_filter", "quantity": "1"},
                ],
            },
        )

        # Loading should not crash
        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )

        self.assertIsNotNone(result)

    def test_legacy_rows_get_id_on_save(self):
        """Legacy rows without _id receive an _id when saved."""
        instance = self.create_instance()

        # Manually create legacy data without _id
        form_data = FormData.objects.create(
            instance=instance,
            data={
                "parts": [
                    {"part": "oil_filter", "quantity": "2"},
                ],
            },
        )

        # Re-save via the normal save path
        submitted_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        rows = form_data.data.get("parts", [])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("_id"))

    # ==============================================================
    # F. Lookup value remains unchanged
    # ==============================================================

    def test_lookup_value_stored_as_string(self):
        """Lookup value is stored as the LookupItem.value string, not an object."""
        instance = self.create_instance()

        submitted_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        rows = form_data.data.get("parts", [])
        self.assertEqual(rows[0]["part"], "oil_filter")
        self.assertIsInstance(rows[0]["part"], str)

    # ==============================================================
    # G. Lookup label snapshot
    # ==============================================================

    def test_lookup_label_snapshot_created(self):
        """A _lookup_labels dict is created for SELECT LOOKUP fields."""
        instance = self.create_instance()

        submitted_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        rows = form_data.data.get("parts", [])
        self.assertIn("_lookup_labels", rows[0])
        self.assertEqual(
            rows[0]["_lookup_labels"]["part"],
            "فیلتر روغن",
        )

    def test_lookup_label_snapshot_preserved_on_unchanged_value(self):
        """When value is unchanged, the previous snapshot is preserved."""
        instance = self.create_instance()

        # First save
        first_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        original_id = form_data.data["parts"][0]["_id"]

        # Change the label in the lookup list (simulating admin edit)
        self.lookup_item_oil.label = "فیلتر روغن (تغییر یافته)"
        self.lookup_item_oil.save()

        # Second save with same value
        second_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "3",
            "parts_0__id": original_id,
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_data,
        )

        # The snapshot should still show the ORIGINAL label
        rows = form_data.data.get("parts", [])
        self.assertEqual(
            rows[0]["_lookup_labels"]["part"],
            "فیلتر روغن",
        )

    def test_lookup_label_snapshot_updates_on_value_change(self):
        """When value changes, the snapshot updates to the new label."""
        instance = self.create_instance()

        # First save with oil_filter
        first_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        original_id = form_data.data["parts"][0]["_id"]

        # Second save with air_filter
        second_data = {
            "parts_0_part": "air_filter",
            "parts_0_quantity": "1",
            "parts_0__id": original_id,
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_data,
        )

        rows = form_data.data.get("parts", [])
        self.assertEqual(rows[0]["part"], "air_filter")
        self.assertEqual(
            rows[0]["_lookup_labels"]["part"],
            "فیلتر هوا",
        )

    # ==============================================================
    # H. DEVICE groups are unaffected (smoke test)
    # ==============================================================

    def test_device_groups_still_work(self):
        """DEVICE repeatable groups continue to use InstanceDevice."""
        from workflow.models import DeviceModel, DeviceType, InstanceDevice

        device_type = DeviceType.objects.create(
            name="Test Type",
            code="TEST_TYPE_NRRID",
            is_active=True,
        )

        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Test",
            name="Test Model",
            code="TEST_MODEL_NRRID",
            is_active=True,
        )

        device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Device Group",
            code="devices",
            order=2,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            is_active=True,
        )

        FormField.objects.create(
            section=self.section,
            repeatable_group=device_group,
            name="IMEI",
            code="imei",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.IMEI,
            label="IMEI",
            order=1,
            is_required=True,
            is_active=True,
        )

        FormField.objects.create(
            section=self.section,
            repeatable_group=device_group,
            name="Device Model",
            code="device_model_id",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.DEVICE_MODEL,
            label="Model",
            order=2,
            is_required=True,
            is_active=True,
        )

        # Grant device field permissions
        for field in device_group.fields.all():
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                role=WorkflowMembership.Role.EXECUTOR,
                can_view=True,
                can_edit=True,
            )

        RepeatableGroupAccess.objects.create(
            group=device_group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
        )

        instance = self.create_instance()

        submitted_data = {
            "parts_0_part": "oil_filter",
            "parts_0_quantity": "2",
            "devices_0_imei": "123456789012345",
            "devices_0_device_model_id": str(device_model.pk),
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        # Device is stored in InstanceDevice, not in FormData
        self.assertTrue(
            InstanceDevice.objects.filter(
                instance=instance,
            ).exists()
        )

        # Normal group has _id
        parts = form_data.data.get("parts", [])
        self.assertTrue(parts[0].get("_id"))

        # Device group is NOT in FormData
        self.assertNotIn("devices", form_data.data)


class NormalRepeatableRowIdEdgeCaseTests(TestCase):
    """Edge cases for stable _id."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="nrrid_edge_user",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="NRRID Edge Workflow",
            code="NRRID_EDGE_WF",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Test Step",
            code="TEST_STEP",
            order=1,
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
            name="NRRID Edge Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Test Section",
            code="TEST_SECTION",
            order=1,
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Items Group",
            code="items",
            order=1,
            is_active=True,
        )

        cls.name_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Name",
            code="name",
            field_type=FormField.FieldType.TEXT,
            label="Name",
            order=1,
            is_required=True,
            is_active=True,
        )

        FieldAccess.objects.create(
            field=cls.name_field,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
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

    def test_delete_middle_row_preserves_other_ids(self):
        """Deleting the middle row preserves _id of remaining rows."""
        instance = self.create_instance()

        # Create 3 rows
        first_data = {
            "items_0_name": "A",
            "items_1_name": "B",
            "items_2_name": "C",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        rows = form_data.data["items"]
        id_a = rows[0]["_id"]
        id_b = rows[1]["_id"]
        id_c = rows[2]["_id"]

        # Delete middle row (B) — submit only A and C
        delete_data = {
            "items_0_name": "A",
            "items_0__id": id_a,
            "items_1_name": "C",
            "items_1__id": id_c,
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=delete_data,
        )

        rows = form_data.data["items"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["_id"], id_a)
        self.assertEqual(rows[0]["name"], "A")
        self.assertEqual(rows[1]["_id"], id_c)
        self.assertEqual(rows[1]["name"], "C")

    def test_empty_group_saves_empty_list(self):
        """Saving with no rows results in an empty list."""
        instance = self.create_instance()

        submitted_data = {}

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        # The group should not be in data at all (no items submitted)
        self.assertNotIn("items", form_data.data)

    def test_non_dict_rows_are_skipped(self):
        """Non-dict items in existing data are safely skipped."""
        instance = self.create_instance()

        # Manually create malformed data
        FormData.objects.create(
            instance=instance,
            data={
                "items": [
                    "not_a_dict",
                    {"name": "valid"},
                ],
            },
        )

        submitted_data = {
            "items_0_name": "valid",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        rows = form_data.data.get("items", [])
        # The valid row should be processed
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("_id"))

    def test_submitted_id_for_nonexistent_previous_row_ignored(self):
        """If submitted _id doesn't match any previous row, treat as new."""
        instance = self.create_instance()

        # First save
        first_data = {
            "items_0_name": "A",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        original_id = form_data.data["items"][0]["_id"]

        # Second save with a fabricated _id that doesn't match
        second_data = {
            "items_0_name": "B",
            "items_0__id": "nonexistent-id-12345",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_data,
        )

        rows = form_data.data.get("items", [])
        self.assertEqual(len(rows), 1)
        # The fabricated _id is used as-is (it becomes the new identity)
        self.assertEqual(rows[0]["_id"], "nonexistent-id-12345")
        self.assertEqual(rows[0]["name"], "B")


class LegacyRowFallbackTests(TestCase):
    """Test fallback matching for legacy rows without _id."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="legacy_fallback_user",
            password="test-password",
        )

        cls.other_user = User.objects.create_user(
            username="legacy_fallback_other",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="Legacy Fallback Workflow",
            code="LEGACY_FB_WF",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step",
            code="STEP",
            order=1,
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
            name="Legacy Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Section",
            code="SEC",
            order=1,
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Items",
            code="items",
            order=1,
            is_active=True,
        )

        cls.name_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Name",
            code="name",
            field_type=FormField.FieldType.TEXT,
            label="Name",
            order=1,
            is_required=True,
            is_active=True,
        )

        cls.note_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Note",
            code="note",
            field_type=FormField.FieldType.TEXT,
            label="Note",
            order=2,
            is_required=False,
            is_active=True,
        )

        # User can edit 'name' but NOT 'note'
        FieldAccess.objects.create(
            field=cls.name_field,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
        )

        FieldAccess.objects.create(
            field=cls.note_field,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=False,
        )

        RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
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

    def test_legacy_row_preserves_non_editable_fields(self):
        """
        Legacy row without _id: non-editable field value is preserved,
        row receives a _id, and subsequent save matches by _id.
        """
        instance = self.create_instance()

        # Create legacy data: row without _id
        # 'note' has a value that the current user cannot edit
        form_data = FormData.objects.create(
            instance=instance,
            data={
                "items": [
                    {
                        "name": "Original Name",
                        "note": "Important note set by admin",
                    },
                ],
            },
        )

        # Submit the row without _id (legacy behavior)
        submitted_data = {
            "items_0_name": "Updated Name",
            "items_0_note": "",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        rows = form_data.data.get("items", [])
        self.assertEqual(len(rows), 1)

        # Row must receive a _id
        self.assertTrue(rows[0].get("_id"))

        # Editable field was updated
        self.assertEqual(rows[0]["name"], "Updated Name")

        # Non-editable field was preserved (not overwritten with empty)
        self.assertEqual(
            rows[0]["note"],
            "Important note set by admin",
        )

    def test_legacy_row_subsequent_save_matches_by_id(self):
        """
        After a legacy row receives a _id, the next save
        must match it by _id, not by index.
        """
        instance = self.create_instance()

        # Create legacy data
        FormData.objects.create(
            instance=instance,
            data={
                "items": [
                    {
                        "name": "Original",
                        "note": "Admin note",
                    },
                ],
            },
        )

        # First save: legacy row gets _id
        first_data = {
            "items_0_name": "First Update",
            "items_0_note": "",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=first_data,
        )

        row_id = form_data.data["items"][0]["_id"]
        self.assertTrue(row_id)

        # Second save: include _id explicitly
        second_data = {
            "items_0_name": "Second Update",
            "items_0_note": "",
            "items_0__id": row_id,
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=second_data,
        )

        rows = form_data.data.get("items", [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_id"], row_id)
        self.assertEqual(rows[0]["name"], "Second Update")
        self.assertEqual(rows[0]["note"], "Admin note")

    def test_two_legacy_rows_matched_by_respective_indexes(self):
        """
        Two legacy rows without _id are matched by their
        respective array indexes, not swapped.
        """
        instance = self.create_instance()

        FormData.objects.create(
            instance=instance,
            data={
                "items": [
                    {
                        "name": "Row A",
                        "note": "Note A (admin)",
                    },
                    {
                        "name": "Row B",
                        "note": "Note B (admin)",
                    },
                ],
            },
        )

        # Submit both rows without _id, swapping names
        submitted_data = {
            "items_0_name": "Row A updated",
            "items_0_note": "",
            "items_1_name": "Row B updated",
            "items_1_note": "",
        }

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data=submitted_data,
        )

        rows = form_data.data["items"]
        self.assertEqual(len(rows), 2)

        # Each row got a _id
        self.assertTrue(rows[0].get("_id"))
        self.assertTrue(rows[1].get("_id"))
        self.assertNotEqual(rows[0]["_id"], rows[1]["_id"])

        # Names were updated
        self.assertEqual(rows[0]["name"], "Row A updated")
        self.assertEqual(rows[1]["name"], "Row B updated")

        # Non-editable notes preserved from correct legacy rows
        self.assertEqual(rows[0]["note"], "Note A (admin)")
        self.assertEqual(rows[1]["note"], "Note B (admin)")
