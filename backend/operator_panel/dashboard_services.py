from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    FormData,
    InstanceDevice,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)

# ---------------------------------------------------------
# Presentation list caps
#
# Counts are always computed from the complete matching
# population (database side). These caps only bound the
# rendered lists.
# ---------------------------------------------------------

PENDING_LIST_LIMIT = 50
ACTIVE_PROCESSES_LIMIT = 10


def _roles_subquery(user):
    """Roles of `user` in the (outer) instance's workflow."""
    return WorkflowMembership.objects.filter(
        workflow_id=OuterRef("workflow_id"),
        user=user,
        is_active=True,
    ).values("role")


def _membership_exists(user):
    """True when the user holds an active membership in the workflow."""
    return Exists(
        WorkflowMembership.objects.filter(
            workflow_id=OuterRef("workflow_id"),
            user=user,
            is_active=True,
        )
    )


def _user_permission_exists(user, action, effect, *, step_scope=False, wf_scope=False):
    """
    Exists over explicit user-scoped permission rows.

    ``step_scope`` matches rows pinned to the instance's current step
    (has_permission scope when a step is supplied). ``wf_scope`` matches
    workflow-level rows (step IS NULL AND transition IS NULL), which is
    the scope has_permission resolves when no step is supplied. The two
    scopes are mutually exclusive and never mixed.
    """
    queryset = WorkflowPermission.objects.filter(
        workflow_id=OuterRef("workflow_id"),
        action=action,
        effect=effect,
        user=user,
    )
    if step_scope:
        queryset = queryset.filter(step_id=OuterRef("current_step_id"))
    elif wf_scope:
        queryset = queryset.filter(
            step__isnull=True,
            transition__isnull=True,
        )
    return Exists(queryset)


def _role_permission_exists(user, action, effect, *, step_scope=False, wf_scope=False):
    """Exists over role-scoped permission rows matching one of the user's
    active roles in the outer instance's workflow."""
    queryset = WorkflowPermission.objects.filter(
        workflow_id=OuterRef("workflow_id"),
        action=action,
        effect=effect,
        user__isnull=True,
        role__in=_roles_subquery(user),
    )
    if step_scope:
        queryset = queryset.filter(step_id=OuterRef("current_step_id"))
    elif wf_scope:
        queryset = queryset.filter(
            step__isnull=True,
            transition__isnull=True,
        )
    return Exists(queryset)


def _execute_annotations(user):
    """
    EXECUTE is always resolved at the scope of the instance's current
    step (the caller never asks for EXECUTE without a step), so only
    step-scoped rows are needed. Precedence matches has_permission:
    user DENY > user ALLOW > role DENY > role ALLOW > deny by default.
    """
    return {
        "_df_execute_user_allow": _user_permission_exists(
            user,
            WorkflowPermission.Action.EXECUTE,
            WorkflowPermission.Effect.ALLOW,
            step_scope=True,
        ),
        "_df_execute_user_deny": _user_permission_exists(
            user,
            WorkflowPermission.Action.EXECUTE,
            WorkflowPermission.Effect.DENY,
            step_scope=True,
        ),
        "_df_execute_role_allow": _role_permission_exists(
            user,
            WorkflowPermission.Action.EXECUTE,
            WorkflowPermission.Effect.ALLOW,
            step_scope=True,
        ),
        "_df_execute_role_deny": _role_permission_exists(
            user,
            WorkflowPermission.Action.EXECUTE,
            WorkflowPermission.Effect.DENY,
            step_scope=True,
        ),
    }


def _view_annotations(user):
    """
    Resolve VIEW with the same precedence as WorkflowAuthorizationService.

    Active dashboard instances normally have a current step, so step-scoped
    permissions are the primary path. The workflow-scoped fallback mirrors
    has_permission when current_step is NULL. The instance starter's implicit
    VIEW applies only when no explicit permission has already denied/allowed
    the request.
    """
    return {
        "_df_view_user_allow": _user_permission_exists(
            user,
            WorkflowPermission.Action.VIEW,
            WorkflowPermission.Effect.ALLOW,
            step_scope=True,
        ),
        "_df_view_user_deny": _user_permission_exists(
            user,
            WorkflowPermission.Action.VIEW,
            WorkflowPermission.Effect.DENY,
            step_scope=True,
        ),
        "_df_view_role_allow": _role_permission_exists(
            user,
            WorkflowPermission.Action.VIEW,
            WorkflowPermission.Effect.ALLOW,
            step_scope=True,
        ),
        "_df_view_role_deny": _role_permission_exists(
            user,
            WorkflowPermission.Action.VIEW,
            WorkflowPermission.Effect.DENY,
            step_scope=True,
        ),
        "_df_view_wf_user_allow": _user_permission_exists(
            user,
            WorkflowPermission.Action.VIEW,
            WorkflowPermission.Effect.ALLOW,
            wf_scope=True,
        ),
        "_df_view_wf_user_deny": _user_permission_exists(
            user,
            WorkflowPermission.Action.VIEW,
            WorkflowPermission.Effect.DENY,
            wf_scope=True,
        ),
        "_df_view_wf_role_allow": _role_permission_exists(
            user,
            WorkflowPermission.Action.VIEW,
            WorkflowPermission.Effect.ALLOW,
            wf_scope=True,
        ),
        "_df_view_wf_role_deny": _role_permission_exists(
            user,
            WorkflowPermission.Action.VIEW,
            WorkflowPermission.Effect.DENY,
            wf_scope=True,
        ),
    }


def _can_view_q(user):
    """Return the database-side VIEW permission predicate."""
    step_scope = (
        Q(
            _df_view_user_deny=False,
            _df_view_user_allow=True,
        )
        | Q(
            _df_view_user_deny=False,
            _df_view_user_allow=False,
            _df_view_role_deny=False,
            _df_view_role_allow=True,
        )
        | Q(
            _df_view_user_deny=False,
            _df_view_user_allow=False,
            _df_view_role_deny=False,
            _df_view_role_allow=False,
            started_by=user,
        )
    )

    workflow_scope = (
        Q(
            _df_view_wf_user_deny=False,
            _df_view_wf_user_allow=True,
        )
        | Q(
            _df_view_wf_user_deny=False,
            _df_view_wf_user_allow=False,
            _df_view_wf_role_deny=False,
            _df_view_wf_role_allow=True,
        )
        | Q(
            _df_view_wf_user_deny=False,
            _df_view_wf_user_allow=False,
            _df_view_wf_role_deny=False,
            _df_view_wf_role_allow=False,
            started_by=user,
        )
    )

    return Q(current_step__isnull=False) & step_scope | Q(
        current_step__isnull=True
    ) & workflow_scope


def _can_take_action_q(user):
    """Return the database-side EXECUTE permission predicate."""
    return Q(
        _df_execute_user_deny=False,
        _df_execute_user_allow=True,
    ) | Q(
        _df_execute_user_deny=False,
        _df_execute_user_allow=False,
        _df_execute_role_deny=False,
        _df_execute_role_allow=True,
    )


class DashboardService:
    def __init__(self, user):
        self.user = user

    def _accessible_active_queryset(self):
        """
        Return active instances the user is actually allowed to VIEW.

        Membership is a prerequisite for workflow authorization, not an
        implicit VIEW grant. EXECUTE is intentionally resolved later by
        _can_take_action_q() for actionable/task lists.
        """
        annotations = {
            **_view_annotations(self.user),
            **_execute_annotations(self.user),
        }
        return (
            WorkflowInstance.objects
            .filter(
                status=WorkflowInstance.Status.ACTIVE,
                workflow__is_active=True,
                workflow__memberships__user=self.user,
                workflow__memberships__is_active=True,
            )
            .annotate(**annotations)
            .filter(_can_view_q(self.user))
            .distinct()
        )

    def _my_active_queryset(self):
        meaningful = (
            Q(
                Exists(
                    FormData.objects.filter(
                        instance_id=OuterRef("pk"),
                    )
                )
            )
            | Q(
                Exists(
                    InstanceDevice.objects.filter(
                        instance_id=OuterRef("pk"),
                    )
                )
            )
            | Q(
                Exists(
                    WorkflowTransitionExecution.objects.filter(
                        instance_id=OuterRef("pk"),
                    )
                )
            )
        )
        return (
            WorkflowInstance.objects
            .filter(
                started_by=self.user,
                status=WorkflowInstance.Status.ACTIVE,
            )
            .filter(meaningful)
            .select_related("workflow", "current_step")
        )

    def my_processes_queryset(self):
        return WorkflowInstance.objects.filter(started_by=self.user).select_related(
            "workflow", "current_step"
        )

    def get_sidebar_counts(self):
        accessible = self._accessible_active_queryset()
        actionable = _can_take_action_q(self.user)
        assigned_to_me = Q(current_step__assigned_to_id=self.user.pk)

        return {
            "active": self._my_active_queryset().count(),
            "tasks": accessible.filter(
                actionable,
                assigned_to_me,
            ).count(),
            "pending": accessible.filter(
                actionable,
            ).exclude(
                assigned_to_me,
            ).count(),
        }

    def get_context(self):
        now = timezone.now()
        today = now.date()
        counts = self.get_sidebar_counts()
        my_instances = self.my_processes_queryset()
        active_processes = list(
            self._my_active_queryset()[:ACTIVE_PROCESSES_LIMIT]
        )
        self._attach_dashboard_state(active_processes, now=now)
        sla_summary = self._build_sla_summary(now=now)

        return {
            "summary": {
                "today": my_instances.filter(started_at__date=today).count(),
                "pending": counts["pending"],
                "tasks": counts["tasks"],
                "active": counts["active"],
                "completed": my_instances.filter(
                    status=WorkflowInstance.Status.COMPLETED,
                ).count(),
                "sla_warning": sla_summary["warning"],
                "sla_breached": sla_summary["breached"],
            },
            "active_processes": active_processes,
            "pending_actions": self._pending_instances(exclude_assigned=True),
            "my_tasks": self._pending_instances(assigned_only=True),
            "recent_activity": self._get_recent_activity(),
            "startable_workflows": (
                WorkflowAuthorizationService
                .get_startable_workflows(self.user)
                .order_by("name")
            ),
            "sidebar_counts": counts,
        }

    def _pending_instances(self, *, assigned_only=False, exclude_assigned=False):
        queryset = self._accessible_active_queryset().filter(
            _can_take_action_q(self.user),
        )
        if assigned_only:
            queryset = queryset.filter(current_step__assigned_to_id=self.user.pk)
        elif exclude_assigned:
            queryset = queryset.exclude(current_step__assigned_to_id=self.user.pk)
        return list(queryset[:PENDING_LIST_LIMIT])

    def _attach_dashboard_state(self, instances, *, now):
        if not instances:
            return

        # Be defensive here: callers must pass a datetime, but accepting
        # timezone.now itself as a callable prevents a function/datetime
        # comparison from reaching the SLA state calculation.
        if callable(now):
            now = now()

        instance_ids = [instance.pk for instance in instances]
        executions = (
            WorkflowStepExecution.objects
            .filter(instance_id__in=instance_ids, is_submitted=False)
            .select_related("workflow_step")
            .order_by("-performed_at")
        )
        current_executions = {}
        for execution in executions:
            current_executions.setdefault(execution.instance_id, execution)

        submitted_step_ids = set(
            WorkflowStepExecution.objects
            .filter(instance_id__in=instance_ids, is_submitted=True)
            .values_list("instance_id", "workflow_step_id")
        )
        transitioned_from_ids = set(
            WorkflowTransitionExecution.objects
            .filter(instance_id__in=instance_ids)
            .values_list("instance_id", "transition__from_step_id")
        )

        for instance in instances:
            instance.dashboard_tracker = self.build_tracker(
                instance,
                submitted_step_ids=submitted_step_ids,
                transitioned_from_ids=transitioned_from_ids,
            )
            instance.dashboard_sla = self._build_sla_state(
                current_executions.get(instance.pk),
                now=now,
            )

    def _build_sla_state(self, execution, *, now):
        if execution is None or execution.sla_due_at is None:
            return {
                "configured": False,
                "status": "none",
                "label": "بدون SLA",
                "due_at": None,
                "warning_at": None,
                "execution": execution,
            }

        if execution.sla_completed_at is not None:
            status = "completed"
            label = "SLA تکمیل شد"
        elif execution.sla_breached_at is not None or now >= execution.sla_due_at:
            status = "breached"
            label = "SLA نقض شده"
        elif execution.sla_warning_at is not None and now >= execution.sla_warning_at:
            status = "warning"
            label = "نزدیک به سررسید SLA"
        else:
            status = "on_track"
            label = "در محدوده SLA"

        return {
            "configured": True,
            "status": status,
            "label": label,
            "due_at": execution.sla_due_at,
            "warning_at": execution.sla_warning_at,
            "execution": execution,
        }

    def _build_sla_summary(self, *, now):
        warning = 0
        breached = 0
        executions = (
            WorkflowStepExecution.objects
            .filter(
                instance__in=self._accessible_active_queryset(),
                is_submitted=False,
                sla_due_at__isnull=False,
                sla_completed_at__isnull=True,
            )
            .order_by("instance_id", "-performed_at")
            .only(
                "instance_id",
                "performed_at",
                "sla_due_at",
                "sla_warning_at",
                "sla_breached_at",
                "sla_completed_at",
            )
        )
        current = {}
        for execution in executions:
            current.setdefault(execution.instance_id, execution)

        for execution in current.values():
            if execution.sla_breached_at is not None or now >= execution.sla_due_at:
                breached += 1
            elif execution.sla_warning_at is not None and now >= execution.sla_warning_at:
                warning += 1
        return {"warning": warning, "breached": breached}

    def build_tracker(self, instance, *, submitted_step_ids, transitioned_from_ids):
        steps = list(
            instance.workflow.steps.filter(is_active=True).order_by("order")
        )
        completed_ids = {
            step_id
            for instance_id, step_id in submitted_step_ids
            if instance_id == instance.pk
        }
        completed_ids.update(
            step_id
            for instance_id, step_id in transitioned_from_ids
            if instance_id == instance.pk
        )
        tracker = []
        for step in steps:
            if instance.status == WorkflowInstance.Status.COMPLETED:
                state = "completed"
            elif instance.status in {
                WorkflowInstance.Status.CANCELLED,
                WorkflowInstance.Status.SUSPENDED,
            }:
                state = "current" if step.pk == instance.current_step_id else "future"
            elif step.pk == instance.current_step_id:
                state = "current"
            elif step.pk in completed_ids:
                state = "completed"
            else:
                state = "future"
            tracker.append({"step": step, "state": state})
        return tracker

    def _get_recent_activity(self):
        return []
