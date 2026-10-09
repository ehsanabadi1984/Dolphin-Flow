from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone
from django.urls import reverse

from workflow.models import (
    FormData,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
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

    def test_my_processes_invalid_form_date_does_not_raise_server_error(self):
        client = Client()
        client.force_login(self.user)

        response = client.get(
            reverse("operator_panel:my_processes"),
            {"q": f"{self.instance.pk}-991399"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
