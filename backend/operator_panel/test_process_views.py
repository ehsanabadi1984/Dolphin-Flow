from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from workflow.models import Workflow, WorkflowInstance, WorkflowStep


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
                                        "items": [{"label": "Serial", "value": "SN-42"}],
                                        "children": [],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        ]
        queryset = WorkflowInstance.objects.filter(pk=self.instance.pk)

        with patch(
            "operator_panel.process_views.DashboardService.my_processes_queryset",
            return_value=queryset,
        ), patch(
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
        self.assertEqual(context_instance.process_summary, summary)\n        self.assertContains(response, "Customer")\n        self.assertContains(response, "Alice")\n        self.assertContains(response, "Devices")\n        self.assertContains(response, "Laptop")\n        self.assertContains(response, "Details")\n        self.assertContains(response, "SN-42")
