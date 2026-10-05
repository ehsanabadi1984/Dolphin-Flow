from django.db.models import Exists, OuterRef, Q, Subquery

from .models import (
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowTransitionExecution,
)


class PendingAcceptanceQueueService:
    """
    Query service for acceptance-required transition executions that are
    currently pending and actionable by the given user.

    This service only discovers pending work. It does not resolve the
    transition, change the workflow state, start SLA, or send notifications.
    """

    def __init__(self, user):
        self.user = user

    def get_queryset(self):
        if not self.user or not self.user.is_authenticated or not self.user.is_active:
            return WorkflowTransitionExecution.objects.none()

        active_memberships = WorkflowMembership.objects.filter(
            user=self.user,
            is_active=True,
            workflow_id=OuterRef("instance__workflow_id"),
        )

        base_permissions = WorkflowPermission.objects.filter(
            workflow_id=OuterRef("instance__workflow_id"),
            step_id=OuterRef("transition__to_step_id"),
            action=WorkflowPermission.Action.STEP_ACTION,
        )

        role_membership = WorkflowMembership.objects.filter(
            user=self.user,
            is_active=True,
            workflow_id=OuterRef("workflow_id"),
            role=OuterRef("role"),
        )

        def permission_exists(*, action_code, effect):
            return Exists(
                base_permissions.filter(
                    action_code=action_code,
                    effect=effect,
                ).filter(
                    Q(user=self.user)
                    | Q(
                        user__isnull=True,
                        role__isnull=False,
                    )
                ).annotate(
                    matching_membership=Exists(role_membership),
                ).filter(
                    Q(user=self.user)
                    | Q(matching_membership=True),
                )
            )

        def effective_permission_q(action_code):
            user_deny = Exists(
                base_permissions.filter(
                    user=self.user,
                    action_code=action_code,
                    effect=WorkflowPermission.Effect.DENY,
                )
            )
            user_allow = Exists(
                base_permissions.filter(
                    user=self.user,
                    action_code=action_code,
                    effect=WorkflowPermission.Effect.ALLOW,
                )
            )
            role_deny = permission_exists(
                action_code=action_code,
                effect=WorkflowPermission.Effect.DENY,
            )
            role_allow = permission_exists(
                action_code=action_code,
                effect=WorkflowPermission.Effect.ALLOW,
            )

            return (
                ~user_deny
                & (
                    user_allow
                    | (
                        ~user_allow
                        & ~role_deny
                        & role_allow
                    )
                )
            )

        return (
            WorkflowTransitionExecution.objects
            .filter(
                Exists(active_memberships),
                status=WorkflowTransitionExecution.Status.PENDING,
                transition__requires_acceptance=True,
                transition__is_active=True,
                transition__to_step__isnull=False,
                transition__to_step__is_active=True,
                transition__workflow__is_active=True,
                instance__status=WorkflowInstance.Status.ACTIVE,
                instance__workflow__is_active=True,
            )
            .filter(
                effective_permission_q("ACCEPT")
                | effective_permission_q("REJECT")
            )
            .select_related(
                "instance",
                "instance__workflow",
                "instance__current_step",
                "transition",
                "transition__from_step",
                "transition__to_step",
                "transition__reject_to_step",
                "performed_by",
            )
            .order_by("performed_at", "pk")
        )
