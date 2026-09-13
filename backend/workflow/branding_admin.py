from django.contrib import admin

from .admin import dolphin_admin_site
from .branding_models import SystemBranding


@admin.register(SystemBranding, site=dolphin_admin_site)
class SystemBrandingAdmin(admin.ModelAdmin):
    admin_category = "system"
    admin_section = "configuration"

    fieldsets = (
        (
            "نام و هویت سیستم",
            {
                "fields": (
                    "system_name",
                    "short_name",
                    "browser_title",
                    "sidebar_subtitle",
                )
            },
        ),
        (
            "نشان و آیکون",
            {
                "fields": (
                    "primary_logo",
                    "sidebar_logo",
                    "sidebar_symbol",
                    "favicon",
                    "logo_alt_text",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return not SystemBranding.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff
