from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from django.template import Context
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.core.exceptions import PermissionDenied

import json

from .form_workspace import get_valid_parent_group_queryset
from .sms_provider_registry import (
    activate_provider,
    build_provider,
    create_provider_revision,
    register_provider,
)

from .models import (
    Workflow,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepSMSRule,
    WorkflowSMSSettings,
    SMSProviderConfiguration,
    SMSTemplate,
    SMSDelivery,
    WorkflowStepExecution,
    WorkflowInstance,
    WorkflowTransition,
    WorkflowTransitionExecution,
    WorkflowPermission,
    WorkflowStepSLA,

    DeviceType,
    DeviceModel,
    Device,
    DeviceIdentifier,

    FormDefinition,
    FormSection,
    FormRepeatableGroup,
    RepeatableGroupAccess,
    FormField,
    FieldAccess,
    FormData,
    FormPrintSettings,
    FormPrintSectionSettings,
    FormPrintFieldSettings,

    BusinessCalendar,
    WeeklySchedule,
    WorkingInterval,
    CalendarException,
    CalendarExceptionInterval,

    LookupList,
    LookupItem,
    StaticChoiceSet,
    StaticChoiceItem,
)




class DolphinAdminSite(AdminSite):

    def index(self, request, extra_context=None):
        return super().index(
            request,
            extra_context,
        )

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(
            request,
            app_label,
        )

        for app in app_list:
            for model in app["models"]:
                model_admin = self._registry.get(
                    model["model"]
                )

                if model_admin:
                    model["admin_category"] = getattr(
                        model_admin,
                        "admin_category",
                        None,
                    )

                    model["admin_section"] = getattr(
                        model_admin,
                        "admin_section",
                        None,
                    )

        return app_list

dolphin_admin_site = DolphinAdminSite(
    name="dolphin_admin"
)
User = get_user_model()

if User not in dolphin_admin_site._registry:
    dolphin_admin_site.register(
        User,
        admin.site._registry[User].__class__,
    )

if Group not in dolphin_admin_site._registry:
    dolphin_admin_site.register(
        Group,
        admin.site._registry[Group].__class__,
    )

# ============================================================
# Dolphin Flow Admin Architecture
# ============================================================

ADMIN_CATEGORIES = {
    "workflows": {
        "label": "فرآیندها",
        "description": (
            "تعریف Workflow، مراحل، Transitionها، "
            "اعضا و دسترسی‌های فرآیند"
        ),
        "icon": "⚙",
        "order": 10,
    },

    "forms": {
        "label": "فرم‌ها",
        "description": (
            "تعریف ساختار فرم‌ها، Sectionها، "
            "Fieldها و گروه‌های تکرارشونده"
        ),
        "icon": "🧩",
        "order": 20,
    },

    "devices": {
        "label": "دستگاه‌ها",
        "description": (
            "مدیریت انواع دستگاه، مدل‌ها، "
            "دستگاه‌ها و شناسه‌های آن‌ها"
        ),
        "icon": "📱",
        "order": 30,
    },

    "sla": {
        "label": "SLA و زمان‌بندی",
        "description": (
            "مدیریت SLA، تقویم‌های کاری "
            "و زمان‌بندی فرآیندها"
        ),
        "icon": "⏱",
        "order": 40,
    },

    "executions": {
        "label": "اجرای فرآیند",
        "description": (
            "مشاهده اجرای Workflowها، "
            "Step Execution و Transition Execution"
        ),
        "icon": "▶",
        "order": 50,
    },

    "communications": {
        "label": "ارتباطات",
        "description": (
            "مدیریت Notificationها و "
            "سایر کانال‌های ارتباطی"
        ),
        "icon": "🔔",
        "order": 60,
    },

    "system": {
        "label": "سیستم",
        "description": (
            "تنظیمات عمومی و اجزای زیرساختی "
            "Dolphin Flow"
        ),
        "icon": "🛠",
        "order": 100,
    },
}

from collections import OrderedDict


def build_admin_structure(request):

    structure = OrderedDict()

    for key, category in ADMIN_CATEGORIES.items():

        structure[key] = {
            **category,
            "sections": OrderedDict(),
        }


    app_list = dolphin_admin_site.get_app_list(request)


    for app in app_list:

        for model in app["models"]:

            category = model.get(
                "admin_category"
            )

            section = model.get(
                "admin_section"
            )

            if not category:
                continue


            if not section:
                section = "general"

            if section not in structure[category]["sections"]:

                section_info = ADMIN_SECTIONS.get(
                    section,
                    {
                        "label": section,
                        "order": 999,
                    }
                )

                structure[category]["sections"][section] = {
                    **section_info,
                    "models": [],
                }


            structure[category]["sections"][section]["models"].append(
                model
            )

    return structure

ADMIN_SECTIONS = {
    "general": {
        "label": "عمومی",
        "order": 100,
    },

    "definition": {
        "label": "تعریف و طراحی",
        "order": 10,
    },

    "security": {
        "label": "امنیت و دسترسی",
        "order": 20,
    },

    "execution": {
        "label": "اجرا و مانیتورینگ",
        "order": 30,
    },


    "forms": {
        "designer": {
            "label": "طراحی فرم",
            "icon": "🧩",
            "order": 10,
        },
        "access": {
            "label": "دسترسی فیلدها",
            "icon": "🔐",
            "order": 20,
        },
        "data": {
            "label": "داده‌ها",
            "icon": "📄",
            "order": 30,
        },
    },

    "devices": {
        "catalog": {
            "label": "ساختار دستگاه",
            "icon": "📚",
            "order": 10,
        },
        "inventory": {
            "label": "تجهیزات",
            "icon": "📱",
            "order": 20,
        },
    },

    "sla": {
        "configuration": {
            "label": "تنظیمات SLA",
            "icon": "⏱",
            "order": 10,
        },
    },

    "executions": {
        "history": {
            "label": "سوابق اجرا",
            "icon": "▶",
            "order": 10,
        },
    },

    "communications": {
        "notification": {
            "label": "Notification",
            "icon": "🔔",
            "order": 10,
        },
    },

    "system": {
        "configuration": {
            "label": "تنظیمات سیستم",
            "icon": "🛠",
            "order": 10,
        },
        "backups": {
            "label": "پشتیبان‌گیری",
            "icon": "💾",
            "order": 20,
        },
    },
}


# ============================================================
# Workflow
# ============================================================
def workflow_dynamic_steps(request):
    workflow_id = request.GET.get("workflow_id")

    if not workflow_id:
        return JsonResponse({"results": []})

    steps = (
        WorkflowStep.objects
        .filter(
            workflow_id=workflow_id,
            is_active=True,
        )
        .order_by("order")
    )

    return JsonResponse({
        "results": [
            {
                "id": step.pk,
                "label": f"{step.order}. {step.name}",
            }
            for step in steps
        ]
    })


def workflow_dynamic_transitions(request):
    workflow_id = request.GET.get("workflow_id")

    if not workflow_id:
        return JsonResponse({"results": []})

    transitions = (
        WorkflowTransition.objects
        .filter(
            workflow_id=workflow_id,
            is_active=True,
        )
        .select_related(
            "from_step",
            "to_step",
        )
        .order_by(
            "from_step__order",
            "to_step__order",
        )
    )

    return JsonResponse({
        "results": [
            {
                "id": transition.pk,
                "label": (
                    f"{transition.from_step.name}"
                    f" → "
                    f"{transition.to_step.name}"
                    if transition.to_step
                    else f"{transition.from_step.name}"
                    f" → [تکمیل فرآیند]"
                ),
            }
            for transition in transitions
        ]
    })


class WorkflowMembershipInline(admin.TabularInline):
    model = WorkflowMembership
    extra = 0

    fields = (
        "user",
        "role",
        "is_active",
        "joined_at",
    )

    autocomplete_fields = (
        "user",
    )

    readonly_fields = (
        "joined_at",
    )


class WorkflowStepInline(admin.TabularInline):
    model = WorkflowStep
    extra = 0

    fields = (
        "order",
        "name",
        "description",
        "is_active",
        "code",
    )

    readonly_fields = (
        "code",
    )

    ordering = (
        "order",
    )

class WorkflowTransitionInline(admin.TabularInline):
    model = WorkflowTransition
    extra = 0

    fields = (
        "from_step",
        "to_step",
        "name",
        "is_active",
        "requires_acceptance",
        "reject_to_step",
        "code",
    )

    autocomplete_fields = (
        "from_step",
        "to_step",
        "reject_to_step",
    )

    readonly_fields = (
        "code",
    )

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(
            request,
            obj,
            **kwargs,
        )

        if obj:
            form = formset.form

            form.base_fields["from_step"].queryset = (
                WorkflowStep.objects
                .filter(
                    workflow=obj,
                    is_active=True,
                )
                .order_by("order")
            )

            form.base_fields["to_step"].queryset = (
                WorkflowStep.objects
                .filter(
                    workflow=obj,
                    is_active=True,
                )
                .order_by("order")
            )

            form.base_fields["reject_to_step"].queryset = (
                WorkflowStep.objects
                .filter(
                    workflow=obj,
                    is_active=True,
                )
                .order_by("order")
            )

        return formset

    ordering = (
        "from_step__order",
        "to_step__order",
    )


class WorkflowPermissionInline(admin.TabularInline):
    model = WorkflowPermission
    fk_name = "workflow"
    extra = 0

    fields = (
        "user",
        "role",
        "action",
        "effect",
    )

    autocomplete_fields = (
        "user",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(
                step__isnull=True,
                transition__isnull=True,
            )
            .select_related(
                "user",
                "workflow",
            )
        )

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(
            request,
            obj,
            **kwargs,
        )

        if obj:
            form = formset.form

            form.base_fields["user"].queryset = (
                get_user_model().objects
                .filter(is_active=True)
                .order_by("username")
            )

        return formset


class WorkflowStepPermissionForm(forms.ModelForm):
    class Media:
        js = (
            "workflow/js/workflow-step-permission-admin.js",
        )

    ACTION_CODE_CHOICES = (
        ("ACCEPT", "تأیید دریافت"),
        ("REJECT", "رد دریافت"),
    )

    action_code = forms.ChoiceField(
        label="نوع عملیات مرحله",
        choices=ACTION_CODE_CHOICES,
        required=False,
    )

    class Meta:
        model = WorkflowPermission
        fields = (
            "user",
            "role",
            "action",
            "action_code",
            "effect",
        )

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        action_code = cleaned_data.get("action_code")

        if action == WorkflowPermission.Action.STEP_ACTION:
            if not action_code:
                self.add_error(
                    "action_code",
                    "برای عملیات مرحله باید نوع عملیات انتخاب شود.",
                )
        else:
            cleaned_data["action_code"] = None

        return cleaned_data


class WorkflowStepPermissionInline(admin.TabularInline):
    model = WorkflowPermission
    fk_name = "step"
    extra = 0

    form = WorkflowStepPermissionForm

    fields = (
        "user",
        "role",
        "action",
        "action_code",
        "effect",
    )

    autocomplete_fields = (
        "user",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(
                transition__isnull=True,
                step__isnull=False,
            )
            .select_related(
                "user",
                "step",
            )
        )


class WorkflowTransitionPermissionInline(admin.TabularInline):
    model = WorkflowPermission
    fk_name = "transition"
    extra = 0

    fields = (
        "user",
        "role",
        "action",
        "effect",
    )

    autocomplete_fields = (
        "user",
    )


@admin.register(
    Workflow,
    site=dolphin_admin_site,
)
class WorkflowAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "definition"

    list_display = (
        "name",
        "code",
        "is_active",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "label",
        "code",
        "description",
    )

    readonly_fields = (
        "code",
        "created_at",
        "updated_at",
    )

    ordering = (
        "name",
    )

    inlines = (
        WorkflowMembershipInline,
        WorkflowStepInline,
        WorkflowTransitionInline,
        WorkflowPermissionInline,
    )

# ============================================================
# Workflow Membership
# ============================================================

@admin.register(
    WorkflowMembership,
    site=dolphin_admin_site,
)
class WorkflowMembershipAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "security"

    list_display = (
        "workflow",
        "user",
        "role",
        "is_active",
        "joined_at",
    )

    list_filter = (
        "workflow",
        "role",
        "is_active",
    )

    search_fields = (
        "workflow__name",
        "workflow__code",
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
    )

    autocomplete_fields = (
        "workflow",
        "user",
    )

    readonly_fields = (
        "joined_at",
    )

    ordering = (
        "workflow",
        "user",
    )


# ============================================================
# Workflow Step
# ============================================================

class WorkflowStepSLAInline(admin.StackedInline):
    model = WorkflowStepSLA

    extra = 0
    max_num = 1

    autocomplete_fields = (
        "calendar",
    )

    fieldsets = (
        (
            "تنظیمات SLA",
            {
                "fields": (
                    "calendar",
                    "duration",
                    "warning_before",
                    "is_active",
                ),
            },
        ),
        (
            "اطلاعات سیستمی",
            {
                "classes": (
                    "collapse",
                ),
                "fields": (
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


class WorkflowStepSMSRuleInline(admin.TabularInline):
    model = WorkflowStepSMSRule
    extra = 0
    fields = (
        "notification_type",
        "sms_enabled",
    )
    verbose_name = "قانون ارسال پیامک"
    verbose_name_plural = "قوانین ارسال پیامک بر اساس نوع اعلان"

    def has_view_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        return () if request.user.is_superuser else self.fields


@admin.register(
    WorkflowStep,
    site=dolphin_admin_site,
)
class WorkflowStepAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "definition"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "workflow",
                "sla",
                "sla__calendar",
            )
        )


    @admin.display(
        description="تقویم SLA",
        ordering="sla__calendar__name",
    )
    def sla_calendar(self, obj):
        if not hasattr(obj, "sla"):
            return "—"

        if not obj.sla.is_active:
            return f"{obj.sla.calendar.name} (غیرفعال)"

        return obj.sla.calendar.name

    list_display = (
        "workflow",
        "order",
        "name",
        "code",
        "sla_calendar",
        "is_active",
    )

    list_filter = (
        "workflow",
        "is_active",
    )

    search_fields = (
        "workflow__name",
        "workflow__code",
        "name",
        "code",
        "description",
    )

    readonly_fields = (
        "code",
        "created_at",
        "updated_at",
    )

    ordering = (
        "workflow",
        "order",
    )

    inlines = (
        WorkflowStepSLAInline,
        WorkflowStepPermissionInline,
        WorkflowStepSMSRuleInline,
    )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if (
                isinstance(instance, WorkflowPermission)
                and not instance.workflow_id
                and instance.step_id
            ):
                instance.workflow = (
                    instance.step.workflow
                )
            instance.save()
        formset.save_m2m()



class WorkflowSMSSettingsAdminForm(forms.ModelForm):
    provider_username = forms.CharField(
        label="نام کاربری مگفا", required=False, max_length=255,
    )
    provider_password = forms.CharField(
        label="رمز عبور مگفا", required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "new-password"},
        ),
        help_text="برای حفظ رمز فعلی، این فیلد را خالی بگذارید.",
    )
    provider_domain = forms.CharField(
        label="دامنه مگفا", required=False, max_length=255,
    )
    provider_sender = forms.CharField(
        label="شماره فرستنده", required=False, max_length=255,
    )
    provider_api_base_url = forms.URLField(
        label="آدرس API", required=False,
    )
    provider_timeout = forms.IntegerField(
        label="مهلت اتصال (ثانیه)", required=False, min_value=1,
    )

    class Meta:
        model = WorkflowSMSSettings
        fields = ("is_enabled",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        provider = SMSProviderConfiguration.objects.filter(code="magfa").first()
        revision = (
            provider.revisions.filter(is_current=True).first()
            if provider else None
        )
        self._sms_existing_revision = revision
        self._sms_existing_credentials = {}
        self._sms_existing_options = {}
        self._sms_credentials_decryption_failed = False
        if revision:
            from .sms_security import decrypt_credentials
            try:
                self._sms_existing_credentials = decrypt_credentials(
                    revision.credentials_ciphertext
                )
            except Exception:
                # Do not silently rotate keys: historical deliveries may still
                # depend on this revision. Restore the original key first.
                self._sms_credentials_decryption_failed = True
                self._sms_existing_credentials = {}
            self._sms_existing_options = revision.connection_options or {}

        for field, key in (
            ("provider_username", "username"),
            ("provider_domain", "domain"),
            ("provider_sender", "sender"),
        ):
            self.fields[field].initial = self._sms_existing_credentials.get(key, "")
        self.fields["provider_api_base_url"].initial = (
            self._sms_existing_options.get("base_url") or
            getattr(settings, "MAGFA_API_BASE_URL", "")
        )
        self.fields["provider_timeout"].initial = (
            self._sms_existing_options.get("timeout") or
            getattr(settings, "MAGFA_TIMEOUT", 10)
        )

    def clean(self):
        cleaned = super().clean()
        credentials = dict(self._sms_existing_credentials)
        for field, key in (
            ("provider_username", "username"),
            ("provider_password", "password"),
            ("provider_domain", "domain"),
            ("provider_sender", "sender"),
        ):
            value = cleaned.get(field)
            if value:
                credentials[key] = value

        options = {
            "base_url": (
                cleaned.get("provider_api_base_url") or
                self._sms_existing_options.get("base_url") or
                "https://sms.magfa.com/api/http/sms/v2"
            ),
            "timeout": (
                cleaned.get("provider_timeout") or
                self._sms_existing_options.get("timeout") or 10
            ),
        }
        submitted_credentials = any(
            cleaned.get(field)
            for field in (
                "provider_username",
                "provider_password",
                "provider_domain",
                "provider_sender",
            )
        )
        if self._sms_credentials_decryption_failed and (
            submitted_credentials or cleaned.get("is_enabled")
        ):
            raise forms.ValidationError(
                "کلید رمزنگاری با تنظیمات ذخیره‌شده سازگار نیست. برای جلوگیری از قطع دسترسی به سوابق ارسال، کلید اصلی را در محیط امن سرور بازیابی کنید."
            )

        required = ("username", "password", "domain", "sender")
        missing = [key for key in required if not credentials.get(key)]
        if missing:
            if not cleaned.get("is_enabled") and not submitted_credentials:
                self._sms_credentials = None
                self._sms_connection_options = None
                self._sms_new_revision = False
                return cleaned
            raise forms.ValidationError(
                "برای راه‌اندازی مگفا، نام کاربری، رمز عبور، دامنه و شماره فرستنده الزامی است."
            )

        from .sms_services import MagfaSMSProvider
        from .sms_security import encrypt_credentials
        try:
            MagfaSMSProvider(
                credentials=credentials, options=options,
            ).validate_configuration()
            encrypt_credentials(credentials)
        except Exception as exc:
            raise forms.ValidationError(
                "تنظیمات اتصال مگفا یا کلید رمزنگاری معتبر نیست. تنظیمات محیط امن سرور را بررسی کنید."
            ) from exc

        self._sms_credentials = credentials
        self._sms_connection_options = options
        self._sms_new_revision = (
            self._sms_existing_revision is None or
            credentials != self._sms_existing_credentials or
            options != self._sms_existing_options
        )
        if cleaned.get("is_enabled"):
            provider = SMSProviderConfiguration.objects.filter(code="magfa").first()
            provider_will_be_activated = (
                "_activate_provider" in self.data
                or bool(provider and provider.is_active and not self._sms_new_revision)
            )
            if not provider_will_be_activated:
                raise forms.ValidationError(
                    "برای فعال‌کردن ارسال سراسری، ابتدا اتصال مگفا را آزمایش و اپراتور را فعال کنید."
                )
        return cleaned


@admin.register(WorkflowSMSSettings, site=dolphin_admin_site)
class WorkflowSMSSettingsAdmin(admin.ModelAdmin):
    form = WorkflowSMSSettingsAdminForm
    change_form_template = "admin/workflow/workflowsmssettings/change_form.html"
    admin_category = "communications"
    admin_section = "notification"
    list_display = ("is_enabled", "updated_at")
    fieldsets = (
        (
            "تنظیمات عمومی پیامک",
            {"fields": ("is_enabled",)},
        ),
        (
            "وضعیت اپراتور",
            {"fields": ("provider_status", "provider_revision", "global_sms_status", "last_connection_test_result", "last_connection_test_message", "delivery_overview", "latest_delivery_status")},
        ),
        (
            "اطلاعات اتصال مگفا",
            {
                "fields": (
                    "provider_username",
                    "provider_password",
                    "provider_domain",
                    "provider_sender",
                    "provider_api_base_url",
                    "provider_timeout",
                ),
                "description": (
                    "رمز عبور به‌صورت رمزنگاری‌شده ذخیره می‌شود. "
                    "برای حفظ رمز فعلی، فیلد رمز عبور را خالی بگذارید."
                ),
            },
        ),
        ("اطلاعات ثبت", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("provider_status", "provider_revision", "global_sms_status", "last_connection_test_result", "last_connection_test_message", "delivery_overview", "latest_delivery_status", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(pk=1)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return (
            request.user.is_active and request.user.is_superuser
            and not WorkflowSMSSettings.objects.exists()
        )

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="وضعیت اپراتور")
    def provider_status(self, obj):
        provider = SMSProviderConfiguration.objects.filter(code="magfa").first()
        if not provider:
            return "مگفا هنوز پیکربندی نشده است."
        return "فعال" if provider.is_active else "غیرفعال"

    @admin.display(description="وضعیت ارسال سراسری")
    def global_sms_status(self, obj):
        enabled = bool(obj and obj.is_enabled)
        return "فعال" if enabled else "غیرفعال"

    @admin.display(description="آخرین آزمایش اتصال")
    def last_connection_test_result(self, obj):
        provider = SMSProviderConfiguration.objects.filter(code="magfa").first()
        if not provider or provider.last_connection_test_success is None:
            return "هنوز آزمایش اتصالی ثبت نشده است."
        result = "موفق" if provider.last_connection_test_success else "ناموفق"
        if provider.last_connection_test_at:
            result += " — " + timezone.localtime(
                provider.last_connection_test_at
            ).strftime("%Y-%m-%d %H:%M")
        return result

    @admin.display(description="توضیح نتیجه آخرین آزمایش")
    def last_connection_test_message(self, obj):
        provider = SMSProviderConfiguration.objects.filter(code="magfa").first()
        if not provider or not provider.last_connection_test_message:
            return "توضیحی ثبت نشده است."
        return provider.last_connection_test_message

    @admin.display(description="خلاصه وضعیت ارسال‌ها")
    def delivery_overview(self, obj):
        totals = SMSDelivery.objects.aggregate(
            total=models.Count("pk"),
            pending=models.Count("pk", filter=models.Q(status=SMSDelivery.Status.PENDING)),
            sending=models.Count("pk", filter=models.Q(status=SMSDelivery.Status.SENDING)),
            sent=models.Count("pk", filter=models.Q(status=SMSDelivery.Status.SENT)),
            failed=models.Count("pk", filter=models.Q(status=SMSDelivery.Status.FAILED)),
            unknown=models.Count("pk", filter=models.Q(status=SMSDelivery.Status.UNKNOWN)),
        )
        return (
            f"کل: {totals['total']} | در صف: {totals['pending']} | "
            f"در حال ارسال: {totals['sending']} | پذیرفته‌شده: {totals['sent']} | "
            f"ناموفق: {totals['failed']} | نامشخص: {totals['unknown']}"
        )

    @admin.display(description="آخرین وضعیت ارسال")
    def latest_delivery_status(self, obj):
        latest = SMSDelivery.objects.order_by("-created_at").first()
        if latest is None:
            return "هنوز سابقه ارسالی ثبت نشده است."
        error_state = "؛ دارای خطا" if latest.last_error else ""
        return (
            f"{latest.get_status_display()} — "
            f"{timezone.localtime(latest.created_at).strftime('%Y-%m-%d %H:%M')}"
            f"{error_state}"
        )

    @admin.display(description="نسخه تنظیمات")
    def provider_revision(self, obj):
        provider = SMSProviderConfiguration.objects.filter(code="magfa").first()
        revision = (
            provider.revisions.filter(is_current=True).first()
            if provider else None
        )
        return f"نسخه {revision.version}" if revision else "ثبت نشده"

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            raise PermissionDenied
        obj.pk = 1
        obj._requested_sms_enabled = form.cleaned_data.get("is_enabled", False)
        super().save_model(request, obj, form, change)
        provider = SMSProviderConfiguration.objects.filter(code="magfa").first()
        if form._sms_new_revision:
            provider = provider or register_provider(code="magfa", name="مگفا")
            if provider.is_active:
                provider.is_active = False
                provider.save(update_fields=("is_active", "updated_at"))
                obj.is_enabled = False
                obj.save(update_fields=("is_enabled", "updated_at"))
                messages.warning(
                    request,
                    "تنظیمات اتصال تغییر کرد؛ برای جلوگیری از ارسال با اعتبارنامه آزمایش‌نشده، اپراتور و ارسال سراسری غیرفعال شدند.",
                )
            create_provider_revision(
                provider,
                credentials=form._sms_credentials,
                connection_options=form._sms_connection_options,
                created_by=request.user,
            )
            provider.last_connection_test_at = None
            provider.last_connection_test_success = None
            provider.last_connection_test_message = ""
            provider.save(update_fields=(
                "last_connection_test_at",
                "last_connection_test_success",
                "last_connection_test_message",
                "updated_at",
            ))

    def _handle_provider_action(self, request, obj):
        action = (
            "test" if "_test_connection" in request.POST else
            "activate" if "_activate_provider" in request.POST else
            "deactivate" if "_deactivate_provider" in request.POST else None
        )
        if not action:
            return False
        provider = None
        try:
            provider = SMSProviderConfiguration.objects.get(code="magfa")
            if action == "deactivate":
                provider.is_active = False
                provider.save(update_fields=("is_active", "updated_at"))
                WorkflowSMSSettings.objects.filter(pk=1).update(is_enabled=False)
                messages.success(
                    request,
                    "اپراتور مگفا و ارسال سراسری پیامک غیرفعال شدند.",
                )
                return True

            revision = provider.revisions.filter(is_current=True).first()
            if revision is None:
                raise ValueError("تنظیمات مگفا ثبت نشده است.")
            adapter = build_provider(revision)
            adapter.test_connection()
            provider.last_connection_test_at = timezone.now()
            provider.last_connection_test_success = True
            provider.last_connection_test_message = (
                "اتصال برقرار شد و سرویس موجودی با موفقیت پاسخ داد."
            )
            provider.save(update_fields=(
                "last_connection_test_at",
                "last_connection_test_success",
                "last_connection_test_message",
                "updated_at",
            ))
            if action == "activate":
                activate_provider(provider)
                if getattr(obj, "_requested_sms_enabled", False):
                    WorkflowSMSSettings.objects.filter(pk=1).update(
                        is_enabled=True
                    )
                messages.success(request, "اتصال مگفا موفق بود و اپراتور فعال شد.")
            else:
                messages.success(
                    request,
                    "اتصال مگفا موفق بود. وضعیت فعال‌سازی اپراتور تغییری نکرد.",
                )
        except Exception as exc:
            if provider is not None:
                if isinstance(exc, TimeoutError):
                    safe_error = "مهلت اتصال به پایان رسید."
                elif isinstance(exc, (ConnectionError, OSError)):
                    safe_error = "برقراری ارتباط با سرویس‌دهنده ممکن نشد."
                elif isinstance(exc, ValueError):
                    safe_error = "پیکربندی اتصال معتبر نیست."
                else:
                    safe_error = (
                        "آزمایش اتصال ناموفق بود؛ تنظیمات و دسترسی سرویس را بررسی کنید."
                    )
                provider.last_connection_test_at = timezone.now()
                provider.last_connection_test_success = False
                provider.last_connection_test_message = safe_error
                provider.save(update_fields=(
                    "last_connection_test_at",
                    "last_connection_test_success",
                    "last_connection_test_message",
                    "updated_at",
                ))
            if not SMSProviderConfiguration.objects.filter(
                is_active=True
            ).exists():
                WorkflowSMSSettings.objects.filter(pk=1).update(
                    is_enabled=False
                )
            messages.error(
                request,
                "آزمایش اتصال مگفا ناموفق بود. اپراتور فعال نشد؛ اطلاعات اتصال و دسترسی API را بررسی کنید.",
            )
        return True

    def response_change(self, request, obj):
        if self._handle_provider_action(request, obj):
            return HttpResponseRedirect(
                reverse(
                    "dolphin_admin:workflow_workflowsmssettings_change",
                    args=(obj.pk,),
                )
            )
        return super().response_change(request, obj)

    def response_add(self, request, obj, post_url_continue=None):
        if self._handle_provider_action(request, obj):
            return HttpResponseRedirect(
                reverse(
                    "dolphin_admin:workflow_workflowsmssettings_change",
                    args=(obj.pk,),
                )
            )
        return super().response_add(request, obj, post_url_continue)



class SMSTemplateScopeFilter(admin.SimpleListFilter):
    title = "دامنه قالب"
    parameter_name = "template_scope"

    def lookups(self, request, model_admin):
        return (
            ("global", "قالب عمومی (همه مراحل)"),
            ("step", "قالب اختصاصی مرحله"),
        )

    def queryset(self, request, queryset):
        if self.value() == "global":
            return queryset.filter(step__isnull=True)
        if self.value() == "step":
            return queryset.filter(step__isnull=False)
        return queryset


class SMSTemplateAdminForm(forms.ModelForm):
    class Meta:
        model = SMSTemplate
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["step"].required = False
        self.fields["step"].help_text = (
            "برای ساخت قالب عمومی (همه مراحل)، مرحله را خالی بگذارید. "
            "قالب اختصاصی هر مرحله بر قالب عمومی همان نوع اعلان اولویت دارد. "
            "برای جلوگیری از تداخل، برای هر دامنه و نوع اعلان فقط یک قالب ثبت می‌شود؛ "
            "قالب موجود را ویرایش کنید."
        )
        from .sms_services import SMS_TEMPLATE_VARIABLES, SMS_TEMPLATE_VARIABLES_BY_TYPE
        variable_payload = {
            notification_type: [
                {"value": key, "label": SMS_TEMPLATE_VARIABLES[key]}
                for key in keys
            ]
            for notification_type, keys in SMS_TEMPLATE_VARIABLES_BY_TYPE.items()
        }
        variable_json = json.dumps(variable_payload, ensure_ascii=False)
        self.fields["title_template"].required = False
        self.fields["title_template"].help_text = "عنوان پیامک؛ در صورت خالی بودن، عنوان خود اعلان استفاده می‌شود."
        self.fields["body_template"].label = "متن پیامک"
        self.fields["body_template"].help_text = "متن پیامک؛ متغیرها را از فهرست انتخاب و در محل مکان‌نما درج کنید."
        for field_name in ("title_template", "body_template"):
            self.fields[field_name].widget.attrs["data-sms-variables"] = variable_json

    def clean(self):
        cleaned_data = super().clean()
        notification_type = cleaned_data.get("notification_type")
        if notification_type and "step" in cleaned_data:
            existing = SMSTemplate.objects.filter(
                notification_type=notification_type,
                step=cleaned_data.get("step"),
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                scope = (
                    "قالب عمومی همه مراحل"
                    if cleaned_data.get("step") is None
                    else f"مرحله «{cleaned_data['step']}»"
                )
                self.add_error(
                    "notification_type",
                    f"برای {scope} و این نوع اعلان، قالبی از قبل ثبت شده است. "
                    "قالب موجود را ویرایش کنید یا دامنه دیگری انتخاب کنید.",
                )
        return cleaned_data


@admin.register(SMSTemplate, site=dolphin_admin_site)
class SMSTemplateAdmin(admin.ModelAdmin):
    form = SMSTemplateAdminForm
    admin_category = "communications"
    admin_section = "notification"
    list_display = (
        "scope_display",
        "workflow_display",
        "step_display",
        "notification_type",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "notification_type",
        SMSTemplateScopeFilter,
        "step__workflow",
    )
    search_fields = (
        "step__name",
        "step__workflow__name",
        "title_template",
        "body_template",
    )
    autocomplete_fields = ("step",)
    list_select_related = ("step", "step__workflow")
    fields = (
        "step",
        "notification_type",
        "title_template",
        "body_template",
        "template_preview",
        "is_active",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    readonly_fields = (
        "template_preview",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )

    @admin.display(description="نوع قالب")
    def scope_display(self, obj):
        return "عمومی" if obj.step_id is None else "اختصاصی مرحله"

    @admin.display(description="فرآیند", ordering="step__workflow__name")
    def workflow_display(self, obj):
        return obj.step.workflow.name if obj.step_id else "همه فرآیندها"

    @admin.display(description="مرحله", ordering="step__name")
    def step_display(self, obj):
        return obj.step.name if obj.step_id else "همه مراحل"

    @admin.display(description="پیش‌نمایش خروجی نهایی پیامک")
    def template_preview(self, obj):
        if not obj or not (obj.title_template or obj.body_template):
            return "پس از نوشتن عنوان یا متن پیامک، پیش‌نمایش در این قسمت نمایش داده می‌شود."
        from types import SimpleNamespace
        from .sms_services import _build_sms_content
        recipient = SimpleNamespace(get_full_name=lambda: "کاربر نمونه", get_username=lambda: "sample")
        instance = SimpleNamespace(pk=123, workflow=SimpleNamespace(name="فرآیند نمونه"))
        sample_notification = SimpleNamespace(
            title="عنوان نمونه اعلان", message="متن نمونه اعلان برای مشاهده خروجی.",
            recipient=recipient, workflow_instance=instance,
            workflow_step=SimpleNamespace(name="مرحله نمونه"), workflow_step_id=1,
            transition_execution=None, transition_execution_id=None,
            file_share_message=None, created_at=timezone.now(),
        )
        try:
            rendered, _ = _build_sms_content(sample_notification, obj)
        except Exception:
            return "قالب معتبر نیست؛ متغیرها و متن را بررسی کنید."
        if not rendered:
            return "خروجی قالب خالی است."
        return format_html('<pre style="white-space:pre-wrap;direction:rtl;margin:0;">{}</pre>', rendered)

    class Media:
        js = ("workflow/admin/sms-template-editor.js",)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            raise PermissionDenied
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)


@admin.register(SMSDelivery, site=dolphin_admin_site)
class SMSDeliveryAdmin(admin.ModelAdmin):
    admin_category = "communications"
    admin_section = "notification"
    list_display = (
        "created_at",
        "recipient",
        "notification",
        "status",
        "provider_code_snapshot",
        "message_source",
        "attempt_count",
        "has_error",
        "sent_at",
    )
    list_filter = (
        "status",
        "provider_code_snapshot",
        "message_source",
        "created_at",
    )
    search_fields = (
        "notification__recipient__username",
        "notification__recipient__first_name",
        "notification__recipient__last_name",
        "notification__title",
        "provider_message_id",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    list_select_related = (
        "notification",
        "notification__recipient",
        "provider_revision",
        "template",
    )
    readonly_fields = (
        "notification", "status", "provider_uid", "provider_message_id",
        "provider_revision", "provider_code_snapshot", "template",
        "message_source", "rendered_message", "attempt_count", "last_error",
        "sent_at", "last_queued_at", "created_at", "updated_at",
    )
    fields = readonly_fields

    @admin.display(description="دریافت‌کننده", ordering="notification__recipient__username")
    def recipient(self, obj):
        user = obj.notification.recipient
        return user.get_full_name() or user.get_username()

    @admin.display(description="جزئیات خطا", boolean=True)
    def has_error(self, obj):
        return bool(obj.last_error)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


#++++++++++++++++++++++
#ٌ WorkFlow DynamicStep
#++++++++++++++++++++++

class WorkflowDynamicStepsAdminView(admin.ModelAdmin):
    def workflow_steps_view(self, request):
        workflow_id = request.GET.get("workflow_id")

        if not workflow_id:
            return JsonResponse({"results": []})

        steps = (
            WorkflowStep.objects
            .filter(
                workflow_id=workflow_id,
                is_active=True,
            )
            .order_by("order")
        )

        results = [
            {
                "id": step.pk,
                "label": f"{step.order}. {step.name}",
            }
            for step in steps
        ]

        return JsonResponse({
            "results": results,
        })


# ============================================================
# Workflow Transition
# ============================================================

class WorkflowTransitionAdminForm(forms.ModelForm):

    class Meta:
        model = WorkflowTransition
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        workflow_id = None

        if self.instance and self.instance.pk:
            workflow_id = self.instance.workflow_id

        if self.data.get("workflow"):
            workflow_id = self.data.get("workflow")

        if workflow_id:
            steps = (
                WorkflowStep.objects
                .filter(
                    workflow_id=workflow_id,
                    is_active=True,
                )
                .order_by("order")
            )

            self.fields["from_step"].queryset = steps
            self.fields["to_step"].queryset = steps
            self.fields["reject_to_step"].queryset = steps

        else:
            self.fields["from_step"].queryset = (
                WorkflowStep.objects.none()
            )

            self.fields["to_step"].queryset = (
                WorkflowStep.objects.none()
            )

            self.fields["reject_to_step"].queryset = (
                WorkflowStep.objects.none()
            )

    def clean(self):
        cleaned_data = super().clean()

        workflow = cleaned_data.get("workflow")
        from_step = cleaned_data.get("from_step")
        to_step = cleaned_data.get("to_step")
        requires_acceptance = cleaned_data.get("requires_acceptance")
        reject_to_step = cleaned_data.get("reject_to_step")

        if workflow and from_step:
            if from_step.workflow_id != workflow.id:
                raise forms.ValidationError(
                    "مرحله مبدأ باید متعلق به همین Workflow باشد."
                )

        if workflow and to_step:
            if to_step.workflow_id != workflow.id:
                raise forms.ValidationError(
                    "مرحله مقصد باید متعلق به همین Workflow باشد."
                )

        if workflow and reject_to_step:
            if reject_to_step.workflow_id != workflow.id:
                raise forms.ValidationError(
                    "مرحله بازگشت پس از رد باید متعلق به همین Workflow باشد."
                )

        if reject_to_step and not requires_acceptance:
            raise forms.ValidationError(
                "مرحله بازگشت پس از رد فقط برای Transitionهای نیازمند تأیید قابل تنظیم است."
            )

        if from_step and to_step:
            if from_step.pk == to_step.pk:
                raise forms.ValidationError(
                    "مرحله مبدأ و مقصد نمی‌توانند یکسان باشند."
                )

        return cleaned_data

@admin.register(
    WorkflowTransition,
    site=dolphin_admin_site,
)
class WorkflowTransitionAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "definition"

    form = WorkflowTransitionAdminForm

    class Media:
        js = (
            "workflow/js/workflow-admin.js",
        )

    list_display = (
        "workflow",
        "name",
        "code",
        "from_step",
        "to_step",
        "reject_to_step",
        "requires_acceptance",
        "is_active",
    )

    list_filter = (
        "workflow",
        "is_active",
    )

    search_fields = (
        "workflow__name",
        "workflow__code",
        "name",
        "code",
        "from_step__name",
        "to_step__name",
        "reject_to_step__name",
    )

    
    readonly_fields = (
        "code",
        "created_at",
        "updated_at",
    )

    ordering = (
        "workflow",
        "from_step__order",
        "to_step__order",
    )

    inlines = (
        WorkflowTransitionPermissionInline,
    )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if (
                isinstance(instance, WorkflowPermission)
                and not instance.workflow_id
                and instance.transition_id
            ):
                instance.workflow = (
                    instance.transition.workflow
                )
            instance.save()
        formset.save_m2m()

# ============================================================
# Workflow Permission
# ============================================================

class WorkflowPermissionAdminForm(forms.ModelForm):

    class Meta:
        model = WorkflowPermission
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        workflow_id = None

        if self.instance and self.instance.pk:
            workflow_id = self.instance.workflow_id

        if self.data.get("workflow"):
            workflow_id = self.data.get("workflow")

        if workflow_id:

            self.fields["step"].queryset = (
                WorkflowStep.objects
                .filter(
                    workflow_id=workflow_id,
                    is_active=True,
                )
                .order_by("order")
            )

            self.fields["transition"].queryset = (
                WorkflowTransition.objects
                .filter(
                    workflow_id=workflow_id,
                    is_active=True,
                )
                .order_by(
                    "from_step__order",
                    "to_step__order",
                )
            )

        else:

            self.fields["step"].queryset = (
                WorkflowStep.objects.none()
            )

            self.fields["transition"].queryset = (
                WorkflowTransition.objects.none()
            )

    def clean(self):
        cleaned_data = super().clean()

        workflow = cleaned_data.get("workflow")
        step = cleaned_data.get("step")
        transition = cleaned_data.get("transition")

        if workflow and step:
            if step.workflow_id != workflow.id:
                raise forms.ValidationError(
                    "Step باید متعلق به همین Workflow باشد."
                )

        if workflow and transition:
            if transition.workflow_id != workflow.id:
                raise forms.ValidationError(
                    "Transition باید متعلق به همین Workflow باشد."
                )

        return cleaned_data

@admin.register(
    WorkflowPermission,
    site=dolphin_admin_site,
)
class WorkflowPermissionAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "security"

    form = WorkflowPermissionAdminForm

    class Media:
        js = (
            "workflow/js/workflow-admin.js",
        )

    list_display = (
        "workflow",
        "step",
        "transition",
        "user",
        "role",
        "action",
        "effect",
    )

    list_filter = (
        "workflow",
        "role",
        "action",
        "effect",
    )

    search_fields = (
        "workflow__name",
        "workflow__code",
        "user__username",
        "user__first_name",
        "user__last_name",
        "step__name",
        "transition__name",
    )

    autocomplete_fields = (
        "workflow",
        "user",
    )
    ordering = (
        "workflow",
        "action",
        "effect",
    )


# ============================================================
# Workflow Instance
# ============================================================

@admin.register(
    WorkflowInstance,
    site=dolphin_admin_site,
)
class WorkflowInstanceAdmin(admin.ModelAdmin):

    admin_category = "executions"
    admin_section = "execution"

    class Media:
        css = {
            "all": (
                "workflow/css/workflow-admin.css",
            ),
        }

    @admin.display(
        description="مدت اجرا",
    )
    def execution_duration(self, obj):
        if not obj.started_at:
            return "—"

        end_time = obj.completed_at or timezone.now()

        return end_time - obj.started_at

    @admin.display(
        description="Timeline",
        )
    def timeline_link(self, obj):
        url = reverse(
        "admin:workflow_workflowinstance_timeline",
        args=[obj.pk],
        )

        return format_html(
            '<a class="timeline-admin-button" href="{}">'
            '<span class="timeline-admin-icon">↗</span>'
            '<span>Timeline</span>'
            '</a>',
            url,
        )

    list_display = (
        "timeline_link",
        "id",
        "workflow",
        "current_step",
        "started_by",
        "status",
        "started_at",
        "completed_at",
        "execution_duration",
    )

    list_filter = (
        "workflow",
        "status",
        "started_at",
    )

    search_fields = (
        "workflow__name",
        "workflow__code",
        "started_by__username",
        "started_by__first_name",
        "started_by__last_name",
    )

    readonly_fields = (
        "workflow",
        "current_step",
        "started_by",
        "status",
        "started_at",
        "completed_at",
    )

    ordering = (
        "-started_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def timeline_view(self, request, object_id):
        instance = get_object_or_404(
            WorkflowInstance.objects.select_related(
                "workflow",
                "current_step",
                "started_by",
            ),
            pk=object_id,
        )

        step_events = list(
            WorkflowStepExecution.objects
            .filter(instance=instance)
            .select_related(
                "workflow_step",
                "performed_by",
            )
            .values(
                "id",
                "performed_at",
                "workflow_step__name",
                "performed_by__username",
                "performed_by__first_name",
                "performed_by__last_name",
                "notes",
                "is_submitted",
                "data",

                "sla_started_at",
                "sla_due_at",
                "sla_warning_at",
                "sla_warning_sent_at",
                "sla_completed_at",
                "sla_breached_at",
            )
        )

        transition_events = list(
            WorkflowTransitionExecution.objects
            .filter(instance=instance)
            .select_related(
                "transition",
                "transition__from_step",
                "transition__to_step",
                "performed_by",
            )
            .values(
                "id",
                "performed_at",
                "transition__name",
                "transition__from_step__name",
                "transition__to_step__name",
                "performed_by__username",
                "performed_by__first_name",
                "performed_by__last_name",
                "notes",
            )
        )

        events = [
            {
                "type": "start",
                "id": f"instance-{instance.pk}",
                "performed_at": instance.started_at,
                "user": str(instance.started_by or "—"),
                "title": "شروع فرآیند",
                "description": (
                    f"Workflow «{instance.workflow.name}» "
                    "شروع شد."
                ),
                "is_submitted": False,
                "sla_completed": False,
                "sla_breached": False,
            }
        ]

        for event in step_events:
            events.append(
                {
                    "type": "step",
                    "id": event["id"],
                    "performed_at": event["performed_at"],
                    "user": (
                        event["performed_by__first_name"]
                        or event["performed_by__last_name"]
                        or event["performed_by__username"]
                    ),
                    "title": (
                        f"ورود به مرحله "
                        f"«{event['workflow_step__name']}»"
                    ),
                    "description": event["notes"],
                    "history": (
                        event["data"].get("history")
                        if event["data"]
                        else None
                    ),

                    "is_submitted": event["is_submitted"],

                    "sla_started_at": event["sla_started_at"],
                    "sla_due_at": event["sla_due_at"],
                    "sla_warning_at": event["sla_warning_at"],
                    "sla_warning_sent_at": (
                        event["sla_warning_sent_at"]
                    ),
                    "sla_completed_at": event["sla_completed_at"],
                    "sla_breached_at": event["sla_breached_at"],

                    "sla_completed": bool(
                        event["sla_completed_at"]
                    ),
                    "sla_breached": bool(
                        event["sla_breached_at"]
                    ),
                }
            )

        for event in transition_events:
            events.append(
                {
                    "type": "transition",
                    "id": event["id"],
                    "performed_at": event["performed_at"],
                    "user": (
                        event["performed_by__first_name"]
                        or event["performed_by__last_name"]
                        or event["performed_by__username"]
                    ),
                    "title": event["transition__name"],
                    "description": (
                        f"{event['transition__from_step__name']}"
                        f" → "
                        f"{event['transition__to_step__name']}"
                        if event['transition__to_step__name']
                        else f"{event['transition__from_step__name']}"
                        f" → [تکمیل فرآیند]"
                    ),
                    "is_submitted": False,
                    "sla_completed": False,
                    "sla_breached": False,
                }
            )

        events.sort(
            key=lambda event: event["performed_at"]
        )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "instance": instance,
            "events": events,
            "title": (
                f"تاریخچه اجرای "
                f"{instance.workflow.name} "
                f"#{instance.pk}"
            ),
        }

        return TemplateResponse(
            request,
            "admin/workflow/workflow_instance_timeline.html",
            context,
        )

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<path:object_id>/timeline/",
                self.admin_site.admin_view(
                    self.timeline_view
                ),
                name=(
                    "workflow_workflowinstance_timeline"
                ),
            ),
        ]

        return custom_urls + urls

# ============================================================
# Workflow Step Execution
# ============================================================

@admin.register(
    WorkflowStepExecution,
    site=dolphin_admin_site,
)
class WorkflowStepExecutionAdmin(admin.ModelAdmin):

    admin_category = "executions"
    admin_section = "execution"

    list_display = (
        "id",
        "instance",
        "workflow_step",
        "performed_by",
        "performed_at",
        "is_submitted",
        "sla_status",
    )

    list_filter = (
        "workflow_step__workflow",
        "workflow_step",
        "is_submitted",
        "performed_by",
        "performed_at",
        "sla_breached_at",
    )

    search_fields = (
        "instance__workflow__name",
        "instance__pk",
        "workflow_step__name",
        "performed_by__username",
        "performed_by__first_name",
        "performed_by__last_name",
        "notes",
    )

    readonly_fields = (
        "instance",
        "workflow_step",
        "performed_by",
        "performed_at",
        "notes",
        "data",
        "is_submitted",
        "submitted_at",
        "sla_started_at",
        "sla_due_at",
        "sla_warning_at",
        "sla_warning_sent_at",
        "sla_completed_at",
        "sla_breached_at",
    )

    autocomplete_fields = (
        "instance",
        "workflow_step",
        "performed_by",
    )

    ordering = (
        "-performed_at",
    )

    @admin.display(
        description="وضعیت SLA",
    )
    def sla_status(self, obj):
        if obj.sla_breached_at:
            return "نقض SLA"

        if obj.sla_completed_at:
            return "تکمیل SLA"

        if obj.sla_due_at:
            return "در انتظار تکمیل"

        return "—"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "instance",
                "instance__workflow",
                "workflow_step",
                "workflow_step__workflow",
                "performed_by",
            )
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

# ============================================================
# Workflow Transition Execution
# ============================================================

@admin.register(
    WorkflowTransitionExecution,
    site=dolphin_admin_site,
)
class WorkflowTransitionExecutionAdmin(admin.ModelAdmin):

    admin_category = "executions"
    admin_section = "execution"

    @admin.display(
        description="از مرحله",
        ordering="transition__from_step__order",
    )
    def from_step(self, obj):
        return obj.transition.from_step

    @admin.display(
        description="به مرحله",
        ordering="transition__to_step__order",
    )
    def to_step(self, obj):
        if obj.transition.to_step:
            return obj.transition.to_step
        return "[تکمیل فرآیند]"

    list_display = (
        "id",
        "instance",
        "from_step",
        "to_step",
        "performed_by",
        "performed_at",
    )

    list_filter = (
        "transition__workflow",
        "transition__from_step",
        "transition__to_step",
        "performed_by",
        "performed_at",
    )

    search_fields = (
        "instance__workflow__name",
        "instance__pk",
        "transition__name",
        "transition__code",
        "transition__from_step__name",
        "transition__to_step__name",
        "performed_by__username",
        "performed_by__first_name",
        "performed_by__last_name",
        "notes",
    )

    readonly_fields = (
        "instance",
        "transition",
        "performed_by",
        "performed_at",
        "notes",
        "data",
    )

    autocomplete_fields = (
        "instance",
        "transition",
        "performed_by",
    )

    ordering = (
        "-performed_at",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "instance",
                "instance__workflow",
                "transition",
                "transition__workflow",
                "transition__from_step",
                "transition__to_step",
                "performed_by",
            )
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
# ============================================================
# Devices
# ============================================================

@admin.register(
    DeviceType,
    site=dolphin_admin_site,
)
class DeviceTypeAdmin(admin.ModelAdmin):

    admin_category = "devices"

    list_display = (
        "name",
        "code",
        "is_active",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "code",
    )

    readonly_fields = (
        "code",
        "created_at",
        "updated_at",
    )

@admin.register(
    DeviceModel,
    site=dolphin_admin_site,
)
class DeviceModelAdmin(admin.ModelAdmin):

    admin_category = "devices"

    list_display = (
        "name",
        "device_type",
        "code",
        "is_active",
    )

    list_filter = (
        "device_type",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "device_type__name",
    )

    autocomplete_fields = (
        "device_type",
    )

    readonly_fields = (
        "code",
        "created_at",
        "updated_at",
    )

@admin.register(
    Device,
    site=dolphin_admin_site,
)
class DeviceAdmin(admin.ModelAdmin):

    admin_category = "devices"

    list_display = (
        "id",
        "device_model",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "device_model__device_type",
    )

    search_fields = (
        "device_model__brand",
        "device_model__name",
        "identifiers__value",
        "description",
    )

    autocomplete_fields = (
        "device_model",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

@admin.register(
    DeviceIdentifier,
    site=dolphin_admin_site,
)
class DeviceIdentifierAdmin(admin.ModelAdmin):

    admin_category = "devices"

    list_display = (
        "device",
        "identifier_type",
        "value",
        "created_at",
    )

    list_filter = (
        "identifier_type",
    )

    search_fields = (
        "value",
        "device__device_model__brand",
        "device__device_model__name",
    )

    autocomplete_fields = (
        "device",
    )

    readonly_fields = (
        "created_at",
    )
#---------------------------------------------
#LookUpList,LookUpItems-StaticChoice,StaticItem
#---------------------------------------------

class LookupItemInline(admin.TabularInline):
    model = LookupItem
    extra = 1

    fields = (
        "label",
        "value",
        "parent",
        "order",
        "is_active",
    )

    autocomplete_fields = (
        "parent",
    )

    ordering = (
        "order",
        "id",
    )


@admin.register(
    LookupList,
    site=dolphin_admin_site,
)
class LookupListAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "name",
        "code",
        "is_active",
        "item_count",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "code",
    )

    ordering = (
        "name",
    )

    inlines = (
        LookupItemInline,
    )

    @admin.display(
        description="تعداد آیتم‌ها",
    )
    def item_count(self, obj):
        return obj.items.count()


@admin.register(
    LookupItem,
    site=dolphin_admin_site,
)
class LookupItemAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "label",
        "value",
        "lookup_list",
        "parent",
        "order",
        "is_active",
    )

    list_filter = (
        "is_active",
        "lookup_list",
    )

    search_fields = (
        "label",
        "value",
        "lookup_list__name",
    )

    ordering = (
        "lookup_list",
        "order",
        "id",
    )

    autocomplete_fields = (
        "lookup_list",
        "parent",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "lookup_list",
                "parent",
            )
        )

class StaticChoiceItemInline(admin.TabularInline):
    model = StaticChoiceItem
    extra = 1

    fields = (
        "label",
        "value",
        "order",
        "is_active",
    )

    ordering = (
        "order",
        "id",
    )


@admin.register(
    StaticChoiceSet,
    site=dolphin_admin_site,
)
class StaticChoiceSetAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "name",
        "code",
        "is_active",
        "item_count",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "code",
    )

    ordering = (
        "name",
    )

    inlines = (
        StaticChoiceItemInline,
    )

    @admin.display(
        description="تعداد گزینه‌ها",
    )
    def item_count(self, obj):
        return obj.items.count()


@admin.register(
    StaticChoiceItem,
    site=dolphin_admin_site,
)
class StaticChoiceItemAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "label",
        "value",
        "choice_set",
        "order",
        "is_active",
    )

    list_filter = (
        "is_active",
        "choice_set",
    )

    search_fields = (
        "label",
        "value",
        "choice_set__name",
    )

    ordering = (
        "choice_set",
        "order",
        "id",
    )

    autocomplete_fields = (
        "choice_set",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "choice_set",
            )
        )


#---------------------
#---------------------
class FormPrintSettingsInline(admin.StackedInline):
    model = FormPrintSettings
    extra = 1
    max_num = 1
    can_delete = False
    fieldsets = (
        (
            "عنوان و سربرگ سند",
            {
                "fields": (
                    "document_title",
                    "subtitle",
                    "header_text",
                    "footer_text",
                ),
            },
        ),
        (
            "صفحه و اطلاعات فرایند",
            {
                "fields": (
                    "page_size",
                    "orientation",
                    "show_workflow_name",
                    "show_instance_number",
                    "show_created_at",
                    "show_empty_values",
                ),
            },
        ),
        (
            "امضاها",
            {
                "fields": (
                    "show_signatures",
                    "signature_count",
                ),
            },
        ),
    )


class FormPrintSectionSettingsInline(admin.StackedInline):
    model = FormPrintSectionSettings
    extra = 1
    max_num = 1
    can_delete = False
    fields = (
        "is_enabled",
        "title_override",
        "print_order",
    )


class FormPrintFieldSettingsInline(admin.StackedInline):
    model = FormPrintFieldSettings
    fk_name = "field"
    extra = 1
    max_num = 1
    fields = (
        "is_enabled",
        "title_override",
        "print_order",
    )


class RepeatableGroupPrintSettingsInline(admin.StackedInline):
    model = FormPrintFieldSettings
    fk_name = "repeatable_group"
    extra = 1
    max_num = 1
    fields = (
        "is_enabled",
        "title_override",
        "print_order",
        "group_layout",
    )


@admin.register(
    FormDefinition,
    site=dolphin_admin_site,
)
class FormDefinitionAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "name",
        "workflow",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "workflow__name",
    )

    inlines = (FormPrintSettingsInline,)

class FormFieldInline(admin.TabularInline):
    model = FormField
    extra = 0

    fields = (
        "name",
        "code",
        "field_type",
        "calendar",
        "label",
        "is_required",
        "order",
        "is_active",
    )

    ordering = (
        "order",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(
                repeatable_group__isnull=True,
            )
        )

class FormRepeatableGroupInlineFormSet(forms.BaseInlineFormSet):

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        form.fields["parent_group"].queryset = get_valid_parent_group_queryset(
            self.instance,
            form.instance,
        )
        return form


class FormRepeatableGroupInline(admin.TabularInline):
    model = FormRepeatableGroup
    fk_name = "section"
    formset = FormRepeatableGroupInlineFormSet
    extra = 0
    fields = (
        "name",
        "label",
        "code",
        "group_type",
        "display_type",
        "description",
        "parent_group",
        "order",
        "is_required",
        "is_active",
    )

@admin.register(
    FormSection,
    site=dolphin_admin_site,
)
class FormSectionAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "name",
        "form",
        "code",
        "order",
        "is_active",
        "layout_designer_link",
    )

    def layout_designer_link(self, obj):
        url = reverse(
            "admin:workflow_formsection_layout",
            args=[obj.pk],
        )
        return format_html(
            '<a href="{}">طراحی ترتیب نمایش</a>',
            url,
        )

    layout_designer_link.short_description = "ترتیب نمایش"

    list_filter = (
        "is_active",
        "form",
    )

    search_fields = (
        "name",
        "code",
    )

    ordering = (
        "form",
        "order",
    )

    inlines = (
        FormFieldInline,
        FormRepeatableGroupInline,
        FormPrintSectionSettingsInline,
    )

    class Media:
        js = (
            "workflow/js/section_layout_designer.js",
        )
        css = {
            "all": (
                "workflow/css/section_layout_designer.css",
            ),
        }

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<path:object_id>/layout/",
                self.admin_site.admin_view(self.layout_view),
                name=(
                    "workflow_formsection_layout"
                ),
            ),
            path(
                "<path:object_id>/layout/save/",
                self.admin_site.admin_view(self.layout_save_view),
                name=(
                    "workflow_formsection_layout_save"
                ),
            ),
        ]

        return custom_urls + urls

    def layout_view(self, request, object_id):
        section = get_object_or_404(
            FormSection.objects.select_related("form").only(
                "id",
                "form_id",
                "name",
                "code",
            ),
            pk=object_id,
        )

        if not self.has_change_permission(request, obj=section):
            raise PermissionDenied()

        # Top-level active FormFields.
        fields = (
            FormField.objects
            .filter(
                section=section,
                repeatable_group__isnull=True,
                is_active=True,
            )
            .only(
                "id",
                "code",
                "label",
                "layout_order",
                "order",
            )
        )

        # Active FormRepeatableGroups.
        groups = (
            FormRepeatableGroup.objects
            .filter(
                section=section,
                parent_group__isnull=True,
                is_active=True,
            )
            .only(
                "id",
                "code",
                "name",
                "label",
                "layout_order",
                "order",
            )
        )

        # Deterministic presentational ordering for NULL layout_order.
        def presentational_key(item):
            layout = item["layout_order"]
            return (
                layout is None,
                layout if layout is not None else 0,
                item["order"],
                0 if item["type"] == "field" else 1,
                item["id"],
            )

        layout_items = []

        for field in fields:
            layout_items.append(
                {
                    "type": "field",
                    "id": field.id,
                    "code": field.code,
                    "label": field.label,
                    "layout_order": (
                        field.layout_order
                        if field.layout_order is not None
                        else None
                    ),
                    "order": field.order,
                }
            )

        for group in groups:
            layout_items.append(
                {
                    "type": "group",
                    "id": group.id,
                    "code": group.code,
                    "label": group.label,
                    "layout_order": (
                        group.layout_order
                        if group.layout_order is not None
                        else None
                    ),
                    "order": group.order,
                }
            )

        layout_items.sort(key=presentational_key)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "section": section,
            "layout_items": layout_items,
            "title": (
                f"ترتیب نمایش آیتم‌های Section «"
                f"{section.name}»"
            ),
        }

        return TemplateResponse(
            request,
            "admin/workflow/formsection_layout.html",
            context,
        )

    def layout_save_view(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied()

        # Authorization: Django Admin admin_view already enforces
        # login/staff + model change permission for the wrapped view.
        # We additionally require explicit change permission on this
        # Section so cross-Section ID injection cannot be executed by
        # a user who cannot change the target Section.
        if not self.has_change_permission(request, obj=None):
            raise PermissionDenied()

        section = get_object_or_404(
            FormSection.objects.only(
                "id",
                "form_id",
                "name",
            ),
            pk=object_id,
        )

        if not self.has_change_permission(request, obj=section):
            raise PermissionDenied()

        if request.method != "POST":
            return JsonResponse(
                {"error": "متد مجاز نیست."},
                status=405,
            )

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (
            ValueError,
            UnicodeDecodeError,
        ):
            return JsonResponse(
                {"error": "شیوه ارسال ترتیب نامعتبر است."},
                status=400,
            )

        if not isinstance(payload, list):
            return JsonResponse(
                {"error": "ترتیب باید در قالب یک لیست ارسال شود."},
                status=400,
            )

        with transaction.atomic():
            # Re-query the current active top-level items to reject stale
            # submissions and to validate the submitted complete set.
            current_fields = {
                obj.id: obj
                for obj in (
                    FormField.objects
                    .filter(
                        section=section,
                        repeatable_group__isnull=True,
                        is_active=True,
                    )
                    .only(
                        "id",
                        "code",
                        "section_id",
                        "repeatable_group_id",
                    )
                )
            }

            current_groups = {
                obj.id: obj
                for obj in (
                    FormRepeatableGroup.objects
                    .filter(
                        section=section,
                        parent_group__isnull=True,
                        is_active=True,
                    )
                    .only(
                        "id",
                        "code",
                        "section_id",
                    )
                )
            }

            expected_ids = (
                {("field", item_id) for item_id in current_fields}
                | {("group", item_id) for item_id in current_groups}
            )
            resolved = []
            seen = set()

            for item in payload:
                if not isinstance(item, dict):
                    return JsonResponse(
                        {"error": "تصمیم‌نامه نامعتبر."},
                        status=400,
                    )

                item_type = item.get("type")
                item_id = item.get("id")

                if item_type not in ("field", "group"):
                    return JsonResponse(
                        {"error": "نوع آیتم نامعتبر."},
                        status=400,
                    )

                if item_id is None:
                    return JsonResponse(
                        {"error": "شناسه آیتم ارسال نشده است."},
                        status=400,
                    )

                if item_type == "field":
                    obj = current_fields.get(item_id)
                    if obj is None:
                        return JsonResponse(
                            {"error": "فیلد نامعتبر یا غیرفعال است."},
                            status=400,
                        )

                    if obj.repeatable_group_id is not None:
                        return JsonResponse(
                            {
                                "error": (
                                    "فیلدهای درون گروه تکرارشونده «"
                                    "نمی‌توانند در ترتیب نمایش Section «"
                                    f"{section.name}» ظاهر شوند."
                                )
                            },
                            status=400,
                        )

                    if obj.section_id != section.id:
                        return JsonResponse(
                            {
                                "error": (
                                    "این آیتم متعلق به Section دیگری است "
                                    "و نمی‌تواند در این Section نمایش داده شود."
                                )
                            },
                            status=400,
                        )

                else:
                    obj = current_groups.get(item_id)
                    if obj is None:
                        return JsonResponse(
                            {"error": "گروه نامعتبر یا غیرفعال است."},
                            status=400,
                        )

                    if obj.section_id != section.id:
                        return JsonResponse(
                            {
                                "error": (
                                    "این آیتم متعلق به Section دیگری است "
                                    "و نمی‌تواند در این Section نمایش داده شود."
                                )
                            },
                            status=400,
                        )

                typed_identity = (item_type, item_id)

                if typed_identity in seen:
                    return JsonResponse(
                        {"error": "یک آیتم در ترتیب دو بار تکرار شده است."},
                        status=400,
                    )

                seen.add(typed_identity)
                resolved.append(obj)

            if seen != expected_ids:
                return JsonResponse(
                    {"error": "مجموعه آیتم‌های ارسالی با ترکیب فعلی Section کاملاً همخوانی ندارد."},
                    status=400,
                )

            field_updates = []
            group_updates = []

            for index, obj in enumerate(resolved, start=1):
                setattr(obj, "layout_order", index * 10)

                if isinstance(obj, FormField):
                    field_updates.append(obj)
                else:
                    group_updates.append(obj)

            if field_updates:
                FormField.objects.bulk_update(
                    field_updates,
                    ["layout_order"],
                )

            if group_updates:
                FormRepeatableGroup.objects.bulk_update(
                    group_updates,
                    ["layout_order"],
                )

        return JsonResponse(
            {"ok": True},
            status=200,
        )

class RepeatableFieldInlineFormSet(forms.BaseInlineFormSet):

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)

        # FormField.section باید همیشه با Section گروه یکی باشد.
        if self.instance and self.instance.section_id:
            form.instance.section = self.instance.section

        return form


class RepeatableFieldInline(admin.TabularInline):
    model = FormField
    formset = RepeatableFieldInlineFormSet

    class Media:
        js = ("workflow/js/formfield_admin.js",)

    extra = 0

    fields = (
        "name",
        "code",
        "field_type",
        "label",
        "help_text",
        "default_value",
        "is_required",
        "allow_file_sharing",
        "order",
        "is_active",
        "choices",
    )

    ordering = (
        "order",
    )

# ============================================================
# Form Repeatable Group
# ============================================================

class RepeatableGroupAccessInline(admin.TabularInline):
    model = RepeatableGroupAccess
    extra = 0

    fields = (
        "step",
        "role",
        "user",
        "can_view",
        "can_edit",
        "can_add",
        "can_delete",
    )

    autocomplete_fields = (
        "step",
        "user",
    )

@admin.register(
    FormRepeatableGroup,
    site=dolphin_admin_site,
)
class FormRepeatableGroupAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "label",
        "name",
        "section",
        "code",
        "group_type",
        "order",
        "is_required",
        "is_active",
    )

    list_filter = (
        "is_active",
        "is_required",
        "group_type",
        "section__form",
    )

    search_fields = (
        "name",
        "code",
        "description",
        "section__name",
        "section__form__name",
    )

    ordering = (
        "section",
        "order",
    )

    autocomplete_fields = (
        "section",
    )

    inlines = (
        RepeatableFieldInline,
        RepeatableGroupAccessInline,
        RepeatableGroupPrintSettingsInline,
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(
            request,
            obj,
            **kwargs,
        )

        if "section" in form.base_fields:
            form.base_fields["section"].queryset = (
                FormSection.objects
                .filter(
                    is_active=True,
                    form__is_active=True,
                )
                .select_related("form")
                .order_by(
                    "form__name",
                    "order",
                )
            )

        if obj and "parent_group" in form.base_fields:
            form.base_fields["parent_group"].queryset = (
                get_valid_parent_group_queryset(
                    obj.section,
                    obj,
                )
            )

        return form

class FieldAccessInline(admin.TabularInline):
    model = FieldAccess
    extra = 0

    fields = (
        "step",
        "role",
        "user",
        "can_view",
        "can_edit",
    )

    autocomplete_fields = (
        "step",
        "user",
    )

def formfield_model_fields(request):
    content_type_id = request.GET.get("content_type")

    if not content_type_id:
        return JsonResponse(
            {"fields": []},
            status=400,
        )

    try:
        content_type = ContentType.objects.get(
            pk=content_type_id,
        )
    except (
        ContentType.DoesNotExist,
        ValueError,
        TypeError,
    ):
        return JsonResponse(
            {"fields": []},
            status=404,
        )

    model_class = content_type.model_class()

    if not model_class:
        return JsonResponse(
            {"fields": []},
            status=404,
        )

    fields = []

    for field in model_class._meta.get_fields():

        if not getattr(field, "concrete", False):
            continue

        if getattr(field, "auto_created", False):
            continue

        if not getattr(field, "editable", True):
            continue

        fields.append(
            {
                "name": field.name,
                "label": str(field.verbose_name),
                "is_foreign_key": isinstance(
                    field,
                    models.ForeignKey,
                ),
            }
        )

    return JsonResponse(
        {
            "fields": fields,
        }
    )    

class FormFieldAdminForm(forms.ModelForm):

    class Meta:
        model = FormField
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from django.contrib.contenttypes.models import ContentType

        # --------------------------------------------------
        # Choice Model
        # --------------------------------------------------

        choice_model_field = self.fields.get("choice_model")
        lookup_list_field = self.fields.get("choice_lookup_list")
        static_set_field = self.fields.get("choice_static_set")

        if choice_model_field:
            choice_model_field.label_from_instance = (
                lambda obj: f"{obj.app_label} → {obj.model}"
            )

        # --------------------------------------------------
        # Choice Source dependencies
        # --------------------------------------------------

        if lookup_list_field:
            lookup_list_field.queryset = (
                LookupList.objects
                .filter(is_active=True)
                .order_by("name")
            )

        if static_set_field:
            static_set_field.queryset = (
                StaticChoiceSet.objects
                .filter(is_active=True)
                .order_by("name")
            )

        # --------------------------------------------------
        # Dynamic model fields
        # --------------------------------------------------

        label_field = self.fields.get("choice_label_field")
        value_field = self.fields.get("choice_value_field")
        filter_field = self.fields.get("choice_filter_field")
        
        if label_field:
            label_field.widget = forms.Select()

        if value_field:
            value_field.widget = forms.Select()

        if filter_field:
            filter_field.widget = forms.Select()

        if label_field and self.instance and self.instance.pk:
            label_field.widget.attrs["data-initial-value"] = (
                self.instance.choice_label_field or ""
            )

        if value_field and self.instance and self.instance.pk:
            value_field.widget.attrs["data-initial-value"] = (
                self.instance.choice_value_field or ""
            )

        if filter_field and self.instance and self.instance.pk:
            filter_field.widget.attrs["data-initial-value"] = (
                self.instance.choice_filter_field or ""
            )

        # --------------------------------------------------
        # Resolve Choice Model
        # --------------------------------------------------

        choice_model = None

        if self.instance and self.instance.pk:
            choice_model = self.instance.choice_model

        if self.is_bound:
            choice_model_id = self.data.get(
                self.add_prefix("choice_model")
            )

            if choice_model_id:
                try:
                    choice_model = ContentType.objects.get(
                        pk=choice_model_id
                    )
                except (
                    ContentType.DoesNotExist,
                    ValueError,
                    TypeError,
                ):
                    choice_model = None

        model_class = (
            choice_model.model_class()
            if choice_model
            else None
        )

        # --------------------------------------------------
        # Build model field choices
        # --------------------------------------------------

        field_choices = []

        if model_class:

            for field in model_class._meta.get_fields():

                if not getattr(field, "concrete", False):
                    continue

                if getattr(field, "auto_created", False):
                    continue

                if not getattr(field, "editable", True):
                    continue

                field_choices.append(
                    (
                        field.name,
                        f"{field.name} ({field.verbose_name})",
                    )
                )

        # --------------------------------------------------
        # Label Field
        # --------------------------------------------------

        if label_field:

            label_field.choices = [
                ("", "---------"),
                *field_choices,
            ]
        
        if label_field and self.instance and self.instance.pk:
                label_field.initial = self.instance.choice_label_field

        # --------------------------------------------------
        # Value Field
        # --------------------------------------------------

        if value_field:

            value_field.choices = [
                ("", "---------"),
                ("id", "id (شناسه)"),
                *field_choices,
            ]
        if value_field and self.instance and self.instance.pk:
            value_field.initial = self.instance.choice_value_field

        if filter_field:

            filter_choices = [
                ("", "---------"),
            ]

            if model_class:
                for field in model_class._meta.get_fields():

                    if not getattr(field, "concrete", False):
                        continue

                    if getattr(field, "auto_created", False):
                        continue

                    if not isinstance(
                        field,
                        models.ForeignKey,
                    ):
                        continue

                    related_model = field.remote_field.model

                    filter_choices.append(
                        (
                            field.name,
                            (
                                f"{field.name} "
                                f"→ "
                                f"{related_model._meta.verbose_name}"
                            ),
                        )
                    )

            filter_field.choices = filter_choices
            if self.instance and self.instance.pk:
                filter_field.initial = self.instance.choice_filter_field
        # --------------------------------------------------
        # Parent Field
        # --------------------------------------------------

        parent_field = self.fields.get(
            "choice_parent_field"
        )

        if parent_field:

            queryset = FormField.objects.filter(
                field_type=FormField.FieldType.SELECT,
                is_active=True,
                section__form_id=(
                    self.instance.section.form_id
                    if self.instance
                    and self.instance.pk
                    and self.instance.section_id
                    else None
                ),
            )

            # هنگام Add هنوز instance.section وجود ندارد.
            if self.is_bound:

                section_id = self.data.get(
                    self.add_prefix("section")
                )

                if section_id:
                    queryset = FormField.objects.filter(
                        field_type=FormField.FieldType.SELECT,
                        is_active=True,
                        section__form__sections__id=section_id,
                    )

            parent_field.queryset = queryset.exclude(
                pk=self.instance.pk
                if self.instance and self.instance.pk
                else None
            )

            if self.instance and self.instance.pk:
                parent_field.initial = self.instance.choice_parent_field_id

@admin.register(
    FormField,
    site=dolphin_admin_site,
)
class FormFieldAdmin(admin.ModelAdmin):

    class Media:
        js = (
            "workflow/js/formfield_admin.js",
        )

    form = FormFieldAdminForm
    admin_category = "forms"

    list_display = (
        "label",
        "section",
        "repeatable_group_type",
        "repeatable_group",
        "code",
        "field_type",
        "access_count",
        "is_required",
        "order",
        "is_active",
    )

    list_filter = (
        "field_type",
        "is_required",
        "is_active",
        "repeatable_group",
        "section__form",
    )

    search_fields = (
        "label",
        "name",
        "code",
        "section__name",
        "repeatable_group__name",
    )

    autocomplete_fields = (
        "section",
        "repeatable_group",
    )

    ordering = (
        "section",
        "order",
    )

    fieldsets = (
        (
            "اطلاعات اصلی",
            {
                "fields": (
                    "section",
                    "repeatable_group",
                    "name",
                    "code",
                    "label",
                    "field_type",
                    "calendar",
                    "system_key",
                    "help_text",
                    "default_value",
                    "is_required",
                    "allow_file_sharing",
                    "show_in_process_summary",
                    "decimal_places",
                    "order",
                    "is_active",
                ),
            },
        ),
        (
            "تنظیمات گزینه‌ها",
            {
                "fields": (
                    "choice_source",
                    "choice_model",
                    "choice_static_set",
                    "choice_lookup_list",
                    "choice_label_field",
                    "choice_value_field",
                    "choice_parent_field",
                    "choice_filter_field",
                ),
            },
        ),
    )

    def formfield_for_foreignkey(
        self,
        db_field,
        request,
        **kwargs,
    ):
        if db_field.name == "choice_parent_field":
            kwargs["queryset"] = FormField.objects.filter(
                field_type=FormField.FieldType.SELECT,
                is_active=True,
            ).select_related(
                "section",
                "section__form",
            )

        elif db_field.name == "choice_model":
            kwargs["queryset"] = ContentType.objects.filter(
                model__isnull=False,
            ).order_by(
                "app_label",
                "model",
            )

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs,
        )

    @admin.display(
        description="نوع گروه",
        ordering="repeatable_group__group_type",
    )
    def repeatable_group_type(self, obj):
        if not obj.repeatable_group_id:
            return "—"

        return obj.repeatable_group.get_group_type_display()

    @admin.display(
        description="دسترسی‌ها",
    )
    def access_count(self, obj):
        return obj.access_rules.count()

    inlines = (
        FieldAccessInline,
        FormPrintFieldSettingsInline,
    )

@admin.register(
    FieldAccess,
    site=dolphin_admin_site,
)

class FieldAccessAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "field_name",
        "field_group",
        "field_form",
        "step",
        "role",
        "user",
        "can_view",
        "can_edit",
    )

    list_filter = (
        "can_view",
        "can_edit",
        "role",
        "field__repeatable_group__group_type",
        "field__section__form",
        "step__workflow",
    )

    search_fields = (
        "field__label",
        "field__name",
        "field__code",
        "field__repeatable_group__name",
        "field__section__name",
        "field__section__form__name",
        "step__name",
        "step__workflow__name",
        "user__username",
        "user__first_name",
        "user__last_name",
    )

    autocomplete_fields = (
        "field",
        "step",
        "user",
    )

    ordering = (
        "field__section__form",
        "field__section",
        "field__repeatable_group",
        "field__order",
        "step__order",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "field",
                "field__section",
                "field__section__form",
                "field__section__form__workflow",
                "field__repeatable_group",
                "step",
                "step__workflow",
                "user",
            )
        )

    @admin.display(
        description="فیلد",
        ordering="field__label",
    )
    def field_name(self, obj):
        return obj.field.label

    @admin.display(
        description="گروه",
        ordering="field__repeatable_group__name",
    )
    def field_group(self, obj):
        if obj.field.repeatable_group_id:
            return obj.field.repeatable_group.name

        return "—"

    @admin.display(
        description="فرم",
        ordering="field__section__form__name",
    )
    def field_form(self, obj):
        return obj.field.section.form.name

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(
            request,
            obj,
            **kwargs,
        )

        if obj and obj.field_id:
            workflow_id = (
                obj.field.section.form.workflow_id
            )

            form.base_fields["step"].queryset = (
                WorkflowStep.objects
                .filter(
                    workflow_id=workflow_id,
                    is_active=True,
                )
                .order_by("order")
            )

        else:
            form.base_fields["step"].queryset = (
                WorkflowStep.objects
                .filter(
                    is_active=True,
                )
                .select_related("workflow")
                .order_by(
                    "workflow__name",
                    "order",
                )
            )

        return form

@admin.register(
    FormData,
    site=dolphin_admin_site,
)
class FormDataAdmin(admin.ModelAdmin):
    list_display = (
        "instance",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "instance__workflow__name",
    )

dolphin_admin_site.index_template = "admin/index.html"


_original_get_app_list = dolphin_admin_site.get_app_list


def dolphin_get_app_list(request, app_label=None):

    app_list = _original_get_app_list(
        request,
        app_label,
    )

    for app in app_list:
        for model in app["models"]:

            model_admin = dolphin_admin_site._registry.get(
                model["model"]
            )

            if model_admin:
                model["admin_category"] = getattr(
                    model_admin,
                    "admin_category",
                    None,
                )

                model["admin_section"] = getattr(
                    model_admin,
                    "admin_section",
                    None,
                )

    return app_list

# ============================================================
# Business Calendar
# ============================================================

class WorkingIntervalInline(admin.TabularInline):
    model = WorkingInterval
    extra = 0

    fields = (
        "start_time",
        "end_time",
    )

    ordering = (
        "start_time",
    )


class WeeklyScheduleInline(admin.TabularInline):
    model = WeeklySchedule
    extra = 0

    fields = (
        "weekday",
        "is_working",
    )

    ordering = (
        "weekday",
    )


class CalendarExceptionIntervalInline(admin.TabularInline):
    model = CalendarExceptionInterval
    extra = 0

    fields = (
        "start_time",
        "end_time",
    )

    ordering = (
        "start_time",
    )


class CalendarExceptionInline(admin.TabularInline):
    model = CalendarException
    extra = 0

    fields = (
        "date",
        "status",
        "title",
        "description",
    )

    ordering = (
        "date",
    )

@admin.register(
    WorkingInterval,
    site=dolphin_admin_site,
)
class WorkingIntervalAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "sla"

    list_display = (
        "weekly_schedule",
        "start_time",
        "end_time",
    )

    list_filter = (
        "weekly_schedule__calendar",
        "weekly_schedule__weekday",
    )

    search_fields = (
        "weekly_schedule__calendar__name",
    )

    autocomplete_fields = (
        "weekly_schedule",
    )

    ordering = (
        "weekly_schedule__calendar",
        "weekly_schedule__weekday",
        "start_time",
    )


@admin.register(
    CalendarExceptionInterval,
    site=dolphin_admin_site,
)
class CalendarExceptionIntervalAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "sla"

    list_display = (
        "exception",
        "start_time",
        "end_time",
    )

    list_filter = (
        "exception__calendar",
        "exception__status",
        "exception__date",
    )

    search_fields = (
        "exception__calendar__name",
        "exception__title",
        "exception__description",
    )

    autocomplete_fields = (
        "exception",
    )

    ordering = (
        "exception__calendar",
        "exception__date",
        "start_time",
    )


@admin.register(
    BusinessCalendar,
    site=dolphin_admin_site,
)
class BusinessCalendarAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "sla"

    list_display = (
        "name",
        "timezone",
        "is_active",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "is_active",
        "timezone",
    )

    search_fields = (
        "name",
        "timezone",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "name",
    )

    inlines = (
        WeeklyScheduleInline,
        CalendarExceptionInline,
    )

@admin.register(
    WeeklySchedule,
    site=dolphin_admin_site,
)
class WeeklyScheduleAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "sla"

    list_display = (
        "calendar",
        "weekday",
        "is_working",
    )

    list_filter = (
        "calendar",
        "weekday",
        "is_working",
    )

    search_fields = (
        "calendar__name",
    )

    autocomplete_fields = (
        "calendar",
    )

    ordering = (
        "calendar",
        "weekday",
    )

    fieldsets = (
            (
                "تقویم کاری",
                {
                    "fields": (
                        "calendar",
                        "weekday",
                        "is_working",
                    ),
                },
            ),
        )

    inlines = (
        WorkingIntervalInline,
    )


@admin.register(
    CalendarException,
    site=dolphin_admin_site,
)
class CalendarExceptionAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "sla"

    list_display = (
        "calendar",
        "date",
        "status",
        "title",
    )

    list_filter = (
        "calendar",
        "status",
        "date",
    )

    search_fields = (
        "calendar__name",
        "title",
        "description",
    )

    autocomplete_fields = (
        "calendar",
    )

    ordering = (
        "calendar",
        "date",
    )


    fieldsets = (
            (
                "استثنا",
                {
                    "fields": (
                        "calendar",
                        "date",
                        "status",
                        "title",
                        "description",
                    ),
                },
            ),
        )

    inlines = (
        CalendarExceptionIntervalInline,
    )

dolphin_admin_site.get_app_list = dolphin_get_app_list
