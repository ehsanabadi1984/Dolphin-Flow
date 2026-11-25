from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from workflow.models import (
    Workflow,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
)
from workflow.services import WorkflowExecutionService


User = get_user_model()


class WorkflowExecutionRolePermissionTests(TestCase):
    """Regression tests for role/user TRANSITION permission precedence."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="auth_role_exec_user",
            password="test-password",
            is_active=True,
        )
        self.workflow = Workflow.objects.create(
            name="Authorization Role Execution Test",
            code="AUTH_ROLE_EXEC_TEST",
            is_active=True,
        )
        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step One",
            code="ROLE_STEP_ONE",
            order=1,
            is_active=True,
            assigned_to=self.user,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step Two",
            code="ROLE_STEP_TWO",
            order=2,
            is_active=True,
            assigned_to=self.user,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Test Transition",
            code="ROLE_TRANSITION",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        # START and EXECUTE are prerequisites for starting and owning the
        # initial step. TRANSITION is granted independently per test.
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def _grant_role_transition(self, effect):
        return WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            transition=self.transition,
            action=WorkflowPermission.Action.TRANSITION,
            effect=effect,
        )

    def _grant_user_transition(self, effect):
        return WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            transition=self.transition,
            action=WorkflowPermission.Action.TRANSITION,
            effect=effect,
        )

    def _start_instance(self):
        return WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

    def _execute_transition(self, instance):
        return WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition,
            user=self.user,
        )

    def test_role_allow(self):
        """Role ALLOW grants permission to execute the transition."""
        self._grant_role_transition(WorkflowPermission.Effect.ALLOW)
        instance = self._start_instance()

        result = self._execute_transition(instance)

        self.assertIsNotNone(result)
        self.assertEqual(instance.current_step_id, self.step_two.pk)

    def test_user_deny_overrides_role_allow(self):
        """An explicit user DENY overrides role-based TRANSITION ALLOW."""
        self._grant_role_transition(WorkflowPermission.Effect.ALLOW)
        self._grant_user_transition(WorkflowPermission.Effect.DENY)
        instance = self._start_instance()

        with self.assertRaises(PermissionDenied):
            self._execute_transition(instance)

        instance.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_one.pk)

    def test_user_allow_overrides_role_deny(self):
        """An explicit user ALLOW overrides role-based TRANSITION DENY."""
        self._grant_role_transition(WorkflowPermission.Effect.DENY)
        self._grant_user_transition(WorkflowPermission.Effect.ALLOW)
        instance = self._start_instance()

        result = self._execute_transition(instance)

        self.assertIsNotNone(result)
        self.assertEqual(instance.current_step_id, self.step_two.pk)

    def test_no_transition_permission(self):
        """START and EXECUTE alone do not grant TRANSITION permission."""
        instance = self._start_instance()

        with self.assertRaises(PermissionDenied):
            self._execute_transition(instance)

        instance.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_one.pk)
