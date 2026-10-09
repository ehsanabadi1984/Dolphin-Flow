from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone
from django.urls import reverse

from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    RepeatableRow,
    RepeatableRowValue,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)


User = get_user_model()


class MyProcessesSummaryWiringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="my_processes_summary_user",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="Summary WF",
            code="SUMMARY_WF",
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Summary Step",
            code="SUMMARY_STEP",
            order=1,
            is_active=True,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
            status=WorkflowInstance.Status.ACTIVE,
        )
        FormData.objects.create(
            instance=self.instance,
            data={"note": "summary"},
        )

    def test_my_processes_attaches_batch_summary_to_page_instances(self):
        client = Client()
        client.force_login(self.user)
        summary = [
            {"label": "Customer", "value": "Alice"},
            {
                "group_label": "Devices",
                "rows": [
                    {
                        "items": [{"label": "Model", "value": "Laptop"}],
                        "children": [
                            {
                                "group_label": "Details",
                                "rows": [
                                    {
                                        "items": [
                                            {"label": "Serial", "value": "SN-42"}
                                        ],
                                        "children": [],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        ]

        with patch(
            "operator_panel.process_views.ProcessSummaryService.get_for_instances",
            return_value={self.instance.pk: summary},
        ) as get_summaries:
            response = client.get(reverse("operator_panel:my_processes"))

        self.assertEqual(response.status_code, 200)
        get_summaries.assert_called_once_with(
            instances=[self.instance],
            user=self.user,
        )

        context_instance = response.context["instances"][0]
        self.assertEqual(context_instance.pk, self.instance.pk)
        self.assertEqual(context_instance.process_summary, summary)
        self.assertContains(response, "Customer")
        self.assertContains(response, "Alice")
        self.assertContains(response, "Devices")
        self.assertContains(response, "Laptop")
        self.assertContains(response, "Details")
        self.assertContains(response, "SN-42")
        self.assertContains(response, '<select id="process-workflow" name="workflow">')
        self.assertContains(response, "</select>")
        self.assertContains(response, '<div class="df-process-row">')
        self.assertContains(response, "Summary WF")

    def test_my_processes_searches_by_unpadded_id_then_date(self):
        client = Client()
        client.force_login(self.user)
        form_date = timezone.localtime(self.instance.started_at).strftime("%y%m%d")

        response = client.get(
            reverse("operator_panel:my_processes"),
            {"q": f"{self.instance.pk}-{form_date}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(
            response,
            f"شماره فرم: {self.instance.pk}-{form_date}",
        )

        # The search box should accept the date-first order users type naturally,
        # with an unpadded instance ID after the hyphen.
        date_first_response = client.get(
            reverse("operator_panel:my_processes"),
            {"q": f"{form_date}-{self.instance.pk}"},
        )
        self.assertEqual(date_first_response.status_code, 200)
        self.assertEqual(date_first_response.context["page_obj"].paginator.count, 1)

        # Keep accepting the old zero-padded date-first form number too.
        legacy_response = client.get(
            reverse("operator_panel:my_processes"),
            {"q": f"{form_date}-{self.instance.pk:06d}"},
        )
        self.assertEqual(legacy_response.status_code, 200)
        self.assertEqual(legacy_response.context["page_obj"].paginator.count, 1)

    def test_my_processes_invalid_form_date_does_not_raise_server_error(self):
        client = Client()
        client.force_login(self.user)

        response = client.get(
            reverse("operator_panel:my_processes"),
            {"q": f"{self.instance.pk}-991399"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 0)


class MyProcessesFormSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="my_processes_form_search_user",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="Form Search WF",
            code="FORM_SEARCH_WF",
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Form Search Step",
            code="FORM_SEARCH_STEP",
            order=1,
            is_active=True,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
            status=WorkflowInstance.Status.ACTIVE,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Searchable Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Main",
            code="SEARCH_MAIN",
            order=1,
        )
        self.other_instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
            status=WorkflowInstance.Status.ACTIVE,
        )
        FormData.objects.create(
            instance=self.instance,
            data={"customer": "Customer-Blue-193"},
        )
        FormData.objects.create(instance=self.other_instance, data={})

    def search_count(self, term):
        client = Client()
        client.force_login(self.user)
        response = client.get(
            reverse("operator_panel:my_processes"),
            {"q": term},
        )
        self.assertEqual(response.status_code, 200)
        return response.context["page_obj"].paginator.count

    def test_search_uses_operator_step_permissions_after_process_moves_on(self):
        other_user = User.objects.create_user(
            username="later_step_operator",
            password="test-password",
        )
        later_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Later Step",
            code="LATER_SEARCH_STEP",
            assigned_to=other_user,
            order=2,
            is_active=True,
        )
        customer_field = FormField.objects.create(
            section=self.section,
            name="Customer",
            code="customer",
            label="Customer",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        # The value was visible to this operator at their step, but hidden
        # at the later step now assigned to somebody else.
        FieldAccess.objects.create(
            field=customer_field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=customer_field,
            step=later_step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=False,
            can_edit=False,
        )
        self.instance.current_step = later_step
        self.instance.save(update_fields=["current_step"])
        WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
            is_submitted=True,
        )

        self.assertEqual(self.search_count("Customer-Blue-193"), 1)

    def test_searches_normal_nested_and_device_fields_but_not_hidden_fields(self):
        FormField.objects.create(
            section=self.section,
            name="Customer",
            code="customer",
            label="Customer",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )

        parent_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Assets",
            label="Assets",
            code="assets",
            order=1,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent_group,
            name="Asset details",
            label="Asset details",
            code="asset_details",
            order=2,
        )
        nested_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Serial",
            code="serial",
            label="Serial",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent_group,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child_group,
            parent_row=parent_row,
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=nested_field,
            text_value="nested-serial-X91",
        )

        device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            label="Devices",
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=3,
        )
        device_description = FormField.objects.create(
            section=self.section,
            repeatable_group=device_group,
            name="Description",
            code="device_description",
            label="Device description",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.DESCRIPTION,
            order=1,
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            description="device-problem-Z77",
        )
        RepeatableRow.objects.create(
            instance=self.instance,
            group=device_group,
            instance_device=instance_device,
        )

        hidden_field = FormField.objects.create(
            section=self.section,
            name="Private note",
            code="private_note",
            label="Private note",
            field_type=FormField.FieldType.TEXT,
            order=2,
        )
        FieldAccess.objects.create(
            field=hidden_field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=False,
            can_edit=False,
        )
        FormData.objects.filter(instance=self.instance).update(
            data={
                "customer": "Customer-Blue-193",
                "private_note": "hidden-SECRET-55",
            }
        )

        self.assertEqual(self.search_count("Customer-Blue-193"), 1)
        self.assertEqual(self.search_count("nested-serial-X91"), 1)
        self.assertEqual(self.search_count("device-problem-Z77"), 1)
        self.assertEqual(self.search_count("hidden-SECRET-55"), 0)
