"""
Regression tests for the Dashboard / Sidebar audit fixes:

  A  workflow-start ValidationError failure path
  B  sidebar badge hidden state
  C  sidebar "فرآیندهای من" count semantics
  D  limit-before-filter counting bug
  E  unified sidebar/dashboard task predicate
  F  abandoned-start consistency
  G  actionable vs instance-VIEW authorization
  H  SLA summary beyond 200 instances
  J  mobile workflow-start DOM
  K  header role display
  L  contextual header page title
  M  notification navigation payload
  O  query volume of the dashboard request
"""

import re
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Job
from operator_panel import dashboard_services as dashboard_q
from operator_panel.dashboard_services import DashboardService
from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    FormData,
    Notification,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)

User = get_user_model()

APP_CSS = (
    Path(__file__).resolve().parent
    / "static"
    / "operator_panel"
    / "css"
    / "app.css"
)


def rendered_page_title(content):
    """Extract the text of the header .df-page-title element."""
    match = re.search(
        r'class="df-page-title">\s*(.*?)\s*</div>',
        content,
        re.DOTALL,
    )
    return match.group(1).strip() if match else None


class DashboardSidebarBase(TestCase):
    """Shared fixtures for dashboard/sidebar tests."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="dash_user",
            password="test-password",
        )
        self.other = User.objects.create_user(
            username="other_user",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Dash WF",
            code="DASH_WF",
            is_active=True,
        )

        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step One",
            code="DASH_S1",
            order=1,
            is_active=True,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step Two",
            code="DASH_S2",
            order=2,
            is_active=True,
        )
        self.transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Forward",
            code="DASH_T1",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )

        for user in (self.user, self.other):
            WorkflowMembership.objects.create(
                workflow=self.workflow,
                user=user,
                role=WorkflowMembership.Role.EXECUTOR,
                is_active=True,
            )

    def grant_role_action_permissions(self):
        """EXECUTOR role gets VIEW + EXECUTE on step one and TRANSITION."""
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.EXECUTE,
            step=self.step_one,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.TRANSITION,
            transition=self.transition,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def create_active_instance(
        self,
        *,
        started_by,
        step=None,
        status=WorkflowInstance.Status.ACTIVE,
    ):
        return WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=step or self.step_one,
            started_by=started_by,
            status=status,
        )

    def get_client(self):
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        return client


class StartWorkflowFailureTests(DashboardSidebarBase):
    """A: starting a workflow that fails validation must not render a
    broken dashboard and must surface the error."""

    def test_failing_start_redirects_through_dashboard_with_visible_error(self):
        # Workflow with no active steps -> ValidationError on start.
        empty_workflow = Workflow.objects.create(
            name="Empty WF",
            code="DASH_EMPTY",
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=empty_workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=empty_workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        client = self.get_client()
        response = client.post(
            reverse(
                "operator_panel:start_workflow",
                args=[empty_workflow.pk],
            ),
            follow=True,
        )

        # No broken/incomplete dashboard render (no 400 with stripped
        # context): the user lands on the normal dashboard flow.
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("فرآیندهای قابل شروع", content)

        # The validation error is visible to the user.
        self.assertContains(
            response,
            "این Workflow هیچ مرحله فعالی ندارد.",
        )
        self.assertContains(response, 'id="df-error-modal"')

        # Nothing was created.
        self.assertFalse(
            WorkflowInstance.objects.filter(
                workflow=empty_workflow,
            ).exists()
        )

    def test_successful_start_still_redirects_to_instance(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        client = self.get_client()
        response = client.post(
            reverse(
                "operator_panel:start_workflow",
                args=[self.workflow.pk],
            ),
        )

        self.assertEqual(response.status_code, 302)
        instance = WorkflowInstance.objects.get(
            workflow=self.workflow,
            started_by=self.user,
        )
        self.assertEqual(
            response.url,
            reverse(
                "operator_panel:workflow_instance",
                args=[instance.pk],
            ),
        )


class SidebarBadgeHiddenTests(DashboardSidebarBase):
    """B: zero-value sidebar badges must be genuinely hidden."""

    def test_zero_badges_render_with_hidden_attribute(self):
        response = self.get_client().get(
            reverse("operator_panel:dashboard"),
        )
        content = response.content.decode()

        self.assertIn('id="df-sidebar-active-count" hidden', content)
        self.assertIn('id="df-sidebar-task-count" hidden', content)
        self.assertIn('id="df-sidebar-pending-count" hidden', content)

    def test_nonzero_badge_renders_without_hidden(self):
        self.grant_role_action_permissions()
        self.create_active_instance(started_by=self.other)

        response = self.get_client().get(
            reverse("operator_panel:dashboard"),
        )
        content = response.content.decode()

        # One pending action, not assigned to the user.
        self.assertIn('id="df-sidebar-pending-count">1', content)
        # Zero counters still carry hidden.
        self.assertIn('id="df-sidebar-active-count" hidden', content)
        self.assertIn('id="df-sidebar-task-count" hidden', content)

    def test_css_forces_hidden_badges_to_not_display(self):
        css = APP_CSS.read_text()
        self.assertIn(".df-nav-badge[hidden]", css)


class SidebarActiveCountTests(DashboardSidebarBase):
    """C: the "فرآیندهای من" badge counts the user's own meaningful
    active processes."""

    def test_other_members_active_instance_not_counted(self):
        self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["active"], 0)

    def test_own_meaningful_active_instance_counted(self):
        instance = self.create_active_instance(started_by=self.user)
        FormData.objects.create(instance=instance, data={"note": "x"})

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["active"], 1)

    def test_abandoned_start_not_counted(self):
        # Started but no data/device/transition -> abandoned start.
        self.create_active_instance(started_by=self.user)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["active"], 0)

    def test_badge_matches_dashboard_active_kpi(self):
        instance = self.create_active_instance(started_by=self.user)
        FormData.objects.create(instance=instance, data={"note": "x"})

        counts = DashboardService(self.user).get_sidebar_counts()
        context = DashboardService(self.user).get_context()
        self.assertEqual(counts["active"], context["summary"]["active"])


class AbandonedStartConsistencyTests(DashboardSidebarBase):
    """F: abandoned starts are excluded consistently from the sidebar
    badge, the dashboard active KPI/panel, and the my_processes page."""

    def test_abandoned_start_excluded_everywhere(self):
        abandoned = self.create_active_instance(started_by=self.user)
        meaningful = self.create_active_instance(started_by=self.user)
        FormData.objects.create(instance=meaningful, data={"note": "x"})

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["active"], 1)
        self.assertEqual(
            [item.pk for item in context["active_processes"]],
            [meaningful.pk],
        )
        self.assertEqual(
            DashboardService(self.user).get_sidebar_counts()["active"],
            1,
        )

        response = self.get_client().get(
            reverse("operator_panel:my_processes"),
        )
        content = response.content.decode()
        self.assertIn(f"<span>#{meaningful.pk}</span>", content)
        self.assertNotIn(f"<span>#{abandoned.pk}</span>", content)


class LimitBeforeFilterTests(DashboardSidebarBase):
    """D: counts come from the full population, never from a list slice."""

    def test_tasks_count_includes_instances_beyond_newest_50(self):
        self.grant_role_action_permissions()
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])

        for _ in range(60):
            self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["tasks"], 60)

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["tasks"], 60)
        # The rendered list is intentionally capped.
        self.assertEqual(len(context["my_tasks"]), 50)

    def test_pending_count_includes_instances_beyond_newest_50(self):
        self.grant_role_action_permissions()

        for _ in range(60):
            self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["pending"], 60)

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["pending"], 60)
        self.assertEqual(len(context["pending_actions"]), 50)

    def test_displayed_list_is_ordered_newest_first(self):
        self.grant_role_action_permissions()

        instance_ids = []
        for _ in range(55):
            instance_ids.append(
                self.create_active_instance(started_by=self.other).pk
            )

        context = DashboardService(self.user).get_context()
        displayed = [
            item.pk for item in context["pending_actions"]
        ]
        # Newest 50 of the 55 matching instances are displayed.
        self.assertEqual(
            displayed,
            list(reversed(instance_ids))[:50],
        )


class TaskPredicateTests(DashboardSidebarBase):
    """E: sidebar task badge and dashboard my-tasks share one predicate:
    assigned to the user AND actionable."""

    def test_assigned_and_actionable_counts_as_task(self):
        self.grant_role_action_permissions()
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])
        self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["tasks"], 1)
        self.assertEqual(counts["pending"], 0)

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["tasks"], 1)
        self.assertEqual(context["summary"]["pending"], 0)
        self.assertEqual(len(context["my_tasks"]), 1)
        self.assertEqual(len(context["pending_actions"]), 0)

    def test_assigned_but_not_actionable_is_not_counted(self):
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])
        self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["tasks"], 0)
        self.assertEqual(counts["pending"], 0)

    def test_unassigned_but_actionable_counts_as_pending(self):
        self.grant_role_action_permissions()
        self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["tasks"], 0)
        self.assertEqual(counts["pending"], 1)

    def test_sidebar_and_dashboard_counts_are_identical(self):
        self.grant_role_action_permissions()
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])
        for _ in range(3):
            self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        context = DashboardService(self.user).get_context()
        self.assertEqual(counts["tasks"], context["summary"]["tasks"])
        self.assertEqual(counts["pending"], context["summary"]["pending"])


class ActionabilityViewConsistencyTests(DashboardSidebarBase):
    """G: the dashboard never advertises an action the user cannot
    legally reach (the instance view enforces VIEW permission)."""

    def test_execute_without_view_not_listed_as_actionable(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.EXECUTE,
            step=self.step_one,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.TRANSITION,
            transition=self.transition,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        instance = self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["pending"], 0)
        self.assertEqual(counts["tasks"], 0)

        client = self.get_client()
        response = client.get(reverse("operator_panel:dashboard"))
        content = response.content.decode()
        self.assertNotIn(f"#{instance.pk}", content)

        # The instance view really does deny access.
        response = client.get(
            reverse(
                "operator_panel:workflow_instance",
                args=[instance.pk],
            ),
        )
        self.assertEqual(response.status_code, 403)

    def test_explicit_view_deny_hides_even_own_instance(self):
        self.grant_role_action_permissions()
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.DENY,
        )
        instance = self.create_active_instance(started_by=self.user)
        FormData.objects.create(instance=instance, data={"note": "x"})

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["active"], 0)

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["active"], 0)
        self.assertEqual(context["active_processes"], [])


class SlaSummaryTests(DashboardSidebarBase):
    """H: SLA counts cover the complete population, not the newest 200."""

    def test_older_instance_beyond_200_contributes_to_breach_count(self):
        self.grant_role_action_permissions()
        now = timezone.now()

        for _ in range(205):
            instance = self.create_active_instance(started_by=self.other)
            WorkflowStepExecution.objects.create(
                instance=instance,
                workflow_step=self.step_one,
                performed_by=self.other,
            )

        # Breach only the 10 oldest instances (beyond the newest 200).
        oldest = list(
            WorkflowInstance.objects.order_by("started_at")[:10]
        )
        for instance in oldest:
            execution = instance.step_executions.first()
            execution.sla_due_at = now - timedelta(days=1)
            execution.save(update_fields=["sla_due_at"])

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["sla_breached"], 10)

    def test_warning_count_across_full_population(self):
        self.grant_role_action_permissions()
        now = timezone.now()

        for _ in range(205):
            instance = self.create_active_instance(started_by=self.other)
            WorkflowStepExecution.objects.create(
                instance=instance,
                workflow_step=self.step_one,
                performed_by=self.other,
            )

        # 5 oldest instances are in warning: due in the future,
        # warning threshold already passed.
        oldest = list(
            WorkflowInstance.objects.order_by("started_at")[:5]
        )
        for instance in oldest:
            execution = instance.step_executions.first()
            execution.sla_warning_at = now - timedelta(hours=1)
            execution.sla_due_at = now + timedelta(days=1)
            execution.save(
                update_fields=["sla_warning_at", "sla_due_at"],
            )

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["sla_warning"], 5)
        self.assertEqual(context["summary"]["sla_breached"], 0)


class MobileWorkflowStartTests(DashboardSidebarBase):
    """J: the mobile sidebar exposes a touch trigger for startable
    workflows and keeps their names in the rendered markup."""

    def test_sidebar_has_touch_trigger_and_named_workflows(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        response = self.get_client().get(
            reverse("operator_panel:dashboard"),
        )
        content = response.content.decode()

        self.assertIn('id="df-nav-workflow-trigger"', content)
        self.assertIn('id="df-nav-workflows"', content)
        self.assertIn(self.workflow.name, content)

        # The trigger is hidden on desktop and only drives the flyout
        # inside the mobile media query.
        css = APP_CSS.read_text()
        self.assertIn(".df-nav-workflow-trigger {", css)
        self.assertIn(
            '.df-nav-workflow-trigger[aria-expanded="true"] + #df-nav-workflows',
            css,
        )
        self.assertIn("@media (max-width: 760px)", css)

    def test_trigger_missing_without_startable_workflows(self):
        # The trigger/list markup is still present (empty state) but no
        # workflow is advertised.
        response = self.get_client().get(
            reverse("operator_panel:dashboard"),
        )
        content = response.content.decode()
        self.assertIn('id="df-nav-workflow-trigger"', content)
        self.assertIn("فرآیند قابل شروعی وجود ندارد.", content)


class HeaderRoleDisplayTests(DashboardSidebarBase):
    """K: the header shows the real role information (job) and renders
    no empty role element when the user has none."""

    def test_job_name_shown_in_header(self):
        job = Job.objects.create(
            name="کارشناس",
            code="EXPERT",
        )
        self.user.job = job
        self.user.save(update_fields=["job"])

        response = self.get_client().get(
            reverse("operator_panel:dashboard"),
        )
        content = response.content.decode()
        self.assertIn("کارشناس", content)
        self.assertIn('class="df-user-role"', content)

    def test_no_empty_role_element_without_job(self):
        response = self.get_client().get(
            reverse("operator_panel:dashboard"),
        )
        content = response.content.decode()
        self.assertNotIn('class="df-user-role"', content)


class ContextualHeaderTitleTests(DashboardSidebarBase):
    """L: the shared header shows the actual page title, not a hardcoded
    "داشبورد"."""

    def test_dashboard_title(self):
        response = self.get_client().get(
            reverse("operator_panel:dashboard"),
        )
        self.assertEqual(
            rendered_page_title(response.content.decode()),
            "داشبورد",
        )

    def test_my_processes_title(self):
        response = self.get_client().get(
            reverse("operator_panel:my_processes"),
        )
        self.assertEqual(
            rendered_page_title(response.content.decode()),
            "فرآیندهای من",
        )

    def test_workflow_instance_title(self):
        instance = self.create_active_instance(started_by=self.user)
        response = self.get_client().get(
            reverse(
                "operator_panel:workflow_instance",
                args=[instance.pk],
            ),
        )
        self.assertEqual(
            rendered_page_title(response.content.decode()),
            self.workflow.name,
        )


class NotificationNavigationTests(DashboardSidebarBase):
    """M: notification payloads carry a safe instance URL for
    click-through navigation."""

    def test_notification_payload_includes_instance_url(self):
        instance = self.create_active_instance(started_by=self.user)
        Notification.objects.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.ACTION_REQUIRED
            ),
            title="اقدام لازم",
            message="یک اقدام لازم است",
            workflow_instance=instance,
        )

        response = self.get_client().get(
            reverse("operator_panel:notifications"),
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["count"], 1)
        payload = data["notifications"][0]
        self.assertEqual(payload["workflow_instance_id"], instance.pk)
        self.assertEqual(
            payload["workflow_instance_url"],
            reverse(
                "operator_panel:workflow_instance",
                args=[instance.pk],
            ),
        )

    def test_notification_without_instance_has_no_url(self):
        Notification.objects.create(
            recipient=self.user,
            notification_type=(
                Notification.NotificationType.ACTION_REQUIRED
            ),
            title="بدون نمونه",
            message="بدون نمونه",
        )

        response = self.get_client().get(
            reverse("operator_panel:notifications"),
        )
        payload = response.json()["notifications"][0]
        self.assertIsNone(payload["workflow_instance_id"])
        self.assertIsNone(payload["workflow_instance_url"])


class DashboardQueryVolumeTests(DashboardSidebarBase):
    """O: the dashboard request stays bounded instead of doing
    per-instance authorization queries."""

    def test_dashboard_request_query_volume_is_bounded(self):
        self.grant_role_action_permissions()
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])

        for _ in range(40):
            self.create_active_instance(started_by=self.other)

        with CaptureQueriesContext(connection) as ctx:
            response = self.get_client().get(
                reverse("operator_panel:dashboard"),
            )
            self.assertEqual(response.status_code, 200)

        self.assertLess(len(ctx), 60)


# ----------------------------------------------------------------
# Correctness-review regression tests.
#
# These compare the optimized dashboard Q/Exists predicates against
# the canonical WorkflowAuthorizationService and prove the "my
# processes" badge, the destination page, and the dashboard panels
# share one queryset.
# ----------------------------------------------------------------


def service_view(user, instance):
    """Canonical: has_permission(VIEW, step=current_step, instance)."""
    return WorkflowAuthorizationService.has_permission(
        user=user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
        instance=instance,
    )


def service_execute(user, instance):
    """Canonical: has_permission(EXECUTE, step=current_step)."""
    return WorkflowAuthorizationService.has_permission(
        user=user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.EXECUTE,
        step=instance.current_step,
    )


def service_transition_granted(user, instance):
    """Canonical: get_allowed_transitions(from_step=current_step) != []"""
    if not instance.current_step_id:
        return False
    return bool(
        WorkflowAuthorizationService.get_allowed_transitions(
            user=user,
            workflow=instance.workflow,
            from_step=instance.current_step,
        )
    )


def service_actionable(user, instance):
    """Canonical dashboard actionability predicate (old can_take_action)."""
    return bool(
        service_view(user, instance)
        and (
            service_execute(user, instance)
            or service_transition_granted(user, instance)
        )
    )


def _annotated_query(user, instance):
    return WorkflowInstance.objects.filter(
        pk=instance.pk,
    ).annotate(
        **dashboard_q._actionability_annotations(user),
    )


def query_view(user, instance):
    return (
        _annotated_query(user, instance)
        .filter(workflow__is_active=True)
        .filter(dashboard_q._can_view_q(user))
        .exists()
    )


def query_execute(user, instance):
    return (
        _annotated_query(user, instance)
        .filter(
            workflow__is_active=True,
            _df_member=True,
        )
        .filter(dashboard_q._deny_allow_q(prefix="execute"))
        .exists()
    )


def query_transition_granted(user, instance):
    if not instance.current_step_id:
        return False
    return (
        _annotated_query(user, instance)
        .filter(
            workflow__is_active=True,
            _df_member=True,
            _df_transition_granted=True,
        )
        .exists()
    )


def query_actionable(user, instance):
    return (
        _annotated_query(user, instance)
        .filter(workflow__is_active=True)
        .filter(dashboard_q._can_take_action_q(user))
        .exists()
    )


class AuthorizationEquivalenceMatrixTests(DashboardSidebarBase):
    """Review #2/#3: the optimized dashboard predicates must produce
    exactly the result of WorkflowAuthorizationService for every
    permission configuration."""

    PREDICATES = {
        "view": (service_view, query_view),
        "execute": (service_execute, query_execute),
        "transition": (
            service_transition_granted,
            query_transition_granted,
        ),
        "actionable": (service_actionable, query_actionable),
    }

    def assert_matches_service(self, user, instances):
        for instance in instances:
            for name, (service, query) in self.PREDICATES.items():
                self.assertEqual(
                    query(user, instance),
                    service(user, instance),
                    f"{name} mismatch for instance #{instance.pk}",
                )

    def perm(self, **kwargs):
        kwargs.setdefault("workflow", self.workflow)
        kwargs.setdefault("effect", WorkflowPermission.Effect.ALLOW)
        return WorkflowPermission.objects.create(**kwargs)

    def test_role_allow_grants_view_execute_transition(self):
        self.grant_role_action_permissions()
        own = self.create_active_instance(started_by=self.user)
        other = self.create_active_instance(started_by=self.other)

        for instance in (own, other):
            self.assertTrue(service_view(self.user, instance))
            self.assertTrue(service_execute(self.user, instance))
            self.assertTrue(service_transition_granted(self.user, instance))
            self.assertTrue(service_actionable(self.user, instance))
        self.assert_matches_service(self.user, [own, other])

    def test_deny_default_and_implicit_starter_view(self):
        # No permission rows at all: membership alone grants nothing...
        own = self.create_active_instance(started_by=self.user)
        other = self.create_active_instance(started_by=self.other)

        # ...except the implicit VIEW grant for the starter.
        self.assertTrue(service_view(self.user, own))
        self.assertFalse(service_view(self.user, other))
        self.assertFalse(service_execute(self.user, other))
        self.assertFalse(service_transition_granted(self.user, other))
        self.assertFalse(service_actionable(self.user, other))
        self.assert_matches_service(self.user, [own, other])

    def test_user_deny_overrides_role_allow(self):
        self.grant_role_action_permissions()
        instance = self.create_active_instance(started_by=self.other)

        self.perm(
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.DENY,
        )
        self.perm(
            user=self.user,
            action=WorkflowPermission.Action.EXECUTE,
            step=self.step_one,
            effect=WorkflowPermission.Effect.DENY,
        )
        self.perm(
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            transition=self.transition,
            effect=WorkflowPermission.Effect.DENY,
        )

        self.assertFalse(service_view(self.user, instance))
        self.assertFalse(service_execute(self.user, instance))
        self.assertFalse(service_transition_granted(self.user, instance))
        self.assertFalse(service_actionable(self.user, instance))
        self.assert_matches_service(self.user, [instance])

    def test_user_allow_overrides_role_deny(self):
        self.grant_role_action_permissions()
        instance = self.create_active_instance(started_by=self.other)

        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.DENY,
        )
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.EXECUTE,
            step=self.step_one,
            effect=WorkflowPermission.Effect.DENY,
        )
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.TRANSITION,
            transition=self.transition,
            effect=WorkflowPermission.Effect.DENY,
        )

        # Role DENY applies...
        self.assertFalse(service_view(self.user, instance))
        self.assertFalse(service_execute(self.user, instance))
        self.assertFalse(service_transition_granted(self.user, instance))

        # ...until an explicit user ALLOW overrides it.
        self.perm(
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
        )
        self.perm(
            user=self.user,
            action=WorkflowPermission.Action.EXECUTE,
            step=self.step_one,
        )
        self.perm(
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            transition=self.transition,
        )
        self.assertTrue(service_view(self.user, instance))
        self.assertTrue(service_execute(self.user, instance))
        self.assertTrue(service_transition_granted(self.user, instance))
        self.assert_matches_service(self.user, [instance])

    def test_role_deny_blocks_implicit_starter_view(self):
        # Explicit DENY must beat the starter's implicit VIEW grant
        # (has_permission checks DENY before the starter fallback).
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.DENY,
        )
        own = self.create_active_instance(started_by=self.user)

        self.assertFalse(service_view(self.user, own))
        self.assertFalse(service_actionable(self.user, own))
        self.assert_matches_service(self.user, [own])

    def test_view_scope_switches_to_workflow_level_without_current_step(self):
        # A workflow-level VIEW ALLOW (step/transition NULL) only applies
        # when has_permission resolves with step=None (current_step None).
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
        )

        completed = self.create_active_instance(
            started_by=self.other,
            status=WorkflowInstance.Status.COMPLETED,
        )
        completed.current_step = None
        completed.save(update_fields=["current_step"])

        on_step = self.create_active_instance(started_by=self.other)

        self.assertTrue(service_view(self.user, completed))
        self.assertFalse(service_view(self.user, on_step))
        self.assert_matches_service(self.user, [completed, on_step])

    def test_workflow_level_deny_blocks_starter_without_current_step(self):
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.DENY,
        )
        own = self.create_active_instance(
            started_by=self.user,
            status=WorkflowInstance.Status.COMPLETED,
        )
        own.current_step = None
        own.save(update_fields=["current_step"])

        self.assertFalse(service_view(self.user, own))
        self.assert_matches_service(self.user, [own])

    def test_inactive_workflow_denies_everything(self):
        self.grant_role_action_permissions()
        self.workflow.is_active = False
        self.workflow.save(update_fields=["is_active"])
        instance = self.create_active_instance(started_by=self.user)

        self.assertFalse(service_view(self.user, instance))
        self.assertFalse(service_execute(self.user, instance))
        self.assertFalse(service_transition_granted(self.user, instance))
        self.assertFalse(service_actionable(self.user, instance))
        self.assert_matches_service(self.user, [instance])

    def test_inactive_membership_denies_everything(self):
        self.grant_role_action_permissions()
        membership = WorkflowMembership.objects.get(
            workflow=self.workflow,
            user=self.user,
        )
        membership.is_active = False
        membership.save(update_fields=["is_active"])
        instance = self.create_active_instance(started_by=self.user)

        self.assertFalse(service_view(self.user, instance))
        self.assertFalse(service_execute(self.user, instance))
        self.assertFalse(service_transition_granted(self.user, instance))
        self.assert_matches_service(self.user, [instance])

    def test_transition_per_transition_allow_and_deny(self):
        """Regression: an ALLOW on one transition must not be negated by
        a DENY on a *different* transition from the same step."""
        self.grant_role_action_permissions()
        second = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Second forward",
            code="DASH_T2",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.TRANSITION,
            transition=second,
            effect=WorkflowPermission.Effect.DENY,
        )

        instance = self.create_active_instance(started_by=self.other)

        # t1 still allowed -> a transition is granted.
        self.assertTrue(service_transition_granted(self.user, instance))
        self.assertTrue(service_actionable(self.user, instance))
        self.assert_matches_service(self.user, [instance])

        # Flip: ALLOW on t2, DENY on t1 only -> granted via t2.
        WorkflowPermission.objects.filter(
            workflow=self.workflow,
            transition=second,
        ).update(effect=WorkflowPermission.Effect.ALLOW)
        WorkflowPermission.objects.filter(
            workflow=self.workflow,
            transition=self.transition,
        ).update(effect=WorkflowPermission.Effect.DENY)
        self.assertTrue(service_transition_granted(self.user, instance))
        self.assert_matches_service(self.user, [instance])

        # DENY on every candidate -> nothing granted.
        WorkflowPermission.objects.filter(
            workflow=self.workflow,
            action=WorkflowPermission.Action.TRANSITION,
        ).update(effect=WorkflowPermission.Effect.DENY)
        self.assertFalse(service_transition_granted(self.user, instance))
        self.assert_matches_service(self.user, [instance])

    def test_inactive_transition_is_never_granted(self):
        self.transition.is_active = False
        self.transition.save(update_fields=["is_active"])
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.TRANSITION,
            transition=self.transition,
        )

        instance = self.create_active_instance(started_by=self.other)

        self.assertFalse(service_transition_granted(self.user, instance))
        self.assert_matches_service(self.user, [instance])

    def test_view_without_execute_or_transition_is_not_actionable(self):
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
        )
        self.perm(
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_two,
        )
        instance = self.create_active_instance(started_by=self.other)

        self.assertTrue(service_view(self.user, instance))
        self.assertFalse(service_execute(self.user, instance))
        self.assertFalse(service_transition_granted(self.user, instance))
        self.assertFalse(service_actionable(self.user, instance))
        self.assert_matches_service(self.user, [instance])


class MyProcessesConsistencyTests(DashboardSidebarBase):
    """Review #1: the sidebar badge and the my_processes destination
    page must represent exactly the same canonical population, and
    every listed row must be reachable under the destination VIEW rule."""

    def _badge_value(self, content):
        match = re.search(
            r'id="df-sidebar-active-count"(?: hidden)?>?(\d*)<',
            content,
        )
        if match is None:
            return None
        return int(match.group(1) or 0)

    def test_badge_equals_active_rows_of_destination_page(self):
        own_active = self.create_active_instance(started_by=self.user)
        FormData.objects.create(
            instance=own_active,
            data={"note": "x"},
        )
        completed = self.create_active_instance(
            started_by=self.user,
            status=WorkflowInstance.Status.COMPLETED,
        )
        FormData.objects.create(
            instance=completed,
            data={"note": "done"},
        )
        # Not mine: excluded from the page and the badge.
        self.create_active_instance(started_by=self.other)

        client = self.get_client()
        response = client.get(reverse("operator_panel:my_processes"))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        page_pks = [
            instance.pk for instance in response.context["instances"]
        ]
        self.assertIn(own_active.pk, page_pks)
        self.assertIn(completed.pk, page_pks)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["active"], 1)
        self.assertEqual(self._badge_value(content), counts["active"])

        # Every listed row is openable under the instance VIEW rule.
        for pk in page_pks:
            row = client.get(
                reverse("operator_panel:workflow_instance", args=[pk]),
            )
            self.assertEqual(row.status_code, 200, f"row #{pk} not openable")

    def test_own_view_denied_instance_hidden_from_page_and_badge(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.DENY,
        )
        instance = self.create_active_instance(started_by=self.user)
        FormData.objects.create(instance=instance, data={"note": "x"})

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["active"], 0)

        response = self.get_client().get(
            reverse("operator_panel:my_processes"),
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(f"<span>#{instance.pk}</span>", content)
        self.assertEqual(self._badge_value(content), 0)

        # The destination really denies access.
        denied = self.get_client().get(
            reverse(
                "operator_panel:workflow_instance",
                args=[instance.pk],
            ),
        )
        self.assertEqual(denied.status_code, 403)

    def test_other_members_active_process_not_listed(self):
        instance = self.create_active_instance(started_by=self.other)
        FormData.objects.create(instance=instance, data={"note": "x"})

        response = self.get_client().get(
            reverse("operator_panel:my_processes"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            f"<span>#{instance.pk}</span>",
            response.content.decode(),
        )
        self.assertEqual(
            DashboardService(self.user).get_sidebar_counts()["active"],
            0,
        )

    def test_inactive_workflow_process_hidden_from_page_and_badge(self):
        workflow = Workflow.objects.create(
            name="Retired WF",
            code="RETIRED",
            is_active=False,
        )
        WorkflowMembership.objects.create(
            workflow=workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        step = WorkflowStep.objects.create(
            workflow=workflow,
            name="Only step",
            code="RET_S1",
            order=1,
            is_active=True,
        )
        instance = WorkflowInstance.objects.create(
            workflow=workflow,
            current_step=step,
            started_by=self.user,
        )
        FormData.objects.create(instance=instance, data={"note": "x"})

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["active"], 0)

        response = self.get_client().get(
            reverse("operator_panel:my_processes"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            f"<span>#{instance.pk}</span>",
            response.content.decode(),
        )

    def test_started_without_membership_hidden(self):
        workflow = Workflow.objects.create(
            name="Foreign WF",
            code="FOREIGN",
            is_active=True,
        )
        step = WorkflowStep.objects.create(
            workflow=workflow,
            name="Only step",
            code="FOR_S1",
            order=1,
            is_active=True,
        )
        # User started an instance but never was (or is no longer) a
        # member: the destination VIEW rule denies, so it is hidden.
        instance = WorkflowInstance.objects.create(
            workflow=workflow,
            current_step=step,
            started_by=self.user,
        )
        FormData.objects.create(instance=instance, data={"note": "x"})

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["active"], 0)

        response = self.get_client().get(
            reverse("operator_panel:my_processes"),
        )
        self.assertNotIn(
            f"<span>#{instance.pk}</span>",
            response.content.decode(),
        )


class TaskSemanticMatrixTests(DashboardSidebarBase):
    """Review #4: task counting is assigned-to-me AND actionable, with
    the same predicate on the sidebar badge, KPI, and list."""

    def test_assigned_with_transition_only_counts_as_task(self):
        # VIEW + TRANSITION (no EXECUTE) is still actionable.
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.TRANSITION,
            transition=self.transition,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])
        self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["tasks"], 1)
        self.assertEqual(counts["pending"], 0)

    def test_assigned_with_view_only_is_not_a_task(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])
        self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["tasks"], 0)
        self.assertEqual(counts["pending"], 0)

    def test_assigned_with_execute_but_no_view_is_not_a_task(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.EXECUTE,
            step=self.step_one,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])
        self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["tasks"], 0)
        self.assertEqual(counts["pending"], 0)

    def test_unassigned_with_view_only_is_neither_task_nor_pending(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            role=WorkflowMembership.Role.EXECUTOR,
            action=WorkflowPermission.Action.VIEW,
            step=self.step_one,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.create_active_instance(started_by=self.other)

        counts = DashboardService(self.user).get_sidebar_counts()
        self.assertEqual(counts["tasks"], 0)
        self.assertEqual(counts["pending"], 0)


class SlaLegacyEquivalenceTests(DashboardSidebarBase):
    """Review #6: the aggregated SLA summary must match the legacy
    per-instance algorithm exactly, while covering the full population
    instead of the newest 200 instances."""

    def legacy_summary(self, now):
        """The pre-optimization algorithm, kept here as ground truth."""
        accessible_ids = list(
            WorkflowInstance.objects
            .filter(
                status=WorkflowInstance.Status.ACTIVE,
                workflow__memberships__user=self.user,
                workflow__memberships__is_active=True,
            )
            .values_list("pk", flat=True)
            .distinct()
        )
        executions = (
            WorkflowStepExecution.objects
            .filter(
                instance_id__in=accessible_ids,
                is_submitted=False,
                sla_due_at__isnull=False,
                sla_completed_at__isnull=True,
            )
            .order_by("instance_id", "-performed_at")
        )
        current = {}
        for execution in executions:
            current.setdefault(execution.instance_id, execution)

        warning = 0
        breached = 0
        for execution in current.values():
            if (
                execution.sla_breached_at is not None
                or now >= execution.sla_due_at
            ):
                breached += 1
            elif (
                execution.sla_warning_at is not None
                and now >= execution.sla_warning_at
            ):
                warning += 1
        return {"warning": warning, "breached": breached}

    def test_summary_matches_legacy_algorithm(self):
        self.grant_role_action_permissions()
        now = timezone.now()

        def execution(
            instance,
            *,
            due=None,
            warning=None,
            breached_at=None,
            completed_at=None,
            submitted=False,
            performed_at=None,
        ):
            execution = WorkflowStepExecution.objects.create(
                instance=instance,
                workflow_step=self.step_one,
                performed_by=self.other,
                is_submitted=submitted,
                sla_due_at=due,
                sla_warning_at=warning,
                sla_breached_at=breached_at,
                sla_completed_at=completed_at,
            )
            if performed_at is not None:
                # performed_at is auto_now_add, so the ordering timestamp
                # must be written after creation.
                WorkflowStepExecution.objects.filter(
                    pk=execution.pk,
                ).update(performed_at=performed_at)
            return execution

        # Latest open execution breached; older one warning -> breached.
        a = self.create_active_instance(started_by=self.other)
        execution(
            a,
            due=now + timedelta(days=2),
            warning=now - timedelta(hours=1),
            performed_at=now - timedelta(days=3),
        )
        execution(
            a,
            due=now - timedelta(days=1),
            performed_at=now - timedelta(hours=1),
        )

        # Latest execution SLA-completed; older one breached -> the
        # completed row is ignored and the open breach still counts.
        b = self.create_active_instance(started_by=self.other)
        execution(
            b,
            due=now - timedelta(days=1),
            performed_at=now - timedelta(days=2),
        )
        execution(
            b,
            due=now - timedelta(days=1),
            completed_at=now,
            performed_at=now - timedelta(hours=1),
        )

        # Latest execution without SLA fields; older breached -> the
        # non-SLA row is ignored and the open breach still counts.
        c = self.create_active_instance(started_by=self.other)
        execution(c, performed_at=now - timedelta(days=2))
        execution(
            c,
            due=now - timedelta(days=1),
            performed_at=now - timedelta(days=1),
        )

        # Submitted executions never contribute.
        d = self.create_active_instance(started_by=self.other)
        execution(
            d,
            due=now - timedelta(days=1),
            submitted=True,
        )

        # Warning state: not breached yet, warning threshold passed.
        e = self.create_active_instance(started_by=self.other)
        execution(
            e,
            due=now + timedelta(days=1),
            warning=now - timedelta(hours=1),
        )

        # No SLA anywhere on this instance.
        f = self.create_active_instance(started_by=self.other)
        execution(f)

        legacy = self.legacy_summary(now)
        self.assertEqual(
            legacy,
            {"warning": 1, "breached": 3},
        )

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["sla_warning"], legacy["warning"])
        self.assertEqual(
            context["summary"]["sla_breached"],
            legacy["breached"],
        )

    def test_summary_matches_legacy_beyond_200_instances(self):
        self.grant_role_action_permissions()
        now = timezone.now()

        # Mixed SLA states across 220 instances (exceeds the legacy
        # 200-row sampling cap) so an older instance must contribute.
        for index in range(220):
            instance = self.create_active_instance(started_by=self.other)
            if index % 3 == 0:
                due = now + timedelta(days=1)
                warning = now - timedelta(hours=1)
            elif index % 3 == 1:
                due = now - timedelta(days=1)
                warning = None
            else:
                due = None
                warning = None
            WorkflowStepExecution.objects.create(
                instance=instance,
                workflow_step=self.step_one,
                performed_by=self.other,
                sla_due_at=due,
                sla_warning_at=warning,
            )

        legacy = self.legacy_summary(now)
        self.assertGreater(legacy["breached"] + legacy["warning"], 0)

        context = DashboardService(self.user).get_context()
        self.assertEqual(context["summary"]["sla_warning"], legacy["warning"])
        self.assertEqual(
            context["summary"]["sla_breached"],
            legacy["breached"],
        )


class TrackerEquivalenceTests(DashboardSidebarBase):
    """Review #8: the batched/prefetched tracker must produce exactly
    the states of the original per-instance algorithm."""

    def legacy_tracker(self, instance):
        """Original build_tracker kept as ground truth."""
        steps = list(
            instance.workflow.steps
            .filter(is_active=True)
            .order_by("order")
        )
        submitted = set(
            WorkflowStepExecution.objects
            .filter(instance=instance, is_submitted=True)
            .values_list("workflow_step_id", flat=True)
        )
        transitioned = set(
            WorkflowTransitionExecution.objects
            .filter(instance=instance)
            .values_list("transition__from_step_id", flat=True)
        )
        completed_ids = submitted | transitioned

        states = []
        for step in steps:
            if instance.status == WorkflowInstance.Status.COMPLETED:
                state = "completed"
            elif instance.status in {
                WorkflowInstance.Status.CANCELLED,
                WorkflowInstance.Status.SUSPENDED,
            }:
                state = (
                    "current"
                    if step.pk == instance.current_step_id
                    else "future"
                )
            elif step.pk == instance.current_step_id:
                state = "current"
            elif step.pk in completed_ids:
                state = "completed"
            else:
                state = "future"
            states.append((step.pk, state))
        return states

    def assert_tracker_equals_legacy(self, instance):
        service_states = [
            (item["step"].pk, item["state"])
            for item in DashboardService(self.user).build_tracker(instance)
        ]
        self.assertEqual(service_states, self.legacy_tracker(instance))

    def test_tracker_states_for_every_instance_status(self):
        # ACTIVE on step one, nothing done.
        fresh = self.create_active_instance(started_by=self.user)
        # ACTIVE with a submitted step-one execution (still current).
        submitted = self.create_active_instance(started_by=self.user)
        WorkflowStepExecution.objects.create(
            instance=submitted,
            workflow_step=self.step_one,
            performed_by=self.user,
            is_submitted=True,
            submitted_at=timezone.now(),
        )
        # ACTIVE on step two after a transition from step one.
        moved = self.create_active_instance(
            started_by=self.user,
            step=self.step_two,
        )
        WorkflowTransitionExecution.objects.create(
            instance=moved,
            transition=self.transition,
            performed_by=self.user,
        )
        # COMPLETED.
        completed = self.create_active_instance(
            started_by=self.user,
            status=WorkflowInstance.Status.COMPLETED,
        )
        # CANCELLED on step two.
        cancelled = self.create_active_instance(
            started_by=self.user,
            step=self.step_two,
            status=WorkflowInstance.Status.CANCELLED,
        )
        # SUSPENDED on step one.
        suspended = self.create_active_instance(
            started_by=self.user,
            status=WorkflowInstance.Status.SUSPENDED,
        )
        # An inactive step is not part of the tracker at all.
        WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Retired step",
            code="RET_STEP",
            order=3,
            is_active=False,
        )

        for instance in (
            fresh,
            submitted,
            moved,
            completed,
            cancelled,
            suspended,
        ):
            self.assert_tracker_equals_legacy(instance)

        # Spot-check meaningful states for the moved instance.
        states = {
            item["step"].pk: item["state"]
            for item in DashboardService(self.user).build_tracker(moved)
        }
        self.assertEqual(states[self.step_one.pk], "completed")
        self.assertEqual(states[self.step_two.pk], "current")

    def test_batched_attach_matches_per_instance_build(self):
        moved = self.create_active_instance(
            started_by=self.user,
            step=self.step_two,
        )
        WorkflowTransitionExecution.objects.create(
            instance=moved,
            transition=self.transition,
            performed_by=self.user,
        )
        submitted = self.create_active_instance(started_by=self.user)
        WorkflowStepExecution.objects.create(
            instance=submitted,
            workflow_step=self.step_one,
            performed_by=self.user,
            is_submitted=True,
            submitted_at=timezone.now(),
        )

        service = DashboardService(self.user)
        active = list(service._my_active_queryset())
        service._attach_dashboard_state(active, now=timezone.now())

        for instance in active:
            batched = [
                (item["step"].pk, item["state"])
                for item in instance.dashboard_tracker
            ]
            per_instance = [
                (item["step"].pk, item["state"])
                for item in service.build_tracker(instance)
            ]
            self.assertEqual(batched, per_instance)
            self.assertEqual(batched, self.legacy_tracker(instance))


class TemplateContextReuseTests(DashboardSidebarBase):
    """Review #7: on the dashboard the sidebar tags reuse the view
    context instead of recomputing the same service results."""

    def test_dashboard_sidebar_reuses_context(self):
        self.grant_role_action_permissions()
        instance = self.create_active_instance(started_by=self.other)
        FormData.objects.create(instance=instance, data={"note": "x"})

        real_counts = DashboardService.get_sidebar_counts
        real_startable = WorkflowAuthorizationService.get_startable_workflows

        def counting_counts(self):
            counting_counts.calls += 1
            return real_counts(self)

        counting_counts.calls = 0

        def counting_startable(user):
            counting_startable.calls += 1
            return real_startable(user)

        counting_startable.calls = 0

        with (
            mock.patch.object(
                DashboardService,
                "get_sidebar_counts",
                counting_counts,
            ),
            mock.patch.object(
                WorkflowAuthorizationService,
                "get_startable_workflows",
                counting_startable,
            ),
        ):
            response = self.get_client().get(
                reverse("operator_panel:dashboard"),
            )
            self.assertEqual(response.status_code, 200)

        # One computation in the view; the sidebar tag must reuse it.
        self.assertEqual(counting_counts.calls, 1)
        self.assertEqual(counting_startable.calls, 1)

    def test_sidebar_standalone_computation_on_other_pages(self):
        real_counts = DashboardService.get_sidebar_counts
        real_startable = WorkflowAuthorizationService.get_startable_workflows

        def counting_counts(self):
            counting_counts.calls += 1
            return real_counts(self)

        counting_counts.calls = 0

        def counting_startable(user):
            counting_startable.calls += 1
            return real_startable(user)

        counting_startable.calls = 0

        with (
            mock.patch.object(
                DashboardService,
                "get_sidebar_counts",
                counting_counts,
            ),
            mock.patch.object(
                WorkflowAuthorizationService,
                "get_startable_workflows",
                counting_startable,
            ),
        ):
            response = self.get_client().get(
                reverse("operator_panel:my_processes"),
            )
            self.assertEqual(response.status_code, 200)

        # No view-context value: the tags compute exactly once each.
        self.assertEqual(counting_counts.calls, 1)
        self.assertEqual(counting_startable.calls, 1)


class QueryScalingTests(DashboardSidebarBase):
    """Review #9: dashboard SQL volume must not grow linearly with the
    number of instances (no per-instance authorization queries)."""

    def _measure_context_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            DashboardService(self.user).get_context()
        return len(ctx)

    def test_query_count_flat_as_instances_grow(self):
        self.grant_role_action_permissions()
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])

        self.create_active_instance(started_by=self.other)
        small = self._measure_context_queries()

        for _ in range(99):
            self.create_active_instance(started_by=self.other)
        large = self._measure_context_queries()

        # The SQL shape is identical regardless of row count; the only
        # permitted difference is planner noise, never per-instance work.
        self.assertLessEqual(large, small + 5)
        self.assertLess(large, 45)

    def test_counts_use_three_aggregate_queries(self):
        self.grant_role_action_permissions()
        for _ in range(5):
            self.create_active_instance(started_by=self.other)

        with CaptureQueriesContext(connection) as ctx:
            DashboardService(self.user).get_sidebar_counts()
        # active / tasks / pending - one aggregate query each.
        self.assertEqual(len(ctx), 3)