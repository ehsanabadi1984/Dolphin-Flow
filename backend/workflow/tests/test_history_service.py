from django.test import TestCase

from accounts.models import User

from workflow.authorization import WorkflowAuthorizationService
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
            is_history_enabled=False,
            order=0,
        )
        self.problem_field = FormField.objects.create(
            section=self.section,
            name="Problem",
            code="problem",
            label="Problem",
            field_type=FormField.FieldType.TEXT,
            is_history_enabled=True,
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

        instance = self._instance(
            data={
                "parts": [
                    {"_id": "row-1", "part_name": "LCD"},
                    {"_id": "row-2", "part_name": "Battery"},
                ]
            }
        )

        snapshot = HistoryService.build_snapshot(
            instance=instance,
            user=self.user,
        )

        items = snapshot["repeatable_groups"][0]["items"]
        self.assertEqual([item["row_id"] for item in items], ["row-1", "row-2"])
        self.assertEqual(items[0]["fields"][0]["value"], "LCD")
        self.assertEqual(items[1]["fields"][0]["value"], "Battery")

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

    def test_without_active_configuration_legacy_history_flag_remains_compatible(self):
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

        self.assertIsNone(snapshot["configuration_id"])
        self.assertEqual(
            [field["code"] for field in snapshot["fields"]],
            ["problem"],
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
        self.assertEqual(
            first_execution.refresh_from_db() or first_execution.data["history"]["fields"][0]["value"],
            "Broken LCD",
        )
        self.assertNotEqual(
            first_execution.data["history"]["fields"][0]["value"],
            second_history["fields"][0]["value"],
        )
