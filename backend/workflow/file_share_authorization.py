from django.core.exceptions import PermissionDenied

from .models import FormField, WorkflowPermission


SHARE_FILES_PERMISSION = "share_files"


def has_direct_share_files_permission(user):
    """
    Return whether an active authenticated user has the permission directly.

    Django's user.has_perm() also considers group permissions, which is
    intentionally not sufficient for file sharing.
    """
    if (
        not user
        or not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
    ):
        return False

    if user.is_superuser:
        return True

    user_model = user._meta
    return user.user_permissions.filter(
        codename=SHARE_FILES_PERMISSION,
        content_type__app_label=user_model.app_label,
        content_type__model=user_model.model_name,
    ).exists()


def has_step_share_files_permission(*, user, workflow, step):
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    if not workflow or not step or step.workflow_id != workflow.pk:
        return False
    rules = WorkflowPermission.objects.filter(workflow=workflow, step=step, user=user, action=WorkflowPermission.Action.SHARE_FILES, action_code__isnull=True, transition__isnull=True)
    if rules.filter(effect=WorkflowPermission.Effect.DENY).exists():
        return False
    return rules.filter(effect=WorkflowPermission.Effect.ALLOW).exists()

def can_share_file_field(*, user, field):
    """Check the phase-one permission and field-level sharing switch."""
    return bool(
        has_direct_share_files_permission(user)
        and field
        and field.field_type == FormField.FieldType.FILE
        and field.allow_file_sharing
    )


def require_file_share_permission(*, user, field, workflow, step):
    """Require global, step-level, and field-level file-sharing permission."""
    if not (has_direct_share_files_permission(user) and has_step_share_files_permission(user=user, workflow=workflow, step=step) and field and field.field_type == FormField.FieldType.FILE and field.allow_file_sharing):
        raise PermissionDenied(
            "کاربر اجازه اشتراک‌گذاری فایل این فیلد را ندارد."
        )
    return True
