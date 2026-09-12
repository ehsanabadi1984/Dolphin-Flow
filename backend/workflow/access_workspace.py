from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .history_permissions import HISTORY_ACTION, HISTORY_ACTION_LABEL
from .models import (
    Workflow,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
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
        self.fields["step"].queryset = WorkflowStep.objects.filter(workflow=workflow, is_active=True).order_by("order")
        self.fields["transition"].queryset = WorkflowTransition.objects.filter(workflow=workflow, is_active=True).order_by("from_step__order", "to_step__order")
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")

        # HISTORY is a workflow-level permission.  The normal model choices are
        # extended here explicitly because Workspace must not depend on the
        # runtime mutation performed in AppConfig.ready().
        action_choices = list(self.fields["action"].choices)
        if not any(value == HISTORY_ACTION for value, _ in action_choices):
            action_choices.append((HISTORY_ACTION, HISTORY_ACTION_LABEL))
        self.fields["action"].choices = action_choices

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        step = cleaned_data.get("step")
        transition = cleaned_data.get("transition")

        if action == HISTORY_ACTION and (step or transition):
            raise forms.ValidationError(
                "دسترسی سوابق فقط در سطح Workflow قابل تعریف است."
            )

        if step and transition and transition.workflow_id != step.workflow_id:
            raise forms.ValidationError(
                "Step و Transition باید متعلق به یک Workflow باشند."
            )

        return cleaned_data

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
        self.fields["field"].queryset = FormField.objects.filter(section__form__workflow=workflow).select_related("section", "repeatable_group").order_by("section__order", "order", "label")
        self.fields["step"].queryset = WorkflowStep.objects.filter(workflow=workflow, is_active=True).order_by("order")
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")


class RepeatableGroupAccessWorkspaceForm(forms.ModelForm):
    class Meta:
        model = RepeatableGroupAccess
        fields = ("group", "step", "role", "user", "can_view", "can_edit", "can_add", "can_delete")

    def __init__(self, workflow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = FormRepeatableGroup.objects.filter(section__form__workflow=workflow).select_related("section").order_by("section__order", "order", "name")
        self.fields["step"].queryset = WorkflowStep.objects.filter(workflow=workflow, is_active=True).order_by("order")
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")


def _workspace_url(workflow, **params):
    url = reverse("access_security_workspace", kwargs={"workflow_id": workflow.pk})
    query = "&".join(f"{k}={v}" for k, v in params.items() if v not in (None, ""))
    return f"{url}?{query}" if query else url


def access_security_workspace_list(request):
    workflows = Workflow.objects.order_by("name")
    return render(request, "admin/workflow/access_security_workspace_list.html", {
        "title": "Access & Security Workspace",
        "workflows": workflows,
    })


def _empty_forms(workflow):
    return {
        "membership_form": MembershipWorkspaceForm(workflow),
        "permission_form": WorkflowPermissionWorkspaceForm(workflow),
        "field_access_form": FieldAccessWorkspaceForm(workflow),
        "group_access_form": RepeatableGroupAccessWorkspaceForm(workflow),
    }


def _base_context(workflow, selected):
    context = _empty_forms(workflow)
    context.update({
        "workflow": workflow,
        "selected": selected,
        "memberships": workflow.memberships.select_related("user").order_by("user__username"),
        "permissions": workflow.permissions.select_related("user", "step", "transition").order_by("step__order", "transition__from_step__order", "action"),
        "field_accesses": FieldAccess.objects.filter(field__section__form__workflow=workflow).select_related("field", "field__section", "field__repeatable_group", "step", "user").order_by("field__section__order", "field__order", "step__order"),
        "group_accesses": RepeatableGroupAccess.objects.filter(group__section__form__workflow=workflow).select_related("group", "group__section", "step", "user").order_by("group__section__order", "group__order", "step__order"),
    })
    return context


def access_security_workspace(request, workflow_id):
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    selected = request.GET.get("section", "memberships")
    edit_id = request.GET.get("edit")
    edit_kind = request.GET.get("kind")
    context = _base_context(workflow, selected)

    if edit_id and edit_kind:
        edit_map = {
            "membership": (WorkflowMembership, {"workflow": workflow}, MembershipWorkspaceForm, "membership_form"),
            "permission": (WorkflowPermission, {"workflow": workflow}, WorkflowPermissionWorkspaceForm, "permission_form",),
            "field_access": (FieldAccess, {"field__section__form__workflow": workflow}, FieldAccessWorkspaceForm, "field_access_form"),
            "group_access": (RepeatableGroupAccess, {"group__section__form__workflow": workflow}, RepeatableGroupAccessWorkspaceForm, "group_access_form"),
        }
        if edit_kind in edit_map:
            model, filters, form_class, context_key = edit_map[edit_kind]
            obj = get_object_or_404(model, pk=edit_id, **filters)
            context[context_key] = form_class(workflow, instance=obj)
            context["editing"] = {"kind": edit_kind, "id": obj.pk}

    if request.method == "POST":
        action = request.POST.get("action")
        if action in {"save_membership", "save_permission", "save_field_access", "save_group_access"}:
            config = {
                "save_membership": (WorkflowMembership, {"workflow": workflow}, MembershipWorkspaceForm, "membership_form", "memberships"),
                "save_permission": (WorkflowPermission, {"workflow": workflow}, WorkflowPermissionWorkspaceForm, "permission_form", "workflow-permissions"),
                "save_field_access": (FieldAccess, {"field__section__form__workflow": workflow}, FieldAccessWorkspaceForm, "field_access_form", "field-access"),
                "save_group_access": (RepeatableGroupAccess, {"group__section__form__workflow": workflow}, RepeatableGroupAccessWorkspaceForm, "group_access_form", "group-access"),
            }
            model, filters, form_class, context_key, selected = config[action]
            obj = get_object_or_404(model, pk=request.POST["object_id"], **filters) if request.POST.get("object_id") else None
            form = form_class(workflow, request.POST, instance=obj)
            if form.is_valid():
                form.save()
                messages.success(request, "اطلاعات با موفقیت ذخیره شد.")
                return redirect(_workspace_url(workflow, section=selected))
            context[context_key] = form
            context["selected"] = selected
        elif action == "delete":
            model_map = {
                "membership": (WorkflowMembership, {"workflow": workflow}),
                "permission": (WorkflowPermission, {"workflow": workflow}),
                "field_access": (FieldAccess, {"field__section__form__workflow": workflow}),
                "group_access": (RepeatableGroupAccess, {"group__section__form__workflow": workflow}),
            }
            kind = request.POST.get("kind")
            if kind in model_map:
                model, filters = model_map[kind]
                obj = get_object_or_404(model, pk=request.POST.get("object_id"), **filters)
                obj.delete()
                messages.success(request, "رکورد حذف شد.")
            return redirect(_workspace_url(workflow, section=request.POST.get("section", "memberships")))

    return render(request, "admin/workflow/access_security_workspace.html", context)
