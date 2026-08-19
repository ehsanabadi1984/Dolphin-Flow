from django import forms
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.contrib.admin.sites import site
from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .models import (
    Workflow,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowInstance,
    WorkflowTransition,
    WorkflowTransitionExecution,
    WorkflowPermission,

    DeviceType,
    DeviceModel,
    Device,
    DeviceIdentifier,

    FormDefinition,
    FormSection,
    FormRepeatableGroup,
    FormField,
    FieldAccess,
    FormData,
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

@admin.register(
    WorkflowStep,
    site=dolphin_admin_site,
)
class WorkflowStepAdmin(admin.ModelAdmin):

    admin_category = "workflows"
    admin_section = "definition"

    list_display = (
        "workflow",
        "order",
        "name",
        "code",
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
        "user",
        "role",
        "action",
        "effect",
        "step",
        "transition",
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

    list_display = (
        "id",
        "workflow",
        "current_step",
        "started_by",
        "status",
        "started_at",
        "completed_at",
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


# ============================================================
# Workflow Step Execution
# ============================================================

@admin.register(
    WorkflowStepExecution,
    site=dolphin_admin_site,
)
class WorkflowStepExecutionAdmin(admin.ModelAdmin):

    admin_category = "executions"

    list_display = (
        "id",
        "instance",
        "workflow_step",
        "performed_by",
        "performed_at",
    )

    list_filter = (
        "workflow_step__workflow",
        "workflow_step",
        "performed_by",
        "performed_at",
    )

    search_fields = (
        "instance__workflow__name",
        "instance__pk",
        "workflow_step__name",
        "performed_by__username",
        "performed_by__first_name",
        "performed_by__last_name",
    )

    readonly_fields = (
        "instance",
        "workflow_step",
        "performed_by",
        "performed_at",
        "notes",
        "data",
    )

    ordering = (
        "-performed_at",
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

    list_display = (
        "id",
        "instance",
        "transition",
        "performed_by",
        "performed_at",
    )

    list_filter = (
        "transition__workflow",
        "transition",
        "performed_by",
        "performed_at",
    )

    search_fields = (
        "instance__workflow__name",
        "instance__pk",
        "transition__name",
        "performed_by__username",
        "performed_by__first_name",
        "performed_by__last_name",
    )

    readonly_fields = (
        "instance",
        "transition",
        "performed_by",
        "performed_at",
        "notes",
        "data",
    )

    ordering = (
        "-performed_at",
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
        "order",
        "is_required",
        "is_active",
    )

    list_filter = (
        "is_active",
        "is_required",
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


@admin.register(
    FormField,
    site=dolphin_admin_site,
)
class FormFieldAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "label",
        "section",
        "repeatable_group",
        "code",
        "field_type",
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

@admin.register(
    FieldAccess,
    site=dolphin_admin_site,
)
class FieldAccessAdmin(admin.ModelAdmin):

    admin_category = "forms"

    list_display = (
        "field",
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
    )

    search_fields = (
        "field__label",
        "field__code",
    )


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


dolphin_admin_site.get_app_list = dolphin_get_app_list