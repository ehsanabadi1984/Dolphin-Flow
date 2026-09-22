from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
)
from operator_panel.dashboard_services import DashboardService


User = get_user_model()


class DashboardPermissionContractTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="dashboard_permission_user",
            password="test-password",
        )
        self.other_user = User.objects.create_user(
            username="dashboard_permission_other",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Dashboard Permission Test",
            code="DASHBOARD_PERMISSION_TEST",
            is_active=True,
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Dashboard Step",
            code="DASHBOARD_PERMISSION_STEP",
            order=1,
            is_active=True,
            assigned_to=self.user,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.other_user,
            status=WorkflowInstance.Status.ACTIVE,
        )

    def add_permission(self, *, action, effect, user=None, role=None):
        return WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=user,
            role=role,
            action=action,
            effect=effect,
        )

    def grant_view(self):
        self.add_permission(
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
            user=self.user,
        )

    def grant_execute(self):
        self.add_permission(
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
            user=self.user,
        )

    def accessible_ids(self):
        return set(
            DashboardService(self.user)
            ._accessible_active_queryset()
            .values_list("pk", flat=True)
        )

    def actionable_ids(self):
        return {
            item.pk
            for item in DashboardService(self.user)._pending_instances(
                assigned_only=True,
            )
        }

    def test_membership_alone_does_not_grant_dashboard_view(self):
        self.assertNotIn(self.instance.pk, self.accessible_ids())

    def test_view_permission_makes_instance_visible_but_not_actionable(self):
        self.grant_view()

        self.assertIn(self.instance.pk, self.accessible_ids())
        self.assertNotIn(self.instance.pk, self.actionable_ids())

    def test_execute_without_view_does_not_make_instance_actionable(self):
        self.grant_execute()

        self.assertNotIn(self.instance.pk, self.accessible_ids())
        self.assertNotIn(self.instance.pk, self.actionable_ids())

    def test_view_and_execute_make_instance_actionable(self):
        self.grant_view()
        self.grant_execute()

        self.assertIn(self.instance.pk, self.accessible_ids())
        self.assertIn(self.instance.pk, self.actionable_ids())

    def test_explicit_view_deny_overrides_role_view_allow(self):
        self.add_permission(
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        self.add_permission(
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.DENY,
            user=self.user,
        )

        self.assertNotIn(self.instance.pk, self.accessible_ids())

    def test_explicit_user_view_allow_overrides_role_view_deny(self):
        self.add_permission(
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.DENY,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        self.add_permission(
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
            user=self.user,
        )

        self.assertIn(self.instance.pk, self.accessible_ids())

    def test_owner_has_implicit_view_but_explicit_deny_still_blocks_it(self):
        self.instance.started_by = self.user
        self.instance.save(update_fields=["started_by"])

        self.assertIn(self.instance.pk, self.accessible_ids())

        self.add_permission(
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.DENY,
            user=self.user,
        )

        self.assertNotIn(self.instance.pk, self.accessible_ids())
