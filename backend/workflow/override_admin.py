from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.contrib.auth import get_user_model

from .admin import WorkflowInstanceAdmin, dolphin_admin_site
from .models import WorkflowInstance, WorkflowStep
from .assignment_services import WorkflowStepAssignmentService
from .override_services import WorkflowOverrideService

User = get_user_model()


class WorkflowInstanceOverrideForm(forms.Form):
    target_step = forms.ModelChoiceField(
        queryset=WorkflowStep.objects.none(),
        label="مرحله مقصد",
    )
    selected_assignee = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="مسئول مرحله مقصد",
        help_text=(
            "برای مراحلی با سیاست «انتخاب توسط تکمیل‌کننده مرحله قبل»، "
            "مسئول باید توسط Admin انتخاب شود."
        ),
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
        target_steps = (
            WorkflowStep.objects
            .filter(
                workflow=instance.workflow,
                is_active=True,
            )
            .exclude(pk=instance.current_step_id)
            .order_by("order")
        )
        self.fields["target_step"].queryset = target_steps

        # On GET, show candidates eligible for any selectable manual-assignment
        # target. On POST, narrow the queryset to the selected target step.
        selected_step = None
        if self.is_bound:
            target_step_id = self.data.get(self.add_prefix("target_step"))
            if target_step_id:
                try:
                    selected_step = target_steps.filter(pk=target_step_id).first()
                except (TypeError, ValueError):
                    selected_step = None

        candidate_ids = set()
        self.assignee_state = None
        if selected_step is not None:
            try:
                self.assignee_state = WorkflowStepAssignmentService.get_override_assignee_state(
                    workflow=instance.workflow,
                    step=selected_step,
                    instance=instance,
                )
            except ValidationError as exc:
                self.assignee_state = {
                    "required": True,
                    "assignee": None,
                    "reason": str(exc),
                }

            if self.assignee_state["required"]:
                self.fields["selected_assignee"].help_text = (
                    self.assignee_state.get("reason")
                    or "برای این مرحله باید یک مسئول واجد شرایط انتخاب کنید."
                )
                candidate_ids = {
                    user.pk
                    for user in WorkflowStepAssignmentService.get_eligible_assignees(
                        workflow=instance.workflow,
                        step=selected_step,
                    )
                }
            else:
                resolved = self.assignee_state["assignee"]
                candidate_ids = {resolved.pk}
                self.fields["selected_assignee"].initial = resolved
                self.fields["selected_assignee"].disabled = True
                self.fields["selected_assignee"].help_text = (
                    "مسئول معتبر آخرین ورود به این مرحله (یا سیاست تخصیص مرحله جدید) "
                    "به‌صورت خودکار حفظ شده است."
                )
        elif not self.is_bound:
            for step in target_steps:
                try:
                    state = WorkflowStepAssignmentService.get_override_assignee_state(
                        workflow=instance.workflow,
                        step=step,
                        instance=instance,
                    )
                except ValidationError:
                    state = {"required": True}
                if state.get("required"):
                    candidate_ids.update(
                        user.pk
                        for user in WorkflowStepAssignmentService.get_eligible_assignees(
                            workflow=instance.workflow,
                            step=step,
                        )
                    )

        self.fields["selected_assignee"].queryset = User.objects.filter(
            pk__in=candidate_ids,
            is_active=True,
        ).order_by("username")

    def clean(self):
        cleaned_data = super().clean()
        target_step = cleaned_data.get("target_step")
        selected_assignee = cleaned_data.get("selected_assignee")

        if (
            target_step
            and self.assignee_state
            and self.assignee_state.get("required")
            and selected_assignee is None
        ):
            self.add_error(
                "selected_assignee",
                self.assignee_state.get("reason")
                or "برای این مرحله، انتخاب مسئول توسط Admin الزامی است.",
            )

        return cleaned_data


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
                    selected_assignee=form.cleaned_data["selected_assignee"],
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
