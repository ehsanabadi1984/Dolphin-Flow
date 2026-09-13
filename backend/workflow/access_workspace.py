from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from urllib.parse import urlencode

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
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return f"{url}?{query}" if query else url


def _section_filter_params(source, selected):
    allowed = {
        "workflow-permissions": ("permission_user", "permission_role", "permission_action", "permission_effect", "permission_step"),
        "field-access": ("field_user", "field_role", "field_field", "field_step"),
        "group-access": ("group_user", "group_role", "group_group", "group_step"),
    }.get(selected, ())
    return {key: source.get(key, "").strip() for key in allowed if source.get(key, "").strip()}


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


def _base_context(workflow, selected, request):
    context = _empty_forms(workflow)
    permissions = workflow.permissions.select_related(
        "user", "step", "transition"
    ).order_by(
        "step__order",
        "transition__from_step__order",
        "action",
    )
    field_accesses = FieldAccess.objects.filter(
        field__section__form__workflow=workflow
    ).select_related(
        "field",
        "field__section",
        "field__repeatable_group",
        "step",
        "user",
    ).order_by(
        "field__section__order",
        "field__order",
        "step__order",
    )
    group_accesses = RepeatableGroupAccess.objects.filter(
        group__section__form__workflow=workflow
    ).select_related(
        "group",
        "group__section",
        "step",
        "user",
    ).order_by(
        "group__section__order",
        "group__order",
        "step__order",
    )

    if selected == "workflow-permissions":
        user = request.GET.get("permission_user", "").strip()
        role = request.GET.get("permission_role", "").strip()
        action = request.GET.get("permission_action", "").strip()
        effect = request.GET.get("permission_effect", "").strip()
        step = request.GET.get("permission_step", "").strip()
        if user:
            permissions = permissions.filter(
                Q(user__username__icontains=user)
                | Q(user__first_name__icontains=user)
                | Q(user__last_name__icontains=user)
                | Q(user__email__icontains=user)
            )
        if role:
            permissions = permissions.filter(role=role)
        if action:
            permissions = permissions.filter(action=action)
        if effect:
            permissions = permissions.filter(effect=effect)
        if step:
            permissions = permissions.filter(step_id=step)

    if selected == "field-access":
        user = request.GET.get("field_user", "").strip()
        role = request.GET.get("field_role", "").strip()
        field = request.GET.get("field_field", "").strip()
        step = request.GET.get("field_step", "").strip()
        if user:
            field_accesses = field_accesses.filter(
                Q(user__username__icontains=user)
                | Q(user__first_name__icontains=user)
                | Q(user__last_name__icontains=user)
                | Q(user__email__icontains=user)
            )
        if role:
            field_accesses = field_accesses.filter(role=role)
        if field:
            field_accesses = field_accesses.filter(
                Q(field__name__icontains=field)
                | Q(field__label__icontains=field)
                | Q(field__code__icontains=field)
            )
        if step:
            field_accesses = field_accesses.filter(step_id=step)

    if selected == "group-access":
        user = request.GET.get("group_user", "").strip()
        role = request.GET.get("group_role", "").strip()
        group = request.GET.get("group_group", "").strip()
        step = request.GET.get("group_step", "").strip()
        if user:
            group_accesses = group_accesses.filter(
                Q(user__username__icontains=user)
                | Q(user__first_name__icontains=user)
                | Q(user__last_name__icontains=user)
                | Q(user__email__icontains=user)
            )
        if role:
            group_accesses = group_accesses.filter(role=role)
        if group:
            group_accesses = group_accesses.filter(
                Q(group__name__icontains=group)
                | Q(group__code__icontains=group)
            )
        if step:
            group_accesses = group_accesses.filter(step_id=step)

    filter_query = request.GET.copy()
    filter_query.pop("edit", None)
    filter_query.pop("kind", None)

    action_choices = list(WorkflowPermission.Action.choices)
    if not any(value == HISTORY_ACTION for value, _ in action_choices):
        action_choices.append((HISTORY_ACTION, HISTORY_ACTION_LABEL))

    context.update({
        "workflow": workflow,
        "selected": selected,
        "memberships": workflow.memberships.select_related("user").order_by("user__username"),
        "permissions": permissions,
        "field_accesses": field_accesses,
        "group_accesses": group_accesses,
        "permission_steps": WorkflowStep.objects.filter(workflow=workflow, is_active=True).order_by("order"),
        "field_steps": WorkflowStep.objects.filter(workflow=workflow, is_active=True).order_by("order"),
        "group_steps": WorkflowStep.objects.filter(workflow=workflow, is_active=True).order_by("order"),
        "role_choices": WorkflowMembership.Role.choices,
        "permission_action_choices": action_choices,
        "permission_effect_choices": WorkflowPermission.Effect.choices,
        "filter_query": filter_query.urlencode(),
        "permission_user_filter": request.GET.get("permission_user", ""),
        "permission_role_filter": request.GET.get("permission_role", ""),
        "permission_action_filter": request.GET.get("permission_action", ""),
        "permission_effect_filter": request.GET.get("permission_effect", ""),
        "permission_step_filter": request.GET.get("permission_step", ""),
        "field_user_filter": request.GET.get("field_user", ""),
        "field_role_filter": request.GET.get("field_role", ""),
        "field_field_filter": request.GET.get("field_field", ""),
        "field_step_filter": request.GET.get("field_step", ""),
        "group_user_filter": request.GET.get("group_user", ""),
        "group_role_filter": request.GET.get("group_role", ""),
        "group_group_filter": request.GET.get("group_group", ""),
        "group_step_filter": request.GET.get("group_step", ""),
    })
    return context


def access_security_workspace(request, workflow_id):
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    selected = request.GET.get("section", "memberships")
    edit_id = request.GET.get("edit")
    edit_kind = request.GET.get("kind")
    context = _base_context(workflow, selected, request)

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
        action = request.POST.get("workspace_action")
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
                return redirect(_workspace_url(
                    workflow,
                    section=selected,
                    **_section_filter_params(request.POST, selected),
                ))
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
            selected = request.POST.get("section", "memberships")
            return redirect(_workspace_url(
                workflow,
                section=selected,
                **_section_filter_params(request.POST, selected),
            ))

    return render(request, "admin/workflow/access_security_workspace.html", context)
