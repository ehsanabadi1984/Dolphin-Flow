from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import WorkflowPermission


class WorkflowAuthorizationService:
    """
    Centralized authorization service for Workflow operations.

    Authorization is resolved using:
        1. Explicit user permission
        2. Role-based permission
        3. Instance-level implicit permissions
           (e.g. the user who started an instance
            may implicitly VIEW that instance)
        4. Deny by default

    Explicit DENY always overrides ALLOW
    at the same authorization level.
    """

    @staticmethod
    def has_permission(
        *,
        user,
        workflow,
        action,
        step=None,
        transition=None,
        instance=None,
    ):
        """
        Return True if the user is authorized to perform
        the requested action.

        When ``instance`` is provided and ``action`` is VIEW,
        the user who started the instance is implicitly
        authorized to view it — without requiring an
        explicit VIEW permission record.
        """

        # -----------------------------------------------------
        # 1. Basic user validation
        # -----------------------------------------------------

        if not user or not user.is_authenticated:
            return False

        if not user.is_active:
            return False

        if not workflow or not workflow.is_active:
            return False

        # -----------------------------------------------------
        # 2. Collect active workflow roles
        # -----------------------------------------------------

        roles = list(
            workflow.memberships.filter(
                user=user,
                is_active=True,
            ).values_list(
                "role",
                flat=True,
            )
        )

        # No membership means no workflow authorization.
        if not roles:
            return False

        # -----------------------------------------------------
        # 3. Base permission queryset
        # -----------------------------------------------------

        permissions = WorkflowPermission.objects.filter(
            workflow=workflow,
            action=action,
        )

        # -----------------------------------------------------
        # 4. Resolve authorization scope
        # -----------------------------------------------------

        if transition is not None:

            if transition.workflow_id != workflow.id:
                return False

            permissions = permissions.filter(
                transition=transition,
            )

        elif step is not None:

            if step.workflow_id != workflow.id:
                return False

            permissions = permissions.filter(
                step=step,
            )

        else:
            permissions = permissions.filter(
                step__isnull=True,
                transition__isnull=True,
            )

        # -----------------------------------------------------
        # 5. Explicit user permissions
        # -----------------------------------------------------

        user_permissions = permissions.filter(
            user=user,
        )

        if user_permissions.filter(
            effect=WorkflowPermission.Effect.DENY,
        ).exists():
            return False

        if user_permissions.filter(
            effect=WorkflowPermission.Effect.ALLOW,
        ).exists():
            return True

        # -----------------------------------------------------
        # 6. Role-based permissions
        # -----------------------------------------------------

        role_permissions = permissions.filter(
            role__in=roles,
            user__isnull=True,
        )

        if role_permissions.filter(
            effect=WorkflowPermission.Effect.DENY,
        ).exists():
            return False

        if role_permissions.filter(
            effect=WorkflowPermission.Effect.ALLOW,
        ).exists():
            return True

        # -----------------------------------------------------
        # 7. Instance-level implicit permissions
        # -----------------------------------------------------
        #
        # The user who started a WorkflowInstance is
        # implicitly authorized to VIEW that specific
        # instance, without an explicit VIEW permission.
        #
        # This does NOT create a database record and
        # does NOT grant access to other instances.
        #
        # Explicit DENY (checked above in steps 5–6)
        # always takes precedence over this implicit
        # grant.

        if (
            action == WorkflowPermission.Action.VIEW
            and instance is not None
            and instance.started_by_id == user.pk
        ):
            return True

        # -----------------------------------------------------
        # 8. Deny by default
        # -----------------------------------------------------

        return False

    @staticmethod
    def require_permission(
        *,
        user,
        workflow,
        action,
        step=None,
        transition=None,
        instance=None,
    ):
        """
        Require authorization.

        Raises PermissionDenied when the user is not authorized.
        """

        allowed = WorkflowAuthorizationService.has_permission(
            user=user,
            workflow=workflow,
            action=action,
            step=step,
            transition=transition,
            instance=instance,
        )

        if not allowed:
            raise PermissionDenied(
                "کاربر اجازه انجام این عملیات را ندارد."
            )
            
        return True


    @staticmethod
    def get_startable_workflows(user):
        """
        Return a queryset of active Workflow objects
        that the user is authorized to start.

        A workflow is startable if:
          1. The workflow is active.
          2. The user has an active membership.
          3. The user has effective START permission
             (no explicit DENY overrides).
        """
        from .models import Workflow, WorkflowMembership

        if not user or not user.is_authenticated:
            return Workflow.objects.none()

        if not user.is_active:
            return Workflow.objects.none()

        # Get workflows where user has active membership.
        workflows = Workflow.objects.filter(
            is_active=True,
            memberships__user=user,
            memberships__is_active=True,
        ).distinct()

        startable = []

        for workflow in workflows:
            if WorkflowAuthorizationService.has_permission(
                user=user,
                workflow=workflow,
                action=WorkflowPermission.Action.START,
            ):
                startable.append(workflow.pk)

        return Workflow.objects.filter(pk__in=startable)

    @staticmethod
    def get_allowed_transitions(
        *,
        user,
        workflow,
        from_step,
    ):
        """
        Return active transitions from the given step
        that the user is authorized to execute.
        """

        transitions = (
            workflow.transitions
            .filter(
                from_step=from_step,
                is_active=True,
            )
            .select_related(
                "from_step",
                "to_step",
            )
        )

        return [
            transition
            for transition in transitions
            if WorkflowAuthorizationService.has_permission(
                user=user,
                workflow=workflow,
                action=WorkflowPermission.Action.TRANSITION,
                transition=transition,
            )
        ]