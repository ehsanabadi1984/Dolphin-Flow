from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from workflow.models import Workflow, WorkflowPermission, WorkflowStep


class WorkflowPermissionStepActionTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Step Action Permission Test",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Destination",
            order=1,
        )
        self.user = get_user_model().objects.create_user(
            username="step-action-user",
        )

    def test_step_action_requires_action_code(self):
        with self.assertRaises(IntegrityError):
            WorkflowPermission.objects.create(
                workflow=self.workflow,
                step=self.step,
                user=self.user,
                action=WorkflowPermission.Action.STEP_ACTION,
            )

    def test_regular_action_cannot_have_action_code(self):
        with self.assertRaises(IntegrityError):
            WorkflowPermission.objects.create(
                workflow=self.workflow,
                step=self.step,
                user=self.user,
                action=WorkflowPermission.Action.VIEW,
                action_code="ACCEPT",
            )

    def test_step_action_accept_and_reject_are_supported(self):
        accept = WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
        )
        reject = WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="REJECT",
        )

        self.assertEqual(accept.action, WorkflowPermission.Action.STEP_ACTION)
        self.assertEqual(accept.action_code, "ACCEPT")
        self.assertEqual(reject.action_code, "REJECT")

    def test_existing_permission_contract_remains_unchanged(self):
        permission = WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
        )

        self.assertIsNone(permission.action_code)

    def test_custom_permission_action_without_action_code_remains_supported(self):
        permission = WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action="HISTORY",
        )

        self.assertEqual(permission.action, "HISTORY")
        self.assertIsNone(permission.action_code)
