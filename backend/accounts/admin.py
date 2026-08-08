from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):

    list_display = (
        "username",
        "first_name",
        "last_name",
        "email",
        "is_active",
    )

    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
    )

    search_fields = (
        "username",
        "first_name",
        "last_name",
        "email",
    )

    fieldsets = (
        (None, {
            "fields": (
                "username",
                "password",
            ),
        }),
        ("Personal information", {
            "fields": (
                "first_name",
                "last_name",
                "email",
            ),
        }),
        ("Permissions", {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            ),
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "username",
                "password1",
                "password2",
                "first_name",
                "last_name",
                "email",
                "is_active",
            ),
        }),
    )

    ordering = ("username",)

    def _is_system_admin(self, request):
        return (
            request.user.is_authenticated
            and request.user.is_superuser
            and request.user.is_active
        )

    def has_module_permission(self, request):
        return self._is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return self._is_system_admin(request)

    def has_add_permission(self, request):
        return self._is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return self._is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_system_admin(request)

    def save_model(self, request, obj, form, change):
        if not self._is_system_admin(request):
            raise PermissionDenied

        if not change:
            # Operational users must not receive Django Admin access.
            obj.is_staff = False
            obj.is_superuser = False

        else:
            # A System Admin cannot remove their own superuser status.
            if obj.pk == request.user.pk:
                obj.is_staff = True
                obj.is_superuser = True

            # An existing superuser cannot be demoted through this interface.
            elif (
                User.objects.filter(
                    pk=obj.pk,
                    is_superuser=True,
                ).exists()
                and not obj.is_superuser
            ):
                raise PermissionDenied

        super().save_model(request, obj, form, change)
