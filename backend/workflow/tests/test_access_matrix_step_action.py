from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.access_matrix import save_access_matrix
from workflow.access_workspace import _matrix_context
from workflow.models import Workflow, WorkflowMembership, WorkflowPermission, WorkflowStep, WorkflowTransition


class AcceptanceAccessMatrixTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Acceptance Access Matrix Test",
        )
        self.source = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Source",
            order=1,
        )
        self.destination = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Destination",
            order=2,
        )
        self.user = get_user_model().objects.create_user(
            username="acceptance-matrix-user",
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.source,
            to_step=self.destination,
            name="Deliver",
            requires_acceptance=True,
        )

    def test_accept_and_reject_are_saved_separately_for_destination_step(self):
        save_access_matrix(
            workflow=self.workflow,
            subject_type="user",
            subject_value=self.user.pk,
            step=self.destination,
            post_data={"step_action_ACCEPT": "1"},
        )

        self.assertTrue(
            WorkflowPermission.objects.filter(
                workflow=self.workflow,
                user=self.user,
                step=self.destination,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="ACCEPT",
                effect=WorkflowPermission.Effect.ALLOW,
            ).exists()
        )
        self.assertFalse(
            WorkflowPermission.objects.filter(
                workflow=self.workflow,
                user=self.user,
                step=self.destination,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="REJECT",
            ).exists()
        )

        save_access_matrix(
            workflow=self.workflow,
            subject_type="user",
            subject_value=self.user.pk,
            step=self.destination,
            post_data={"step_action_REJECT": "1"},
        )

        self.assertFalse(
            WorkflowPermission.objects.filter(
                workflow=self.workflow,
                user=self.user,
                step=self.destination,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="ACCEPT",
            ).exists()
        )
        self.assertTrue(
            WorkflowPermission.objects.filter(
                workflow=self.workflow,
                user=self.user,
                step=self.destination,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="REJECT",
                effect=WorkflowPermission.Effect.ALLOW,
            ).exists()
        )

    def test_step_action_permissions_are_not_available_without_acceptance_transition(self):
        self.transition.requires_acceptance = False
        self.transition.save(update_fields=["requires_acceptance"])

        save_access_matrix(
            workflow=self.workflow,
            subject_type="user",
            subject_value=self.user.pk,
            step=self.destination,
            post_data={"step_action_ACCEPT": "1", "step_action_REJECT": "1"},
        )

        self.assertFalse(
            WorkflowPermission.objects.filter(
                workflow=self.workflow,
                user=self.user,
                step=self.destination,
                action=WorkflowPermission.Action.STEP_ACTION,
            ).exists()
        )

    def test_workspace_reads_acceptance_action_permissions(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            step=self.destination,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.ALLOW,
        )

        matrix = _matrix_context(
            self.workflow,
            "user",
            str(self.user.pk),
            self.destination,
            role=WorkflowMembership.Role.EXECUTOR,
        )

        self.assertTrue(matrix["step_action_enabled"])
        self.assertEqual(
            {row["value"]: row["enabled"] for row in matrix["step_action_rows"]},
            {"ACCEPT": True, "REJECT": False},
        )
