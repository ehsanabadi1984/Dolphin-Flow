from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from workflow.form_file_models import FormFile
from workflow.history_models import HistoryConfiguration, HistoryField
from workflow.models import (
    BusinessCalendar,
    Device,
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
    LookupItem,
    LookupList,
    Notification,
    RepeatableGroupAccess,
    RepeatableRow,
    RepeatableRowValue,
    StaticChoiceItem,
    StaticChoiceSet,
    WeeklySchedule,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowStepSLA,
    WorkflowTransition,
    WorkflowTransitionExecution,
)


class ResetWorkflowDataCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reset-owner",
            password="password",
        )
        self.workflow = Workflow.objects.create(
            name="Reset Workflow",
            code="RESET-WF",
        )
        self.step1 = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step 1",
            order=1,
        )
        self.step2 = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step 2",
            order=2,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step1,
            to_step=self.step2,
            name="Next",
            code="NEXT",
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step1,
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.device_type = DeviceType.objects.create(
            name="Laptop",
            code="LAPTOP",
        )
        self.device_model = DeviceModel.objects.create(
            device_type=self.device_type,
            brand="Test",
            name="Model",
            code="MODEL",
        )
        self.device = Device.objects.create(device_model=self.device_model)
        self.identifier = DeviceIdentifier.objects.create(
            device=self.device,
            identifier_type=DeviceIdentifier.IdentifierType.SERIAL_NUMBER,
            value="RESET-001",
        )

        self.static_set = StaticChoiceSet.objects.create(
            name="Static",
            code="STATIC-RESET",
        )
        self.static_item = StaticChoiceItem.objects.create(
            choice_set=self.static_set,
            value="A",
            label="A",
        )
        self.lookup_list = LookupList.objects.create(
            name="Lookup",
            code="LOOKUP-RESET",
        )
        self.lookup_item = LookupItem.objects.create(
            lookup_list=self.lookup_list,
            value="A",
            label="A",
        )

        self.calendar = BusinessCalendar.objects.create(
            name="Reset Calendar",
        )
        self.weekday = WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=0,
            is_working=True,
        )
        WorkflowStepSLA.objects.create(
            step=self.step1,
            calendar=self.calendar,
            duration="01:00:00",
        )

        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Reset Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Section",
            code="SECTION",
        )
        self.parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parent Group",
            code="PARENT",
        )
        self.child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.parent_group,
            name="Child Group",
            code="CHILD",
            order=1,
        )

        self.parent_field = FormField.objects.create(
            section=self.section,
            name="Parent",
            code="PARENT-FIELD",
            label="Parent",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=self.lookup_list,
        )
        self.child_field = FormField.objects.create(
            section=self.section,
            name="Child",
            code="CHILD-FIELD",
            label="Child",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=self.lookup_list,
            choice_parent_field=self.parent_field,
            order=1,
        )

        self.repeatable_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.child_group,
            name="Repeatable",
            code="REPEATABLE-FIELD",
            label="Repeatable",
            order=0,
        )

        FieldAccess.objects.create(
            field=self.child_field,
            step=self.step1,
            user=self.user,
        )
        RepeatableGroupAccess.objects.create(
            group=self.child_group,
            step=self.step1,
            user=self.user,
        )

        self.history_config = HistoryConfiguration.objects.create(
            form=self.form,
            name="Reset History",
        )
        HistoryField.objects.create(
            configuration=self.history_config,
            form_field=self.child_field,
        )

        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step1,
            started_by=self.user,
        )
        self.instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            device=self.device,
        )
        self.form_data = FormData.objects.create(
            instance=self.instance,
            data={"Child": "A"},
        )

        self.parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.parent_group,
            row_order=0,
        )
        self.child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=self.child_group,
            parent_row=self.parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=self.child_row,
            field=self.repeatable_field,
            text_value="runtime",
        )

        self.step_execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step1,
            performed_by=self.user,
            data={"history": {"fields": {"Child": "A"}}},
        )
        self.transition_execution = WorkflowTransitionExecution.objects.create(
            instance=self.instance,
            transition=self.transition,
            performed_by=self.user,
        )
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.STEP_ENTERED,
            title="Reset",
            message="Reset",
            workflow_instance=self.instance,
            workflow_step=self.step1,
        )

    def test_dry_run_changes_nothing(self):
        before = {
            "workflow": Workflow.objects.count(),
            "membership": WorkflowMembership.objects.count(),
            "form": FormDefinition.objects.count(),
            "instance": WorkflowInstance.objects.count(),
            "static": StaticChoiceSet.objects.count(),
            "lookup": LookupList.objects.count(),
            "calendar": BusinessCalendar.objects.count(),
        }

        output = StringIO()
        call_command("reset_workflow_data", "--dry-run", stdout=output)

        after = {
            "workflow": Workflow.objects.count(),
            "membership": WorkflowMembership.objects.count(),
            "form": FormDefinition.objects.count(),
            "instance": WorkflowInstance.objects.count(),
            "static": StaticChoiceSet.objects.count(),
            "lookup": LookupList.objects.count(),
            "calendar": BusinessCalendar.objects.count(),
        }

        self.assertEqual(before, after)
        self.assertIn("DRY RUN", output.getvalue())

    def test_reset_deletes_forms_and_runtime_but_preserves_configuration(self):
        output = StringIO()
        call_command("reset_workflow_data", "--yes", stdout=output)

        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertTrue(Workflow.objects.filter(pk=self.workflow.pk).exists())
        self.assertTrue(WorkflowMembership.objects.filter(
            pk=self.workflow.memberships.get(user=self.user).pk
        ).exists())
        self.assertTrue(WorkflowStep.objects.filter(pk=self.step1.pk).exists())
        self.assertTrue(WorkflowStep.objects.filter(pk=self.step2.pk).exists())
        self.assertTrue(WorkflowTransition.objects.filter(pk=self.transition.pk).exists())
        self.assertTrue(WorkflowPermission.objects.filter(workflow=self.workflow).exists())

        self.assertTrue(DeviceType.objects.filter(pk=self.device_type.pk).exists())
        self.assertTrue(DeviceModel.objects.filter(pk=self.device_model.pk).exists())
        self.assertTrue(Device.objects.filter(pk=self.device.pk).exists())
        self.assertTrue(DeviceIdentifier.objects.filter(pk=self.identifier.pk).exists())

        self.assertTrue(StaticChoiceSet.objects.filter(pk=self.static_set.pk).exists())
        self.assertTrue(StaticChoiceItem.objects.filter(pk=self.static_item.pk).exists())
        self.assertTrue(LookupList.objects.filter(pk=self.lookup_list.pk).exists())
        self.assertTrue(LookupItem.objects.filter(pk=self.lookup_item.pk).exists())

        self.assertTrue(BusinessCalendar.objects.filter(pk=self.calendar.pk).exists())
        self.assertTrue(WeeklySchedule.objects.filter(pk=self.weekday.pk).exists())
        self.assertTrue(WorkflowStepSLA.objects.filter(step=self.step1).exists())

        self.assertEqual(FormDefinition.objects.count(), 0)
        self.assertEqual(FormSection.objects.count(), 0)
        self.assertEqual(FormField.objects.count(), 0)
        self.assertEqual(FormRepeatableGroup.objects.count(), 0)
        self.assertEqual(FieldAccess.objects.count(), 0)
        self.assertEqual(RepeatableGroupAccess.objects.count(), 0)
        self.assertEqual(HistoryConfiguration.objects.count(), 0)
        self.assertEqual(HistoryField.objects.count(), 0)

        self.assertEqual(WorkflowInstance.objects.count(), 0)
        self.assertEqual(FormData.objects.count(), 0)
        self.assertEqual(InstanceDevice.objects.count(), 0)
        self.assertEqual(RepeatableRow.objects.count(), 0)
        self.assertEqual(RepeatableRowValue.objects.count(), 0)
        self.assertEqual(WorkflowStepExecution.objects.count(), 0)
        self.assertEqual(WorkflowTransitionExecution.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(FormFile.objects.count(), 0)

        self.assertIn("Workflow data reset completed.", output.getvalue())
