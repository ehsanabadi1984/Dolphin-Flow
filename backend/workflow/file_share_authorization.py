from django.core.exceptions import PermissionDenied

from .models import FormField


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


def can_share_file_field(*, user, field):
    """Check the phase-one permission and field-level sharing switch."""
    return bool(
        has_direct_share_files_permission(user)
        and field
        and field.field_type == FormField.FieldType.FILE
        and field.allow_file_sharing
    )


def require_file_share_permission(*, user, field):
    """Raise PermissionDenied unless the user may share this file field."""
    if not can_share_file_field(user=user, field=field):
        raise PermissionDenied(
            "کاربر اجازه اشتراک‌گذاری فایل این فیلد را ندارد."
        )
    return True
