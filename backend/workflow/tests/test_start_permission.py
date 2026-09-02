from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase, Client

from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
)
from workflow.services import WorkflowExecutionService


User = get_user_model()


class StartPermissionBaseTestCase(TestCase):
    """Shared fixtures for START permission tests."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="start_perm_user",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Start Permission Test Workflow",
            code="START_PERM_TEST",
            is_active=True,
        )

        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step One",
            code="START_STEP_ONE",
            order=1,
            is_active=True,
        )

        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step Two",
            code="START_STEP_TWO",
            order=2,
            is_active=True,
        )

        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Transition One",
            code="START_TRANS_ONE",
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


class StartPermissionServiceTests(StartPermissionBaseTestCase):
    """Test start_workflow authorization using START permission."""

    def test_user_with_start_can_start_workflow(self):
        """User with START permission can start a workflow."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        self.assertIsNotNone(instance)
        self.assertEqual(instance.workflow, self.workflow)
        self.assertEqual(instance.started_by, self.user)
        self.assertEqual(instance.status, WorkflowInstance.Status.ACTIVE)

    def test_user_without_start_cannot_start_workflow(self):
        """User without START permission cannot start a workflow."""
        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.start_workflow(
                workflow=self.workflow,
                user=self.user,
            )

    def test_view_without_start_cannot_start_workflow(self):
        """VIEW without START must NOT allow starting a workflow."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.start_workflow(
                workflow=self.workflow,
                user=self.user,
            )

    def test_execute_without_start_cannot_start_workflow(self):
        """EXECUTE without START must NOT allow starting a workflow."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.start_workflow(
                workflow=self.workflow,
                user=self.user,
            )

    def test_start_without_view_can_start_workflow(self):
        """START without VIEW must allow starting a workflow."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        # No VIEW permission granted.
        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        self.assertIsNotNone(instance)
        self.assertEqual(instance.workflow, self.workflow)

    def test_start_does_not_grant_execute(self):
        """START must not automatically grant permission to execute transitions."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition,
                user=self.user,
            )

    def test_role_based_start_permission(self):
        """START permission via role membership works."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        self.assertIsNotNone(instance)
        self.assertEqual(instance.workflow, self.workflow)

    def test_user_deny_overrides_role_start_allow(self):
        """Explicit user DENY overrides role-based START ALLOW."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.DENY,
        )

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.start_workflow(
                workflow=self.workflow,
                user=self.user,
            )

    def test_inactive_workflow_cannot_be_started(self):
        """An inactive workflow cannot be started regardless of permission."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.workflow.is_active = False
        self.workflow.save(update_fields=["is_active"])

        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            WorkflowExecutionService.start_workflow(
                workflow=self.workflow,
                user=self.user,
            )


class StartPermissionDashboardTests(StartPermissionBaseTestCase):
    """Test that the dashboard only shows startable workflows."""

    def test_user_with_start_sees_workflow_in_dashboard(self):
        """User with START permission sees the workflow in startable list."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        startable = WorkflowAuthorizationService.get_startable_workflows(
            user=self.user,
        )

        self.assertIn(self.workflow, startable)

    def test_user_without_start_does_not_see_workflow(self):
        """User without START permission does not see the workflow."""
        startable = WorkflowAuthorizationService.get_startable_workflows(
            user=self.user,
        )

        self.assertNotIn(self.workflow, startable)

    def test_user_with_start_only_sees_authorized_workflows(self):
        """User with START on workflow A but not B only sees A."""
        workflow_b = Workflow.objects.create(
            name="Workflow B",
            code="START_PERM_TEST_B",
            is_active=True,
        )

        WorkflowStep.objects.create(
            workflow=workflow_b,
            name="Step B1",
            order=1,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=workflow_b,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        # Grant START only for workflow A (self.workflow).
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        startable = WorkflowAuthorizationService.get_startable_workflows(
            user=self.user,
        )

        self.assertIn(self.workflow, startable)
        self.assertNotIn(workflow_b, startable)

    def test_anonymous_user_gets_empty_queryset(self):
        """An anonymous user gets an empty queryset."""
        from django.contrib.auth.models import AnonymousUser

        startable = WorkflowAuthorizationService.get_startable_workflows(
            user=AnonymousUser(),
        )

        self.assertEqual(startable.count(), 0)

    def test_inactive_workflow_not_shown(self):
        """An inactive workflow is not shown even with START permission."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.workflow.is_active = False
        self.workflow.save(update_fields=["is_active"])

        startable = WorkflowAuthorizationService.get_startable_workflows(
            user=self.user,
        )

        self.assertNotIn(self.workflow, startable)


class StartPermissionEndpointTests(StartPermissionBaseTestCase):
    """Test that the start endpoint enforces START permission."""

    def test_direct_post_without_start_permission_is_denied(self):
        """Direct POST to start endpoint without START permission returns 403."""
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)

        response = client.post(
            f"/operator/workflow/{self.workflow.pk}/start/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 403)

    def test_direct_post_with_start_permission_succeeds(self):
        """Direct POST to start endpoint with START permission succeeds."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)

        response = client.post(
            f"/operator/workflow/{self.workflow.pk}/start/",
            HTTP_HOST="localhost",
        )

        # Should redirect to the workflow instance page.
        self.assertEqual(response.status_code, 302)

        # Verify the instance was created.
        self.assertTrue(
            WorkflowInstance.objects.filter(
                workflow=self.workflow,
                started_by=self.user,
            ).exists()
        )

    def test_get_to_start_endpoint_redirects_to_dashboard(self):
        """GET to start endpoint redirects to dashboard."""
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)

        response = client.get(
            f"/operator/workflow/{self.workflow.pk}/start/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 302)

    def test_dashboard_only_shows_startable_workflows(self):
        """Dashboard page only shows workflows user can start."""
        workflow_b = Workflow.objects.create(
            name="Workflow B Startable",
            code="START_DASH_TEST_B",
            is_active=True,
        )

        WorkflowStep.objects.create(
            workflow=workflow_b,
            name="Step B1",
            order=1,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=workflow_b,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        # Grant START only for workflow B.
        WorkflowPermission.objects.create(
            workflow=workflow_b,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)

        response = client.get(
            "/operator/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)

        content = response.content.decode()

        # Workflow B should appear (has START permission).
        self.assertIn(workflow_b.name, content)

        # Workflow A should NOT appear (no START permission).
        self.assertNotIn(self.workflow.name, content)


class ImplicitViewPermissionTests(StartPermissionBaseTestCase):
    """Test implicit VIEW permission for the user who started
    a WorkflowInstance (via START permission).
    """

    def test_start_without_view_can_view_own_instance(self):
        """START without VIEW: user can start and view their
        newly created instance.
        """
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        # The starter should be able to VIEW their own instance.
        allowed = WorkflowAuthorizationService.has_permission(
            user=self.user,
            workflow=self.workflow,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            instance=instance,
        )

        self.assertTrue(allowed)

    def test_start_without_view_cannot_view_other_instances(self):
        """START without VIEW: user cannot view another user's
        instance of the same workflow.
        """
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        other_user = User.objects.create_user(
            username="other_instance_user",
            password="test-password",
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=other_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=other_user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        # Other user starts an instance.
        other_instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=other_user,
        )

        # Our user (with only START) should NOT be able to
        # view the other user's instance.
        allowed = WorkflowAuthorizationService.has_permission(
            user=self.user,
            workflow=self.workflow,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            instance=other_instance,
        )

        self.assertFalse(allowed)

    def test_view_without_start_cannot_start_workflow(self):
        """VIEW without START: user cannot start a workflow."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.start_workflow(
                workflow=self.workflow,
                user=self.user,
            )

    def test_start_without_execute_can_start_but_not_transition(self):
        """START without EXECUTE: user can start and view their
        own instance but cannot execute a transition.
        """
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        # Can view own instance (implicit).
        allowed_view = WorkflowAuthorizationService.has_permission(
            user=self.user,
            workflow=self.workflow,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            instance=instance,
        )
        self.assertTrue(allowed_view)

        # Cannot execute transition without explicit permission.
        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition,
                user=self.user,
            )

    def test_explicit_view_permission_still_works(self):
        """Explicit VIEW permission continues to work as before."""
        # Grant step-level VIEW so the check with step=step_one
        # matches the explicit permission.
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            step=self.step_one,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        # User with explicit VIEW can access instances they
        # did NOT start.
        other_user = User.objects.create_user(
            username="explicit_view_other",
            password="test-password",
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=other_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=other_user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        other_instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=other_user,
        )

        # Our user with explicit VIEW should see it.
        allowed = WorkflowAuthorizationService.has_permission(
            user=self.user,
            workflow=self.workflow,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            instance=other_instance,
        )

        self.assertTrue(allowed)

    def test_explicit_deny_overrides_implicit_view(self):
        """Explicit DENY overrides the implicit VIEW grant."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        # Explicitly deny VIEW at the step level so the
        # step-scoped check finds the DENY.
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            step=self.step_one,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.DENY,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

        # Explicit DENY should override the implicit VIEW.
        allowed = WorkflowAuthorizationService.has_permission(
            user=self.user,
            workflow=self.workflow,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            instance=instance,
        )

        self.assertFalse(allowed)

    def test_start_endpoint_redirects_to_instance_without_403(self):
        """After starting a workflow, the user can follow the
        redirect to the new instance without receiving 403.
        """
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)

        # Start the workflow via POST.
        response = client.post(
            f"/operator/workflow/{self.workflow.pk}/start/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 302)

        # Follow the redirect to the instance page.
        instance = WorkflowInstance.objects.get(
            workflow=self.workflow,
            started_by=self.user,
        )

        response = client.get(
            f"/operator/workflow-instance/{instance.pk}/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)

    def test_implicit_view_only_applies_with_instance(self):
        """Without an instance parameter, the implicit VIEW
        grant should NOT apply.
        """
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        # Without instance=, VIEW should not be granted.
        allowed = WorkflowAuthorizationService.has_permission(
            user=self.user,
            workflow=self.workflow,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
        )

        self.assertFalse(allowed)
