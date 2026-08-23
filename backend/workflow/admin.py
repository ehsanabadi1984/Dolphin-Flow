from django import forms
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.contrib.contenttypes.models import ContentType

from .models import (
    Workflow,
    WorkflowMembership,
    WorkflowStep,
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

    BusinessCalendar,
    WeeklySchedule,
    WorkingInterval,
    CalendarException,
    CalendarExceptionInterval,
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
        "code",
    )

    autocomplete_fields = (
        "from_step",
        "to_step",
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


class WorkflowStepPermissionInline(admin.TabularInline):
    model = WorkflowPermission
    fk_name = "step"
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
    )

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

        else:
            self.fields["from_step"].queryset = (
                WorkflowStep.objects.none()
            )

            self.fields["to_step"].queryset = (
                WorkflowStep.objects.none()
            )

    def clean(self):
        cleaned_data = super().clean()

        workflow = cleaned_data.get("workflow")
        from_step = cleaned_data.get("from_step")
        to_step = cleaned_data.get("to_step")

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
        return obj.transition.to_step

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

    def has_delete_permission(self, request):
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

#---------------------
#---------------------
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

class FormFieldInline(admin.TabularInline):
    model = FormField
    extra = 0

    fields = (
        "name",
        "code",
        "field_type",
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

class FormRepeatableGroupInline(admin.TabularInline):
    model = FormRepeatableGroup
    extra = 0
    fields = (
        "name",
        "code",
        "group_type",
        "description",
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
    )

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

    extra = 0

    fields = (
        "name",
        "code",
        "field_type",
        "label",
        "help_text",
        "is_required",
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

        if choice_model_field:
            choice_model_field.label_from_instance = (
                lambda obj: f"{obj.app_label} → {obj.model}"
            )

        # --------------------------------------------------
        # Dynamic model fields
        # --------------------------------------------------

        label_field = self.fields.get("choice_label_field")
        value_field = self.fields.get("choice_value_field")
        parent_model_field = self.fields.get(
            "choice_parent_model_field"
        )

        if label_field:
            label_field.widget = forms.Select()

        if value_field:
            value_field.widget = forms.Select()

        if parent_model_field:
            parent_model_field.widget = forms.Select()

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

        # --------------------------------------------------
        # Value Field
        # --------------------------------------------------

        if value_field:

            value_field.choices = [
                ("", "---------"),
                ("id", "id (شناسه)"),
                *field_choices,
            ]

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

        # --------------------------------------------------
        # Parent Model Field
        # --------------------------------------------------

        if parent_model_field:

            relation_choices = [
                ("", "---------"),
            ]

            if model_class:

                for field in model_class._meta.get_fields():

                    if not getattr(field, "concrete", False):
                        continue

                    if getattr(field, "auto_created", False):
                        continue

                    # فقط ForeignKey
                    if not isinstance(
                        field,
                        models.ForeignKey,
                    ):
                        continue

                    related_model = field.remote_field.model

                    relation_choices.append(
                        (
                            field.name,
                            (
                                f"{field.name} "
                                f"→ "
                                f"{related_model._meta.verbose_name}"
                            ),
                        )
                    )

            parent_model_field.choices = relation_choices

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
        "choice_parent_field",
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
                    "help_text",
                    "is_required",
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
                    "choice_label_field",
                    "choice_value_field",
                    "choice_parent_field",
                    "choice_parent_model_field",
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