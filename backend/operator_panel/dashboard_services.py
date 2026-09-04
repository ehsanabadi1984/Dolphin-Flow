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
    VIEW resolution depends on the instance's current step:

      * current step set   -> step-scoped rows (step = current step)
      * current step None  -> workflow-level rows (step IS NULL AND
                              transition IS NULL)

    `has_permission` never mixes the two scopes, so both annotation
    sets are computed and the final Q expression selects the one that
    applies to each instance row.
    """
    annotations = {}
    for scope, suffix in (("step", "view"), ("wf", "view_wf")):
        kwargs = {"step_scope": True} if scope == "step" else {"wf_scope": True}
        annotations.update({
            f"_df_{suffix}_user_allow": _user_permission_exists(
                user,
                WorkflowPermission.Action.VIEW,
                WorkflowPermission.Effect.ALLOW,
                **kwargs,
            ),
            f"_df_{suffix}_user_deny": _user_permission_exists(
                user,
                WorkflowPermission.Action.VIEW,
                WorkflowPermission.Effect.DENY,
                **kwargs,
            ),
            f"_df_{suffix}_role_allow": _role_permission_exists(
                user,
                WorkflowPermission.Action.VIEW,
                WorkflowPermission.Effect.ALLOW,
                **kwargs,
            ),
            f"_df_{suffix}_role_deny": _role_permission_exists(
                user,
                WorkflowPermission.Action.VIEW,
                WorkflowPermission.Effect.DENY,
                **kwargs,
            ),
        })
    return annotations


def _transition_permission_annotation(user, effect, *, role_scoped, roles):
    """
    Exists over TRANSITION permission rows pinned to the *same*
    transition row (OuterRef("pk") of the correlated WorkflowTransition
    subquery). This keeps DENY/ALLOW resolution per transition, exactly
    like has_permission(transition=t) which `get_allowed_transitions`
    calls for every candidate transition.
    """
    queryset = WorkflowPermission.objects.filter(
        workflow_id=OuterRef("workflow_id"),
        action=WorkflowPermission.Action.TRANSITION,
        effect=effect,
        transition_id=OuterRef("pk"),
    )
    if role_scoped:
        queryset = queryset.filter(
            user__isnull=True,
            role__in=roles,
        )
    else:
        queryset = queryset.filter(user=user)
    return Exists(queryset)


def _transition_granted_annotation(user):
    """
    "There is at least one active transition from the instance's current
    step that the user may execute."

    Mirrors `get_allowed_transitions` exactly: for every candidate
    transition has_permission is resolved per transition (user DENY >
    user ALLOW > role DENY > role ALLOW > deny) and the annotation is
    true when any candidate passes.
    """
    roles = _roles_subquery(user)

    user_deny = _transition_permission_annotation(
        user,
        WorkflowPermission.Effect.DENY,
        role_scoped=False,
        roles=roles,
    )
    user_allow = _transition_permission_annotation(
        user,
        WorkflowPermission.Effect.ALLOW,
        role_scoped=False,
        roles=roles,
    )
    role_deny = _transition_permission_annotation(
        user,
        WorkflowPermission.Effect.DENY,
        role_scoped=True,
        roles=roles,
    )
    role_allow = _transition_permission_annotation(
        user,
        WorkflowPermission.Effect.ALLOW,
        role_scoped=True,
        roles=roles,
    )

    return Exists(
        WorkflowTransition.objects
        .filter(
            workflow_id=OuterRef("workflow_id"),
            from_step_id=OuterRef("current_step_id"),
            is_active=True,
        )
        .filter(
            ~user_deny
            & (user_allow | (~role_deny & role_allow))
        )
    )


def _actionability_annotations(user):
    """
    Boolean annotations mirroring WorkflowAuthorizationService for the
    three actions the dashboard depends on:
      * VIEW      — required to reach the instance view
      * EXECUTE   — required to act on the current step
      * TRANSITION— required to run a transition from the current step
    """
    return {
        "_df_member": _membership_exists(user),
        **_execute_annotations(user),
        **_view_annotations(user),
        "_df_transition_granted": _transition_granted_annotation(user),
    }


def _deny_allow_q(*, prefix, allow_starter=False, user_pk=None):
    """
    has_permission precedence for one permission action scope:

        user DENY  >  user ALLOW  >  role DENY  >  role ALLOW

    plus, when ``allow_starter``, the implicit instance-starter VIEW
    grant only after every ALLOW/DENY row (role DENY blocks the starter).
    """
    user_deny = Q(**{f"_df_{prefix}_user_deny": True})
    user_allow = Q(**{f"_df_{prefix}_user_allow": True})
    role_deny = Q(**{f"_df_{prefix}_role_deny": True})
    role_allow = Q(**{f"_df_{prefix}_role_allow": True})

    q = ~user_deny & (
        user_allow
        | (
            ~role_deny
            & (
                role_allow
                | (Q(started_by_id=user_pk) if allow_starter else Q(pk__isnull=True))
            )
        )
    )
    return q


def _can_view_q(user):
    """
    Q expression for effective VIEW permission on the instance,
    matching has_permission(VIEW, step=current_step, instance=instance)
    — the exact check the instance view enforces. Workflow-active and
    membership requirements are applied by the querysets that use this
    expression (or by _df_member).
    """
    step_scope = _deny_allow_q(
        prefix="view",
        allow_starter=True,
        user_pk=user.pk,
    )
    wf_scope = _deny_allow_q(
        prefix="view_wf",
        allow_starter=True,
        user_pk=user.pk,
    )
    return Q(_df_member=True) & (
        (Q(current_step_id__isnull=False) & step_scope)
        | (Q(current_step_id__isnull=True) & wf_scope)
    )


def _can_take_action_q(user):
    """
    "The user can legally reach the instance view AND can take an
    action on it" — VIEW (as enforced by the destination view) plus
    EXECUTE or an allowed transition. Rows are never advertised when
    the destination instance view would deny access.
    """
    execute = _deny_allow_q(prefix="execute")
    return _can_view_q(user) & (
        execute | Q(_df_transition_granted=True)
    )


class DashboardService:
    """Build the operator dashboard from the existing workflow domain."""

    def __init__(self, user):
        self.user = user
        self._counts = None

    # ---------------------------------------------------------
    # Shared querysets
    # ---------------------------------------------------------

    @staticmethod
    def meaningful_instance_queryset(user):
        """
        Non-draft instances started by ``user``, excluding abandoned
        starts (an ACTIVE instance still sitting on the first step with
        no saved data, device, or transition). This is the ownership
        concept shared by the "my processes" page, the sidebar badge,
        and the dashboard panels.
        """
        if not user or not user.is_authenticated:
            return WorkflowInstance.objects.none()

        first_step_id = Subquery(
            WorkflowStep.objects
            .filter(
                workflow_id=OuterRef("workflow_id"),
                is_active=True,
            )
            .order_by("order")
            .values("pk")[:1]
        )

        has_form_data = Exists(
            FormData.objects.filter(instance_id=OuterRef("pk"))
        )
        has_active_device = Exists(
            InstanceDevice.objects.filter(
                instance_id=OuterRef("pk"),
                is_active=True,
            )
        )
        has_transition = Exists(
            WorkflowTransitionExecution.objects.filter(
                instance_id=OuterRef("pk"),
            )
        )

        abandoned_start = (
            Q(
                status=WorkflowInstance.Status.ACTIVE,
                current_step_id=first_step_id,
            )
            & ~has_form_data
            & ~has_active_device
            & ~has_transition
        )

        return (
            WorkflowInstance.objects
            .filter(started_by=user)
            .exclude(status=WorkflowInstance.Status.DRAFT)
            .exclude(abandoned_start)
            .select_related("workflow", "current_step")
        )

    def my_processes_queryset(self):
        """
        Canonical "فرآیندهای من" population.

        Instances the user started (meaningful, non-abandoned) in an
        active workflow that the user can still open — i.e. effective
        VIEW holds for the exact authorization the instance view
        enforces. Every row of the my_processes destination page comes
        from this queryset, so a listed row is always reachable, and the
        sidebar badge counts exactly the ACTIVE rows of this population.
        """
        return (
            DashboardService.meaningful_instance_queryset(self.user)
            .filter(workflow__is_active=True)
            .annotate(**_actionability_annotations(self.user))
            .filter(_can_view_q(self.user))
            .order_by("-started_at")
        )

    def _my_active_queryset(self):
        """The user's own ACTIVE meaningful processes they can open."""
        return self.my_processes_queryset().filter(
            status=WorkflowInstance.Status.ACTIVE,
        )

    def _accessible_active_queryset(self):
        """
        ACTIVE instances in active workflows that the user may need to
        act on (any starter, active membership required by the
        authorization predicates), annotated with the full actionability
        state.
        """
        return (
            WorkflowInstance.objects
            .filter(
                status=WorkflowInstance.Status.ACTIVE,
                workflow__is_active=True,
            )
            .annotate(**_actionability_annotations(self.user))
            .select_related("workflow", "current_step")
            .order_by("-started_at")
        )

    # ---------------------------------------------------------
    # Counts (single source of truth for sidebar + dashboard KPIs)
    # ---------------------------------------------------------

    def get_sidebar_counts(self):
        """
        The three sidebar counters, computed from the complete matching
        population with database-side filtering:

          active  — the user's own meaningful ACTIVE processes they can
                    open (== the ACTIVE rows of my_processes)
          tasks   — accessible ACTIVE instances assigned to the user
                    that they can actually act on
          pending — accessible ACTIVE instances not assigned to the user
                    that they can act on
        """
        if self._counts is None:
            self._counts = self._compute_sidebar_counts()
        return self._counts

    def _compute_sidebar_counts(self):
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

    # ---------------------------------------------------------
    # Dashboard context
    # ---------------------------------------------------------

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
                "today": my_instances.filter(
                    started_at__date=today,
                ).count(),
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
            "pending_actions": self._pending_instances(
                exclude_assigned=True,
            ),
            "my_tasks": self._pending_instances(assigned_only=True),
            "recent_activity": self._get_recent_activity(),
            "startable_workflows": (
                WorkflowAuthorizationService
                .get_startable_workflows(self.user)
                .order_by("name")
            ),
            # Reused by the sidebar template tag on the dashboard request
            # so the counters are not recomputed.
            "sidebar_counts": counts,
        }

    def _pending_instances(self, *, assigned_only=False, exclude_assigned=False):
        """
        Bounded list of actionable accessible ACTIVE instances.

        The counts always come from the full population (see
        ``get_sidebar_counts``); this method only builds the capped list
        rendered on the dashboard, so an older matching instance beyond
        the newest rows still counts correctly.
        """
        queryset = self._accessible_active_queryset().filter(
            _can_take_action_q(self.user),
        )

        if assigned_only:
            queryset = queryset.filter(
                current_step__assigned_to_id=self.user.pk,
            )
        elif exclude_assigned:
            queryset = queryset.exclude(
                current_step__assigned_to_id=self.user.pk,
            )

        return list(queryset[:PENDING_LIST_LIMIT])

    # ---------------------------------------------------------
    # Per-instance detailed state (tracker + SLA) for the
    # bounded active-process panel
    # ---------------------------------------------------------

    def _attach_dashboard_state(self, instances, *, now):
        if not instances:
            return

        instance_ids = [instance.pk for instance in instances]

        executions = (
            WorkflowStepExecution.objects
            .filter(
                instance_id__in=instance_ids,
                is_submitted=False,
            )
            .select_related("workflow_step")
            .order_by("-performed_at")
        )

        current_executions = {}
        for execution in executions:
            current_executions.setdefault(execution.instance_id, execution)

        submitted_step_ids = set(
            WorkflowStepExecution.objects
            .filter(
                instance_id__in=instance_ids,
                is_submitted=True,
            )
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
        elif (
            execution.sla_warning_at is not None
            and now >= execution.sla_warning_at
        ):
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
        """
        Aggregate SLA warning/breach counts over the complete population
        of accessible ACTIVE instances, database side — not capped by any
        presentation limit.

        Only the latest unsubmitted SLA-tracked execution of each
        instance contributes, matching the per-instance SLA state.
        """
        latest_sla_execution = (
            WorkflowStepExecution.objects
            .filter(
                instance_id=OuterRef("instance_id"),
                is_submitted=False,
                sla_due_at__isnull=False,
                sla_completed_at__isnull=True,
            )
            .order_by("-performed_at")
            .values("pk")[:1]
        )

        member = Exists(
            WorkflowMembership.objects.filter(
                workflow_id=OuterRef("instance__workflow_id"),
                user=self.user,
                is_active=True,
            )
        )

        executions = (
            WorkflowStepExecution.objects
            .filter(
                pk=Subquery(latest_sla_execution),
                instance__status=WorkflowInstance.Status.ACTIVE,
            )
            .filter(member)
        )

        breached = executions.filter(
            Q(sla_breached_at__isnull=False)
            | Q(sla_due_at__lte=now),
        ).count()

        warning = executions.filter(
            sla_breached_at__isnull=True,
            sla_due_at__gt=now,
            sla_warning_at__isnull=False,
            sla_warning_at__lte=now,
        ).count()

        return {"warning": warning, "breached": breached}

    # ---------------------------------------------------------
    # Activity + tracker helpers
    # ---------------------------------------------------------

    def _get_recent_activity(self, limit=10):
        transitions = list(
            WorkflowTransitionExecution.objects
            .filter(
                instance__workflow__memberships__user=self.user,
                instance__workflow__memberships__is_active=True,
            )
            .select_related(
                "instance",
                "instance__workflow",
                "transition",
                "transition__from_step",
                "transition__to_step",
                "performed_by",
            )
            .distinct()
            .order_by("-performed_at")[:limit]
        )

        step_executions = list(
            WorkflowStepExecution.objects
            .filter(
                instance__workflow__memberships__user=self.user,
                instance__workflow__memberships__is_active=True,
                is_submitted=True,
            )
            .select_related(
                "instance",
                "instance__workflow",
                "workflow_step",
                "performed_by",
            )
            .distinct()
            .order_by("-submitted_at", "-performed_at")[:limit]
        )

        activities = []
        for item in transitions:
            if item.transition.to_step:
                title = (
                    f"فرآیند «{item.instance.workflow.name}» "
                    f"به «{item.transition.to_step.name}» منتقل شد"
                )
            else:
                title = f"فرآیند «{item.instance.workflow.name}» تکمیل شد"

            activities.append({
                "title": title,
                "meta": (
                    f"فرآیند #{item.instance.pk} · "
                    f"توسط {item.performed_by.get_full_name() or item.performed_by.username}"
                ),
                "performed_at": item.performed_at,
            })

        for item in step_executions:
            activities.append({
                "title": (
                    f"مرحله «{item.workflow_step.name}» "
                    f"در فرآیند «{item.instance.workflow.name}» ثبت شد"
                ),
                "meta": (
                    f"فرآیند #{item.instance.pk} · "
                    f"توسط {item.performed_by.get_full_name() or item.performed_by.username}"
                ),
                "performed_at": item.submitted_at or item.performed_at,
            })

        return sorted(
            activities,
            key=lambda item: item["performed_at"],
            reverse=True,
        )[:limit]

    def build_tracker(self, instance, *, submitted_step_ids=None, transitioned_from_ids=None):
        steps = list(
            instance.workflow.steps
            .filter(is_active=True)
            .order_by("order")
        )

        if submitted_step_ids is None or transitioned_from_ids is None:
            submitted_step_ids = set(
                WorkflowStepExecution.objects
                .filter(
                    instance=instance,
                    is_submitted=True,
                )
                .values_list("instance_id", "workflow_step_id")
            )
            transitioned_from_ids = set(
                WorkflowTransitionExecution.objects
                .filter(instance=instance)
                .values_list("instance_id", "transition__from_step_id")
            )

        completed_ids = set()
        for step in steps:
            if (
                (instance.pk, step.pk) in submitted_step_ids
                or (instance.pk, step.pk) in transitioned_from_ids
            ):
                completed_ids.add(step.pk)

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

            tracker.append({
                "step": step,
                "state": state,
            })

        return tracker
