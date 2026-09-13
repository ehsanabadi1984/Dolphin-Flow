from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .admin import WorkflowInstanceAdmin, dolphin_admin_site
from .models import WorkflowInstance, WorkflowStep, WorkflowStepExecution
from .override_services import WorkflowOverrideService


class WorkflowInstanceOverrideForm(forms.Form):
    target_step = forms.ModelChoiceField(
        queryset=WorkflowStep.objects.none(),
        label="مرحله مقصد",
    )
    reason = forms.CharField(
        label="دلیل اصلاح مسیر",
        min_length=5,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="دلیل اصلاح مسیر را ثبت کنید. این توضیح در Timeline ذخیره می‌شود.",
    )

    def __init__(self, *args, instance, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        self.fields["target_step"].queryset = (
            WorkflowStep.objects
            .filter(
                workflow=instance.workflow,
                is_active=True,
            )
            .exclude(pk=instance.current_step_id)
            .order_by("order")
        )


class WorkflowInstanceOverrideAdmin(WorkflowInstanceAdmin):
    """Adds a dedicated, non-editing override operation to WorkflowInstance."""

    @staticmethod
    def _can_override(request):
        return (
            request.user.is_active
            and request.user.is_staff
            and (
                request.user.is_superuser
                or request.user.has_perm("workflow.change_workflowinstance")
            )
        )

    @admin.display(description="اصلاح مسیر")
    def override_link(self, obj):
        url = reverse(
            "admin:workflow_workflowinstance_override",
            args=[obj.pk],
        )
        return format_html(
            '<a class="timeline-admin-button" href="{}">'
            '<span>اصلاح مسیر</span>'
            '</a>',
            url,
        )

    def override_view(self, request, object_id):
        if not self._can_override(request):
            raise PermissionDenied()

        instance = get_object_or_404(
            WorkflowInstance.objects.select_related(
                "workflow",
                "current_step",
                "started_by",
            ),
            pk=object_id,
        )

        form = WorkflowInstanceOverrideForm(
            request.POST or None,
            instance=instance,
        )

        if request.method == "POST" and form.is_valid():
            try:
                WorkflowOverrideService.override_instance_step(
                    instance=instance,
                    target_step=form.cleaned_data["target_step"],
                    performed_by=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as exc:
                form.add_error(None, exc.message)
            else:
                return redirect(
                    "admin:workflow_workflowinstance_timeline",
                    object_id,
                )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "instance": instance,
            "form": form,
            "title": f"اصلاح مسیر فرآیند {instance.workflow.name} #{instance.pk}",
        }

        return TemplateResponse(
            request,
            "admin/workflow/workflow_instance_override.html",
            context,
        )

    def timeline_view(self, request, object_id):
        response = super().timeline_view(request, object_id)
        events = list(response.context_data.get("events", []))
        instance = response.context_data["instance"]

        step_executions = (
            WorkflowStepExecution.objects
            .filter(instance=instance)
            .select_related(
                "workflow_step",
                "performed_by",
            )
        )

        for step_execution in step_executions:
            notes = (step_execution.notes or "").strip()
            prefix = WorkflowOverrideService.OVERRIDE_NOTE_PREFIX
            if not notes.startswith(prefix):
                continue

            details = notes[len(prefix):].strip()
            path_text, separator, reason = details.partition("| دلیل:")
            reason = reason.strip() if separator else "—"
            user = (
                step_execution.performed_by.get_full_name()
                or step_execution.performed_by.username
            )

            events.append(
                {
                    "type": "transition",
                    "id": f"override-{step_execution.pk}",
                    "performed_at": step_execution.performed_at,
                    "user": user,
                    "title": "اصلاح مسیر فرآیند",
                    "description": (
                        f"{path_text.strip()} | دلیل: {reason}"
                    ),
                    "is_submitted": False,
                    "sla_completed": False,
                    "sla_breached": False,
                }
            )

        events.sort(key=lambda event: event["performed_at"])
        response.context_data["events"] = events
        return response

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/override-step/",
                self.admin_site.admin_view(self.override_view),
                name="workflow_workflowinstance_override",
            ),
        ]
        return custom_urls + urls

    list_display = WorkflowInstanceAdmin.list_display + ("override_link",)


# Replace only the WorkflowInstance admin registration. The model itself and
# the original read-only behavior remain unchanged.
if WorkflowInstance in dolphin_admin_site._registry:
    dolphin_admin_site.unregister(WorkflowInstance)

dolphin_admin_site.register(
    WorkflowInstance,
    WorkflowInstanceOverrideAdmin,
)
