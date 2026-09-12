from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import (
    Workflow,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FieldAccess,
    RepeatableGroupAccess,
)

User = get_user_model()


class MembershipWorkspaceForm(forms.ModelForm):
    class Meta:
        model = WorkflowMembership
        fields = ("user", "role", "is_active")

    def __init__(self, workflow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow = workflow
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.workflow = self.workflow
        if commit:
            obj.save()
        return obj


class WorkflowPermissionWorkspaceForm(forms.ModelForm):
    class Meta:
        model = WorkflowPermission
        fields = ("step", "transition", "user", "role", "action", "effect")

    def __init__(self, workflow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow = workflow
        self.fields["step"].queryset = WorkflowStep.objects.filter(
            workflow=workflow, is_active=True
        ).order_by("order")
        self.fields["transition"].queryset = WorkflowTransition.objects.filter(
            workflow=workflow, is_active=True
        ).order_by("from_step__order", "to_step__order")
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")

    def clean(self):
        cleaned = super().clean()
        step = cleaned.get("step")
        transition = cleaned.get("transition")
        if step and transition:
            raise forms.ValidationError("یک Permission نمی‌تواند همزمان برای Step و Transition ثبت شود.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.workflow = self.workflow
        if commit:
            obj.save()
        return obj


class FieldAccessWorkspaceForm(forms.ModelForm):
    class Meta:
        model = FieldAccess
        fields = ("field", "step", "role", "user", "can_view", "can_edit")

    def __init__(self, workflow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow = workflow
        self.fields["field"].queryset = FormField.objects.filter(
            section__form__workflow=workflow
        ).select_related("section", "section__form", "repeatable_group").order_by(
            "section__order", "order", "label"
        )
        self.fields["step"].queryset = WorkflowStep.objects.filter(
            workflow=workflow, is_active=True
        ).order_by("order")
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")


class RepeatableGroupAccessWorkspaceForm(forms.ModelForm):
    class Meta:
        model = RepeatableGroupAccess
        fields = ("group", "step", "role", "user", "can_view", "can_edit", "can_add", "can_delete")

    def __init__(self, workflow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow = workflow
        self.fields["group"].queryset = FormRepeatableGroup.objects.filter(
            section__form__workflow=workflow
        ).select_related("section", "section__form").order_by(
            "section__order", "order", "name"
        )
        self.fields["step"].queryset = WorkflowStep.objects.filter(
            workflow=workflow, is_active=True
        ).order_by("order")
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")


def _workspace_url(workflow, **params):
    url = reverse("access_security_workspace", kwargs={"workflow_id": workflow.pk})
    query = "&".join(f"{k}={v}" for k, v in params.items() if v not in (None, ""))
    return f"{url}?{query}" if query else url


def _form_context(workflow, selected):
    return {
        "membership_form": MembershipWorkspaceForm(workflow),
        "permission_form": WorkflowPermissionWorkspaceForm(workflow),
        "field_access_form": FieldAccessWorkspaceForm(workflow),
        "group_access_form": RepeatableGroupAccessWorkspaceForm(workflow),
        "selected": selected,
    }


def access_security_workspace(request, workflow_id):
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    selected = request.GET.get("section", "memberships")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "save_membership":
            obj = None
            if request.POST.get("object_id"):
                obj = get_object_or_404(WorkflowMembership, pk=request.POST["object_id"], workflow=workflow)
            form = MembershipWorkspaceForm(workflow, request.POST, instance=obj)
            if form.is_valid():
                form.save()
                messages.success(request, "عضویت فرآیند ذخیره شد.")
                return redirect(_workspace_url(workflow, section="memberships"))
            selected = "memberships"

        elif action == "save_permission":
            obj = None
            if request.POST.get("object_id"):
                obj = get_object_or_404(WorkflowPermission, pk=request.POST["object_id"], workflow=workflow)
            form = WorkflowPermissionWorkspaceForm(workflow, request.POST, instance=obj)
            if form.is_valid():
                form.save()
                messages.success(request, "Permission ذخیره شد.")
                return redirect(_workspace_url(workflow, section="workflow-permissions"))
            selected = "workflow-permissions"

        elif action == "save_field_access":
            obj = None
            if request.POST.get("object_id"):
                obj = get_object_or_404(FieldAccess, pk=request.POST["object_id"], field__section__form__workflow=workflow)
            form = FieldAccessWorkspaceForm(workflow, request.POST, instance=obj)
            if form.is_valid():
                form.save()
                messages.success(request, "دسترسی Field ذخیره شد.")
                return redirect(_workspace_url(workflow, section="field-access"))
            selected = "field-access"

        elif action == "save_group_access":
            obj = None
            if request.POST.get("object_id"):
                obj = get_object_or_404(RepeatableGroupAccess, pk=request.POST["object_id"], group__section__form__workflow=workflow)
            form = RepeatableGroupAccessWorkspaceForm(workflow, request.POST, instance=obj)
            if form.is_valid():
                form.save()
                messages.success(request, "دسترسی گروه تکرارشونده ذخیره شد.")
                return redirect(_workspace_url(workflow, section="group-access"))
            selected = "group-access"

        elif action == "delete":
            model_map = {
                "membership": (WorkflowMembership, {"workflow": workflow}),
                "permission": (WorkflowPermission, {"workflow": workflow}),
                "field_access": (FieldAccess, {"field__section__form__workflow": workflow}),
                "group_access": (RepeatableGroupAccess, {"group__section__form__workflow": workflow}),
            }
            kind = request.POST.get("kind")
            model_info = model_map.get(kind)
            if model_info:
                model, filters = model_info
                obj = get_object_or_404(model, pk=request.POST.get("object_id"), **filters)
                obj.delete()
                messages.success(request, "رکورد حذف شد.")
            return redirect(_workspace_url(workflow, section=request.POST.get("section", "memberships")))

        # Invalid POSTs render with the bound form below.
        context = _form_context(workflow, selected)
        if action == "save_membership":
            context["membership_form"] = form
        elif action == "save_permission":
            context["permission_form"] = form
        elif action == "save_field_access":
            context["field_access_form"] = form
        elif action == "save_group_access":
            context["group_access_form"] = form
        context["workflow"] = workflow
        context["memberships"] = workflow.memberships.select_related("user").order_by("user__username")
        context["permissions"] = workflow.permissions.select_related("user", "step", "transition").order_by("step__order", "transition__from_step__order", "action")
        context["field_accesses"] = FieldAccess.objects.filter(field__section__form__workflow=workflow).select_related("field", "field__section", "field__repeatable_group", "step", "user").order_by("field__section__order", "field__order", "step__order")
        context["group_accesses"] = RepeatableGroupAccess.objects.filter(group__section__form__workflow=workflow).select_related("group", "group__section", "step", "user").order_by("group__section__order", "group__order", "step__order")
        return render(request, "admin/workflow/access_security_workspace.html", context)

    context = _form_context(workflow, selected)
    context.update({
        "workflow": workflow,
        "memberships": workflow.memberships.select_related("user").order_by("user__username"),
        "permissions": workflow.permissions.select_related("user", "step", "transition").order_by("step__order", "transition__from_step__order", "action"),
        "field_accesses": FieldAccess.objects.filter(field__section__form__workflow=workflow).select_related("field", "field__section", "field__repeatable_group", "step", "user").order_by("field__section__order", "field__order", "step__order"),
        "group_accesses": RepeatableGroupAccess.objects.filter(group__section__form__workflow=workflow).select_related("group", "group__section", "step", "user").order_by("group__section__order", "group__order", "step__order"),
    })
    return render(request, "admin/workflow/access_security_workspace.html", context)
