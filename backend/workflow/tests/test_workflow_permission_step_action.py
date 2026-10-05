from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    Workflow,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
)


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
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
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

    def test_authorization_distinguishes_accept_and_reject(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
        )

        self.assertTrue(
            WorkflowAuthorizationService.has_permission(
                user=self.user,
                workflow=self.workflow,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="ACCEPT",
                step=self.step,
            )
        )
        self.assertFalse(
            WorkflowAuthorizationService.has_permission(
                user=self.user,
                workflow=self.workflow,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="REJECT",
                step=self.step,
            )
        )

    def test_step_action_requires_action_code_at_runtime(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
        )

        self.assertFalse(
            WorkflowAuthorizationService.has_permission(
                user=self.user,
                workflow=self.workflow,
                action=WorkflowPermission.Action.STEP_ACTION,
                step=self.step,
            )
        )

    def test_require_permission_passes_action_code(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
        )

        self.assertTrue(
            WorkflowAuthorizationService.require_permission(
                user=self.user,
                workflow=self.workflow,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="ACCEPT",
                step=self.step,
            )
        )

    def test_custom_permission_action_without_action_code_remains_supported(self):
        permission = WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action="HISTORY",
        )

        self.assertEqual(permission.action, "HISTORY")
        self.assertIsNone(permission.action_code)

    def test_recipient_resolver_uses_role_allow(self):
        role_user = get_user_model().objects.create_user(
            username="role-allow-user",
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=role_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.ALLOW,
        )

        users = WorkflowAuthorizationService.get_users_with_step_action_permission(
            workflow=self.workflow,
            step=self.step,
            action_code="ACCEPT",
        )

        self.assertEqual({user.pk for user in users}, {role_user.pk})

    def test_recipient_resolver_user_deny_overrides_role_allow(self):
        role_user = get_user_model().objects.create_user(
            username="role-allow-denied-user",
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=role_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=role_user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.DENY,
        )

        users = WorkflowAuthorizationService.get_users_with_step_action_permission(
            workflow=self.workflow,
            step=self.step,
            action_code="ACCEPT",
        )

        self.assertNotIn(role_user.pk, {user.pk for user in users})

    def test_recipient_resolver_user_allow_overrides_role_deny(self):
        role_denied_user = get_user_model().objects.create_user(
            username="role-deny-user",
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=role_denied_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.DENY,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=role_denied_user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.ALLOW,
        )

        users = WorkflowAuthorizationService.get_users_with_step_action_permission(
            workflow=self.workflow,
            step=self.step,
            action_code="ACCEPT",
        )

        self.assertIn(role_denied_user.pk, {user.pk for user in users})

    def test_recipient_resolver_excludes_inactive_membership_and_user(self):
        inactive_membership_user = get_user_model().objects.create_user(
            username="inactive-membership-user",
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=inactive_membership_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=False,
        )

        inactive_user = get_user_model().objects.create_user(
            username="inactive-user",
            is_active=False,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=inactive_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.ALLOW,
        )

        users = WorkflowAuthorizationService.get_users_with_step_action_permission(
            workflow=self.workflow,
            step=self.step,
            action_code="ACCEPT",
        )

        user_ids = {user.pk for user in users}
        self.assertNotIn(inactive_membership_user.pk, user_ids)
        self.assertNotIn(inactive_user.pk, user_ids)
