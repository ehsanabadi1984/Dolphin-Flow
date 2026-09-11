from django import forms
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db.models import Max
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Workflow, WorkflowStep, WorkflowTransition


User = get_user_model()


class WorkflowWorkspaceForm(forms.ModelForm):
    class Meta:
        model = Workflow
        fields = ("name", "code", "description", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class WorkflowStepWorkspaceForm(forms.ModelForm):
    class Meta:
        model = WorkflowStep
        fields = ("name", "description", "assigned_to", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, workflow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow = workflow

        users = User.objects.filter(is_active=True)
        if self.instance and self.instance.assigned_to_id:
            users = User.objects.filter(is_active=True) | User.objects.filter(
                pk=self.instance.assigned_to_id,
            )

        self.fields["assigned_to"].queryset = users.distinct().order_by(
            "first_name", "last_name", "username"
        )
        self.fields["assigned_to"].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.workflow = self.workflow
        if not instance.pk:
            last_order = (
                WorkflowStep.objects
                .filter(workflow=self.workflow)
                .aggregate(max_order=Max("order"))
                .get("max_order")
            )
            instance.order = (last_order + 1) if last_order is not None else 1
        if commit:
            instance.save()
        return instance


class WorkflowTransitionWorkspaceForm(forms.ModelForm):
    class Meta:
        model = WorkflowTransition
        fields = ("from_step", "to_step", "name", "description", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, workflow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow = workflow
        active_steps = WorkflowStep.objects.filter(
            workflow=workflow,
            is_active=True,
        )
        step_ids = list(active_steps.values_list("pk", flat=True))
        if self.instance and self.instance.pk:
            if self.instance.from_step_id:
                step_ids.append(self.instance.from_step_id)
            if self.instance.to_step_id:
                step_ids.append(self.instance.to_step_id)

        steps = WorkflowStep.objects.filter(
            workflow=workflow,
            pk__in=set(step_ids),
        ).order_by("order")
        self.fields["from_step"].queryset = steps
        self.fields["to_step"].queryset = steps
        self.fields["to_step"].required = False

    def clean(self):
        cleaned = super().clean()
        from_step = cleaned.get("from_step")
        to_step = cleaned.get("to_step")
        if from_step and from_step.workflow_id != self.workflow.pk:
            self.add_error("from_step", "مرحله انتخاب‌شده متعلق به این فرآیند نیست.")
        if to_step and to_step.workflow_id != self.workflow.pk:
            self.add_error("to_step", "مرحله انتخاب‌شده متعلق به این فرآیند نیست.")
        if from_step and to_step and from_step.pk == to_step.pk:
            self.add_error("to_step", "مرحله مبدأ و مقصد نمی‌توانند یکسان باشند.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.workflow = self.workflow
        if commit:
            instance.save()
        return instance


def _workspace_redirect(request, **params):
    workflow_id = params.pop("workflow_id")
    url = reverse("process_workspace", kwargs={"workflow_id": workflow_id})
    query = "&".join(
        f"{key}={value}" for key, value in params.items() if value
    )
    if query:
        url = f"{url}?{query}"
    return redirect(url)


def process_workspace_list(request):
    workflows = Workflow.objects.all().order_by("name")
    create_form = WorkflowWorkspaceForm()

    if request.method == "POST":
        create_form = WorkflowWorkspaceForm(request.POST)
        if create_form.is_valid():
            workflow = create_form.save()
            messages.success(request, f"فرآیند «{workflow.name}» ایجاد شد.")
            return redirect(
                reverse("process_workspace", kwargs={"workflow_id": workflow.pk})
            )

    return render(
        request,
        "admin/workflow/process_workspace_list.html",
        {
            "title": "Process Workspace",
            "workflows": workflows,
            "create_form": create_form,
        },
    )


def process_workspace(request, workflow_id):
    workflow = get_object_or_404(Workflow, pk=workflow_id)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "save_workflow":
            form = WorkflowWorkspaceForm(request.POST, instance=workflow)
            if form.is_valid():
                form.save()
                messages.success(request, "مشخصات فرآیند ذخیره شد.")
            else:
                messages.error(request, "اطلاعات فرآیند معتبر نیست.")
            return _workspace_redirect(request, workflow_id=workflow.pk)

        if action == "add_step":
            form = WorkflowStepWorkspaceForm(workflow, request.POST)
            if form.is_valid():
                step = form.save()
                messages.success(request, "مرحله جدید اضافه شد.")
                return _workspace_redirect(
                    request, workflow_id=workflow.pk, step=step.pk
                )
            messages.error(request, "اطلاعات مرحله معتبر نیست.")
            return _workspace_redirect(request, workflow_id=workflow.pk)

        if action == "edit_step":
            step = get_object_or_404(
                WorkflowStep,
                pk=request.POST.get("step_id"),
                workflow=workflow,
            )
            form = WorkflowStepWorkspaceForm(workflow, request.POST, instance=step)
            if form.is_valid():
                form.save()
                messages.success(request, "مرحله ذخیره شد.")
            else:
                messages.error(request, "اطلاعات مرحله معتبر نیست.")
            return _workspace_redirect(
                request, workflow_id=workflow.pk, step=step.pk
            )

        if action == "delete_step":
            step = get_object_or_404(
                WorkflowStep,
                pk=request.POST.get("step_id"),
                workflow=workflow,
            )
            step_name = step.name
            try:
                step.delete()
            except ProtectedError:
                messages.error(
                    request,
                    (
                        f"مرحله «{step_name}» قابل حذف نیست؛ این مرحله هنوز "
                        "در داده‌های وابسته استفاده شده است. ابتدا Transitionها "
                        "یا سوابق/داده‌های وابسته را مدیریت کنید."
                    ),
                )
            else:
                messages.success(request, f"مرحله «{step_name}» حذف شد.")
            return _workspace_redirect(request, workflow_id=workflow.pk)

        if action == "add_transition":
            form = WorkflowTransitionWorkspaceForm(workflow, request.POST)
            if form.is_valid():
                transition = form.save()
                messages.success(request, "ارتباط بین مراحل ایجاد شد.")
                return _workspace_redirect(
                    request, workflow_id=workflow.pk, transition=transition.pk
                )
            messages.error(request, "اطلاعات Transition معتبر نیست.")
            return _workspace_redirect(request, workflow_id=workflow.pk)

        if action == "edit_transition":
            transition = get_object_or_404(
                WorkflowTransition,
                pk=request.POST.get("transition_id"),
                workflow=workflow,
            )
            form = WorkflowTransitionWorkspaceForm(
                workflow,
                request.POST,
                instance=transition,
            )
            if form.is_valid():
                form.save()
                messages.success(request, "Transition ذخیره شد.")
            else:
                messages.error(request, "اطلاعات Transition معتبر نیست.")
            return _workspace_redirect(
                request, workflow_id=workflow.pk, transition=transition.pk
            )

        if action == "delete_transition":
            transition = get_object_or_404(
                WorkflowTransition,
                pk=request.POST.get("transition_id"),
                workflow=workflow,
            )
            transition_name = transition.name
            try:
                transition.delete()
            except ProtectedError:
                messages.error(
                    request,
                    (
                        f"Transition «{transition_name}» قابل حذف نیست؛ "
                        "این Transition هنوز در داده‌های وابسته یا سوابق اجرا "
                        "استفاده شده است."
                    ),
                )
            else:
                messages.success(request, f"Transition «{transition_name}» حذف شد.")
            return _workspace_redirect(request, workflow_id=workflow.pk)

        if action == "toggle_step":
            step = get_object_or_404(
                WorkflowStep,
                pk=request.POST.get("step_id"),
                workflow=workflow,
            )
            step.is_active = not step.is_active
            step.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "وضعیت مرحله تغییر کرد.")
            return _workspace_redirect(request, workflow_id=workflow.pk, step=step.pk)

        if action == "toggle_transition":
            transition = get_object_or_404(
                WorkflowTransition,
                pk=request.POST.get("transition_id"),
                workflow=workflow,
            )
            transition.is_active = not transition.is_active
            transition.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "وضعیت Transition تغییر کرد.")
            return _workspace_redirect(
                request, workflow_id=workflow.pk, transition=transition.pk
            )

    steps = workflow.steps.select_related("assigned_to").order_by("order")
    transitions = (
        workflow.transitions
        .select_related("from_step", "to_step")
        .order_by("from_step__order", "to_step__order", "name")
    )

    selected_step = None
    selected_transition = None
    selected_step_id = request.GET.get("step")
    selected_transition_id = request.GET.get("transition")

    if selected_step_id:
        selected_step = next(
            (step for step in steps if str(step.pk) == selected_step_id),
            None,
        )
    if selected_transition_id:
        selected_transition = next(
            (
                transition
                for transition in transitions
                if str(transition.pk) == selected_transition_id
            ),
            None,
        )

    step_form = (
        WorkflowStepWorkspaceForm(workflow, instance=selected_step)
        if selected_step
        else WorkflowStepWorkspaceForm(workflow)
    )
    transition_form = (
        WorkflowTransitionWorkspaceForm(workflow, instance=selected_transition)
        if selected_transition
        else WorkflowTransitionWorkspaceForm(workflow)
    )

    return render(
        request,
        "admin/workflow/process_workspace.html",
        {
            "title": f"Process Workspace — {workflow.name}",
            "workflow": workflow,
            "workflow_form": WorkflowWorkspaceForm(instance=workflow),
            "steps": steps,
            "transitions": transitions,
            "step_form": step_form,
            "transition_form": transition_form,
            "selected_step": selected_step,
            "selected_transition": selected_transition,
        },
    )
