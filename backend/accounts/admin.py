from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import User, UserContactMethod


class UserContactMethodInline(admin.StackedInline):
    fk_name = "user"
    model = UserContactMethod
    extra = 0
    fields = (
        "channel_type",
        "value",
        "is_active",
        "is_verified",
        "verification_method",
        "verified_at",
        "verified_by",
    )
    readonly_fields = (
        "verification_method",
        "verified_at",
        "verified_by",
    )


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = (UserContactMethodInline,)

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

    def save_formset(self, request, form, formset, change):
        if formset.model is not UserContactMethod:
            return super().save_formset(request, form, formset, change)

        instances = formset.save(commit=False)
        for deleted_object in formset.deleted_objects:
            deleted_object.delete()

        for contact_form in formset.forms:
            contact = contact_form.instance
            if contact not in instances:
                continue

            if "is_verified" in contact_form.changed_data and contact.is_verified:
                contact.verification_method = (
                    UserContactMethod.VerificationMethod.MANUAL
                )
                contact.verified_by = request.user
                contact.verified_at = timezone.now()
                contact.verification_code_hash = ""
                contact.verification_expires_at = None
                contact.verification_sent_at = None
                contact.verification_attempts = 0

            contact.save()

        formset.save_m2m()

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
