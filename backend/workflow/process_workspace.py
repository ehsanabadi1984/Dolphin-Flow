from django import forms
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db.models import Max
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
        self.fields["assigned_to"].queryset = (
            User.objects.filter(is_active=True)
            .order_by("first_name", "last_name", "username")
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
        steps = (
            WorkflowStep.objects
            .filter(workflow=workflow, is_active=True)
            .order_by("order")
        )
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


def process_workspace_list(request):
    workflows = Workflow.objects.all().order_by("name")
    create_form = WorkflowWorkspaceForm()

    if request.method == "POST":
        create_form = WorkflowWorkspaceForm(request.POST)
        if create_form.is_valid():
            workflow = create_form.save()
            messages.success(request, f"فرآیند «{workflow.name}» ایجاد شد.")
            return redirect(
                reverse(
                    "process_workspace",
                    kwargs={"workflow_id": workflow.pk},
                )
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
            return redirect(request.path)

        if action == "add_step":
            form = WorkflowStepWorkspaceForm(workflow, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "مرحله جدید اضافه شد.")
            else:
                messages.error(request, "اطلاعات مرحله معتبر نیست.")
            return redirect(request.path)

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
            return redirect(request.path)

        if action == "add_transition":
            form = WorkflowTransitionWorkspaceForm(workflow, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "ارتباط بین مراحل ایجاد شد.")
            else:
                messages.error(request, "اطلاعات Transition معتبر نیست.")
            return redirect(request.path)

        if action == "toggle_step":
            step = get_object_or_404(
                WorkflowStep,
                pk=request.POST.get("step_id"),
                workflow=workflow,
            )
            step.is_active = not step.is_active
            step.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "وضعیت مرحله تغییر کرد.")
            return redirect(request.path)

        if action == "toggle_transition":
            transition = get_object_or_404(
                WorkflowTransition,
                pk=request.POST.get("transition_id"),
                workflow=workflow,
            )
            transition.is_active = not transition.is_active
            transition.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "وضعیت Transition تغییر کرد.")
            return redirect(request.path)

    workflow_form = WorkflowWorkspaceForm(instance=workflow)
    steps = (
        workflow.steps
        .select_related("assigned_to")
        .order_by("order")
    )
    transitions = (
        workflow.transitions
        .select_related("from_step", "to_step")
        .order_by("from_step__order", "to_step__order")
    )

    return render(
        request,
        "admin/workflow/process_workspace.html",
        {
            "title": f"Process Workspace — {workflow.name}",
            "workflow": workflow,
            "workflow_form": workflow_form,
            "steps": steps,
            "transitions": transitions,
            "step_form": WorkflowStepWorkspaceForm(workflow),
            "transition_form": WorkflowTransitionWorkspaceForm(workflow),
        },
    )
