from django.core.exceptions import PermissionDenied

from .models import WorkflowPermission


class WorkflowAuthorizationService:
    """
    Centralized authorization service for Workflow operations.

    Authorization is resolved using:
        1. Explicit user permission
        2. Role-based permission
        3. Deny by default

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
    ):
        """
        Return True if the user is authorized to perform
        the requested action.
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
        # 7. Deny by default
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
        )

        if not allowed:
            raise PermissionDenied(
                "کاربر اجازه انجام این عملیات را ندارد."
            )

        return True