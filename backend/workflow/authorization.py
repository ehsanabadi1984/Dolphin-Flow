from django.core.exceptions import PermissionDenied

from .models import WorkflowPermission


class WorkflowAuthorizationService:

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
        Check whether a user is allowed to perform an action
        within a workflow.

        Permission resolution order:

        1. Explicit user permission
        2. Workflow role permission
        3. Deny by default
        """

        # ---------------------------------------------------------
        # 1. Basic user validation
        # ---------------------------------------------------------

        if not user or not user.is_authenticated:
            return False

        if not user.is_active:
            return False

        # ---------------------------------------------------------
        # 2. Collect active workflow roles
        # ---------------------------------------------------------

        memberships = workflow.memberships.filter(
            user=user,
            is_active=True,
        )

        roles = list(
            memberships.values_list(
                "role",
                flat=True,
            )
        )

        # ---------------------------------------------------------
        # 3. Find applicable permissions
        # ---------------------------------------------------------

        permissions = WorkflowPermission.objects.filter(
            workflow=workflow,
            action=action,
        )

        if step is not None:
            permissions = permissions.filter(
                step=step,
            )

        elif transition is not None:
            permissions = permissions.filter(
                transition=transition,
            )

        else:
            permissions = permissions.filter(
                step__isnull=True,
                transition__isnull=True,
            )

        # ---------------------------------------------------------
        # 4. User-specific permissions
        # ---------------------------------------------------------

        user_permissions = permissions.filter(
            user=user,
        )

        explicit_deny = user_permissions.filter(
            effect=WorkflowPermission.Effect.DENY,
        ).exists()

        if explicit_deny:
            return False

        explicit_allow = user_permissions.filter(
            effect=WorkflowPermission.Effect.ALLOW,
        ).exists()

        if explicit_allow:
            return True

        # ---------------------------------------------------------
        # 5. Role-based permissions
        # ---------------------------------------------------------

        if roles:
            role_permissions = permissions.filter(
                role__in=roles,
                user__isnull=True,
            )

            role_deny = role_permissions.filter(
                effect=WorkflowPermission.Effect.DENY,
            ).exists()

            if role_deny:
                return False

            role_allow = role_permissions.filter(
                effect=WorkflowPermission.Effect.ALLOW,
            ).exists()

            if role_allow:
                return True

        # ---------------------------------------------------------
        # 6. Deny by default
        # ---------------------------------------------------------

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
        Require permission or raise PermissionDenied.
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