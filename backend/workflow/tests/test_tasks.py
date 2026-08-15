from unittest.mock import patch

from django.test import TestCase

from workflow.tasks import process_sla_monitor


class WorkflowTaskTests(TestCase):

    @patch(
        "workflow.tasks.SLAMonitorService.process_active_slas"
    )
    def test_process_sla_monitor_calls_monitor_service(
        self,
        mock_process,
    ):
        mock_process.return_value = {
            "warning_count": 2,
            "breach_count": 1,
        }

        result = process_sla_monitor.run()

        mock_process.assert_called_once_with()

        self.assertEqual(
            result,
            {
                "warning_count": 2,
                "breach_count": 1,
            },
        )