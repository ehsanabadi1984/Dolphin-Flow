from django import forms
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from .models import (
    Workflow,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowInstance,
    WorkflowTransition,
    WorkflowTransitionExecution,
    WorkflowPermission,
)


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




@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
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

@admin.register(WorkflowMembership)
class WorkflowMembershipAdmin(admin.ModelAdmin):
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

@admin.register(WorkflowStep)
class WorkflowStepAdmin(admin.ModelAdmin):
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

@admin.register(WorkflowTransition)
class WorkflowTransitionAdmin(admin.ModelAdmin):
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

@admin.register(WorkflowPermission)
class WorkflowPermissionAdmin(admin.ModelAdmin):
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

@admin.register(WorkflowInstance)
class WorkflowInstanceAdmin(admin.ModelAdmin):
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

@admin.register(WorkflowStepExecution)
class WorkflowStepExecutionAdmin(admin.ModelAdmin):
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

@admin.register(WorkflowTransitionExecution)
class WorkflowTransitionExecutionAdmin(admin.ModelAdmin):
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