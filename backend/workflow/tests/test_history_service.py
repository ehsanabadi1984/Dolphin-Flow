from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.models import User

from workflow.form_file_models import FormFile
from workflow.history_models import HistoryConfiguration, HistoryField
from workflow.history_services import HistoryService
from workflow.models import (
    Device,
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
)
from workflow.services import WorkflowExecutionService


class HistoryServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="history-test",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="History Test Workflow",
            code="HISTORY_TEST",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Repair",
            code="REPAIR",
            order=1,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Repair Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Main",
            code="MAIN",
            order=1,
        )
        self.imei_field = FormField.objects.create(
            section=self.section,
            name="IMEI",
            code="imei",
            label="IMEI",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        self.problem_field = FormField.objects.create(
            section=self.section,
            name="Problem",
            code="problem",
            label="Problem",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        self.group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parts",
            code="parts",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            order=1,
        )
        self.part_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="Part Name",
            code="part_name",
            label="Part Name",
            field_type=FormField.FieldType.TEXT,
            order=2,
        )

    def _instance(self, *, data=None):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
        )
        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step,
            performed_by=self.user,
        )
        FormData.objects.create(
            instance=instance,
            data=data or {},
        )
        return instance

    def test_active_configuration_is_the_primary_selection_source(self):
        configuration = HistoryConfiguration.objects.create(
            form=self.form,
            name="Repair History",
        )
        history_field = HistoryField.objects.create(
            configuration=configuration,
            form_field=self.imei_field,
            display_label="شماره IMEI",
            display_order=10,
            is_enabled=True,
        )
        HistoryField.objects.create(
            configuration=configuration,
            form_field=self.problem_field,
            display_order=20,
            is_enabled=False,
        )

        instance = self._instance(
            data={
                "imei": "111222333",
                "problem": "Screen broken",
            }
        )

        snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=self.user,
        )

        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["configuration_id"], configuration.pk)
        self.assertEqual(len(snapshot["fields"]), 1)
        self.assertEqual(snapshot["fields"][0]["code"], "imei")
        self.assertEqual(snapshot["fields"][0]["display_label"], "شماره IMEI")
        self.assertEqual(snapshot["fields"][0]["display_order"], 10)
        self.assertEqual(snapshot["fields"][0]["history_field_id"], history_field.pk)

    def test_normal_repeatable_rows_keep_their_row_id_and_values(self):
        configuration = HistoryConfiguration.objects.create(form=self.form)
        HistoryField.objects.create(
            configuration=configuration,
            form_field=self.part_field,
            display_label="قطعه",
            display_order=1,
        )

        instance = self._instance()

        from workflow.repeatable_row_services import RepeatableRowService

        row_1 = RepeatableRowService.create_row(
            instance=instance,
            group=self.group,
            row_order=0,
        )
        row_2 = RepeatableRowService.create_row(
            instance=instance,
            group=self.group,
            row_order=1,
        )
        RepeatableRowService.set_value(
            row=row_1,
            field=self.part_field,
            value="LCD",
        )
        RepeatableRowService.set_value(
            row=row_2,
            field=self.part_field,
            value="Battery",
        )

        snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=self.user,
        )

        items = snapshot["repeatable_groups"][0]["items"]
        self.assertEqual([item["row_id"] for item in items], [row_1.pk, row_2.pk])
        self.assertEqual(items[0]["fields"][0]["value"], "LCD")
        self.assertEqual(items[1]["fields"][0]["value"], "Battery")

    def test_nested_repeatable_rows_preserve_parent_child_hierarchy(self):
        configuration = HistoryConfiguration.objects.create(form=self.form)

        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Part Details",
            code="part_details",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            order=3,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Serial",
            code="serial",
            label="Serial",
            field_type=FormField.FieldType.TEXT,
            order=4,
        )
        HistoryField.objects.create(
            configuration=configuration,
            form_field=self.part_field,
            display_label="قطعه",
            display_order=1,
        )
        HistoryField.objects.create(
            configuration=configuration,
            form_field=child_field,
            display_label="سریال",
            display_order=2,
        )

        instance = self._instance()

        from workflow.repeatable_row_services import RepeatableRowService

        parent_a = RepeatableRowService.create_row(
            instance=instance,
            group=self.group,
            row_order=0,
        )
        parent_b = RepeatableRowService.create_row(
            instance=instance,
            group=self.group,
            row_order=1,
        )
        RepeatableRowService.set_value(
            row=parent_a,
            field=self.part_field,
            value="LCD",
        )
        RepeatableRowService.set_value(
            row=parent_b,
            field=self.part_field,
            value="Battery",
        )

        child_a = RepeatableRowService.create_row(
            instance=instance,
            group=child_group,
            parent_row=parent_a,
            row_order=0,
        )
        child_b = RepeatableRowService.create_row(
            instance=instance,
            group=child_group,
            parent_row=parent_b,
            row_order=0,
        )
        RepeatableRowService.set_value(
            row=child_a,
            field=child_field,
            value="SERIAL-A",
        )
        RepeatableRowService.set_value(
            row=child_b,
            field=child_field,
            value="SERIAL-B",
        )

        snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=self.user,
        )

        parent_group = next(
            group
            for group in snapshot["repeatable_groups"]
            if group["code"] == self.group.code
        )

        self.assertIn("child_groups", parent_group["items"][0])
        self.assertIn("child_groups", parent_group["items"][1])

        self.assertEqual(
            [
                (
                    item["fields"][0]["value"],
                    item["child_groups"][0]["code"],
                    item["child_groups"][0]["items"][0]["fields"][0]["value"],
                )
                for item in parent_group["items"]
            ],
            [
                ("LCD", child_group.code, "SERIAL-A"),
                ("Battery", child_group.code, "SERIAL-B"),
            ],
        )

    def test_repeatable_file_is_included_in_history_snapshot(self):
        configuration = HistoryConfiguration.objects.create(form=self.form)
        file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="Attachment",
            code="attachment",
            label="Attachment",
            field_type=FormField.FieldType.FILE,
            order=3,
        )
        HistoryField.objects.create(
            configuration=configuration,
            form_field=file_field,
            display_label="پیوست",
            display_order=2,
        )

        instance = self._instance()

        from workflow.repeatable_row_services import RepeatableRowService

        row = RepeatableRowService.create_row(
            instance=instance,
            group=self.group,
            row_order=0,
        )
        RepeatableRowService.set_value(
            row=row,
            field=self.part_field,
            value="LCD",
        )

        form_data = FormData.objects.get(instance=instance)
        FormFile.objects.create(
            form_data=form_data,
            field=file_field,
            row_id=str(row.pk),
            file=SimpleUploadedFile(
                "repair-photo.jpg",
                b"historical-file-content",
                content_type="image/jpeg",
            ),
            original_name="repair-photo.jpg",
            file_size=22,
            content_type="image/jpeg",
            uploaded_by=self.user,
        )

        snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=self.user,
        )

        item = snapshot["repeatable_groups"][0]["items"][0]
        file_history = next(
            field
            for field in item["fields"]
            if field["code"] == file_field.code
        )

        self.assertEqual(
            file_history["file"],
            {
                "name": "repair-photo.jpg",
                "size": 22,
                "content_type": "image/jpeg",
            },
        )

    def test_file_history_snapshot_contains_metadata_only(self):
        configuration = HistoryConfiguration.objects.create(form=self.form)
        file_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="Attachment",
            code="attachment_metadata",
            label="Attachment",
            field_type=FormField.FieldType.FILE,
            order=3,
        )
        HistoryField.objects.create(
            configuration=configuration,
            form_field=file_field,
            display_label="پیوست",
            display_order=2,
        )

        instance = self._instance()
        from workflow.repeatable_row_services import RepeatableRowService

        row = RepeatableRowService.create_row(
            instance=instance,
            group=self.group,
            row_order=0,
        )
        form_data = FormData.objects.get(instance=instance)
        form_file = FormFile.objects.create(
            form_data=form_data,
            field=file_field,
            row_id=str(row.pk),
            file=SimpleUploadedFile(
                "history-secret.pdf",
                b"historical-file-content",
                content_type="application/pdf",
            ),
            original_name="history-secret.pdf",
            file_size=22,
            content_type="application/pdf",
            uploaded_by=self.user,
        )

        snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=self.user,
        )

        file_history = snapshot["repeatable_groups"][0]["items"][0]["fields"][0]["file"]

        self.assertEqual(
            set(file_history),
            {"name", "size", "content_type"},
        )
        self.assertEqual(
            file_history,
            {
                "name": "history-secret.pdf",
                "size": 22,
                "content_type": "application/pdf",
            },
        )
        self.assertNotIn("url", file_history)
        self.assertNotIn("delete_url", file_history)
        self.assertNotIn("path", file_history)
        self.assertNotIn("file", file_history)
        self.assertEqual(form_file.original_name, file_history["name"])

    def test_nested_repeatable_files_preserve_parent_child_ownership(self):
        configuration = HistoryConfiguration.objects.create(form=self.form)

        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Part Details",
            code="part_details",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            order=3,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Attachment",
            code="attachment",
            label="Attachment",
            field_type=FormField.FieldType.FILE,
            order=4,
        )
        HistoryField.objects.create(
            configuration=configuration,
            form_field=self.part_field,
            display_label="قطعه",
            display_order=1,
        )
        HistoryField.objects.create(
            configuration=configuration,
            form_field=child_field,
            display_label="پیوست",
            display_order=2,
        )

        instance = self._instance()

        from workflow.repeatable_row_services import RepeatableRowService

        parent_a = RepeatableRowService.create_row(
            instance=instance,
            group=self.group,
            row_order=0,
        )
        parent_b = RepeatableRowService.create_row(
            instance=instance,
            group=self.group,
            row_order=1,
        )
        RepeatableRowService.set_value(
            row=parent_a,
            field=self.part_field,
            value="LCD",
        )
        RepeatableRowService.set_value(
            row=parent_b,
            field=self.part_field,
            value="Battery",
        )

        child_a = RepeatableRowService.create_row(
            instance=instance,
            group=child_group,
            parent_row=parent_a,
            row_order=0,
        )
        child_b = RepeatableRowService.create_row(
            instance=instance,
            group=child_group,
            parent_row=parent_b,
            row_order=0,
        )

        form_data = FormData.objects.get(instance=instance)
        FormFile.objects.create(
            form_data=form_data,
            field=child_field,
            row_id=str(child_a.pk),
            file=SimpleUploadedFile(
                "file-a.jpg",
                b"file-a-content",
                content_type="image/jpeg",
            ),
            original_name="file-a.jpg",
            file_size=13,
            content_type="image/jpeg",
            uploaded_by=self.user,
        )
        FormFile.objects.create(
            form_data=form_data,
            field=child_field,
            row_id=str(child_b.pk),
            file=SimpleUploadedFile(
                "file-b.jpg",
                b"file-b-content",
                content_type="image/jpeg",
            ),
            original_name="file-b.jpg",
            file_size=13,
            content_type="image/jpeg",
            uploaded_by=self.user,
        )

        snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=self.user,
        )

        parent_group = next(
            group
            for group in snapshot["repeatable_groups"]
            if group["code"] == self.group.code
        )

        child_groups = [
            item["child_groups"][0]
            for item in parent_group["items"]
        ]

        self.assertEqual(
            child_groups[0]["items"][0]["fields"][0]["file"],
            {
                "name": "file-a.jpg",
                "size": 13,
                "content_type": "image/jpeg",
            },
        )
        self.assertEqual(
            child_groups[1]["items"][0]["fields"][0]["file"],
            {
                "name": "file-b.jpg",
                "size": 13,
                "content_type": "image/jpeg",
            },
        )

    def test_same_device_in_two_instances_produces_independent_snapshots(self):
        configuration = HistoryConfiguration.objects.create(form=self.form)

        device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Brand",
            name="Model X",
            code="MODEL_X",
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="123456789",
        )

        device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=2,
        )
        device_field = FormField.objects.create(
            section=self.section,
            repeatable_group=device_group,
            name="IMEI",
            code="device_imei",
            label="IMEI",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.IMEI,
            order=3,
        )
        HistoryField.objects.create(
            configuration=configuration,
            form_field=device_field,
            display_label="IMEI تاریخی",
            display_order=1,
        )

        first = self._instance()
        second = self._instance()
        first_device = InstanceDevice.objects.create(
            instance=first,
            device=device,
            is_active=True,
        )
        second_device = InstanceDevice.objects.create(
            instance=second,
            device=device,
            is_active=True,
        )

        first_snapshot = HistoryService.build_snapshot(
            instance=first,
            user=self.user,
        )
        second_snapshot = HistoryService.build_snapshot(
            instance=second,
            user=self.user,
        )

        first_item = first_snapshot["repeatable_groups"][0]["items"][0]
        second_item = second_snapshot["repeatable_groups"][0]["items"][0]

        self.assertEqual(first_item["device_id"], device.pk)
        self.assertEqual(second_item["device_id"], device.pk)
        self.assertEqual(first_item["instance_device_id"], first_device.pk)
        self.assertEqual(second_item["instance_device_id"], second_device.pk)
        self.assertNotEqual(first_item["instance_device_id"], second_item["instance_device_id"])

    def test_without_active_configuration_does_not_use_legacy_history_flag(self):
        instance = self._instance(
            data={
                "problem": "Legacy problem",
                "imei": "not configured",
            }
        )

        snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=self.user,
        )

        self.assertIsNotNone(snapshot["configuration_id"])
        self.assertEqual(snapshot["fields"], [])
        self.assertEqual(snapshot["repeatable_groups"], [])

    def test_legacy_history_field_is_removed_from_form_field_model(self):
        from django.core.exceptions import FieldDoesNotExist

        with self.assertRaises(FieldDoesNotExist):
            FormField._meta.get_field("is_history_enabled")

    def test_persisted_history_snapshot_is_immutable_after_form_data_changes(self):
        configuration = HistoryConfiguration.objects.create(form=self.form)
        HistoryField.objects.create(
            configuration=configuration,
            form_field=self.problem_field,
            display_label="شرح مشکل تعمیر",
            display_order=1,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step,
            to_step=None,
            name="Finish Repair",
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=transition,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        instance = self._instance(data={"problem": "Original problem"})
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=transition,
            user=self.user,
        )
        execution = instance.step_executions.get(workflow_step=self.step)
        self.assertEqual(
            execution.data["history"]["fields"][0]["value"],
            "Original problem",
        )
        form_data = FormData.objects.get(instance=instance)
        form_data.data = {"problem": "Changed later"}
        form_data.save(update_fields=["data"])
        execution.refresh_from_db()
        self.assertEqual(
            execution.data["history"]["fields"][0]["value"],
            "Original problem",
        )

    def test_transition_persists_independent_history_for_two_repairs_of_same_device(self):
        configuration = HistoryConfiguration.objects.create(form=self.form)
        HistoryField.objects.create(
            configuration=configuration,
            form_field=self.problem_field,
            display_label="شرح مشکل تعمیر",
            display_order=1,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
        )

        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step,
            to_step=None,
            name="Finish Repair",
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=transition,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        device_type = DeviceType.objects.create(
            name="Phone E2E",
            code="PHONE_E2E",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Brand",
            name="Model E2E",
            code="MODEL_E2E",
        )
        device = Device.objects.create(device_model=device_model)
        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="987654321",
        )

        first = self._instance(data={"problem": "Broken LCD"})
        InstanceDevice.objects.create(
            instance=first,
            device=device,
            reported_problem="Broken LCD",
            is_active=True,
        )

        WorkflowExecutionService.execute_transition(
            instance=first,
            transition=transition,
            user=self.user,
        )

        first_execution = first.step_executions.get(workflow_step=self.step)
        first_history = first_execution.data["history"]
        self.assertEqual(
            first_history["fields"][0]["value"],
            "Broken LCD",
        )

        second = self._instance(data={"problem": "Battery issue"})
        InstanceDevice.objects.create(
            instance=second,
            device=device,
            reported_problem="Battery issue",
            is_active=True,
        )

        WorkflowExecutionService.execute_transition(
            instance=second,
            transition=transition,
            user=self.user,
        )

        second_execution = second.step_executions.get(workflow_step=self.step)
        second_history = second_execution.data["history"]

        self.assertEqual(
            second_history["fields"][0]["value"],
            "Battery issue",
        )

        first_execution.refresh_from_db()
        self.assertEqual(
            first_execution.data["history"]["fields"][0]["value"],
            "Broken LCD",
        )
        self.assertNotEqual(
            first_execution.data["history"]["fields"][0]["value"],
            second_history["fields"][0]["value"],
        )
