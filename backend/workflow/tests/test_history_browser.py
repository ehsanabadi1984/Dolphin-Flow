from django.test import TestCase

from accounts.models import User
from workflow.history_browser_service import HistoryBrowserService
from workflow.history_permissions import HISTORY_ACTION
from workflow.models import (
    Device,
    DeviceModel,
    DeviceType,
    InstanceDevice,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
)


class HistoryBrowserServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="history-browser-user",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="History Browser Workflow",
            code="HISTORY_BROWSER",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Repair",
            code="REPAIR",
            order=1,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
        )

    def _execution(self, snapshot):
        return WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
            is_submitted=True,
            data={"history": snapshot},
        )

    def test_history_permission_is_independent_from_view(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self._execution({"version": 1, "fields": [], "repeatable_groups": []})

        self.assertEqual(
            HistoryBrowserService.get_history(
                user=self.user,
                instance_id=self.instance.pk,
            ),
            [],
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.assertEqual(
            len(
                HistoryBrowserService.get_history(
                    user=self.user,
                    instance_id=self.instance.pk,
                )
            ),
            1,
        )

    def test_device_filter_keeps_complete_top_level_history(self):
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
        InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
            is_active=True,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self._execution(
            {
                "version": 1,
                "fields": [
                    {
                        "code": "customer",
                        "label": "Customer",
                        "display_label": "Customer",
                        "value": "Ehsan",
                        "display_value": "Ehsan",
                    }
                ],
                "repeatable_groups": [
                    {
                        "code": "devices",
                        "name": "Devices",
                        "items": [
                            {
                                "device_id": device.pk,
                                "instance_device_id": 1,
                                "fields": [],
                            },
                            {
                                "device_id": 999999,
                                "instance_device_id": 2,
                                "fields": [],
                            },
                        ],
                    }
                ],
            }
        )

        history = HistoryBrowserService.get_history(
            user=self.user,
            device_id=device.pk,
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(
            history[0]["snapshot"]["fields"][0]["value"],
            "Ehsan",
        )
        self.assertEqual(
            history[0]["snapshot"]["repeatable_groups"][0]["items"][0]["device_id"],
            device.pk,
        )
