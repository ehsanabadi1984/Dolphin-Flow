from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .access_matrix import STEP_ACTIONS, WORKFLOW_ACTIONS, save_access_matrix
from .models import (
    FieldAccess,
    FormField,
    FormRepeatableGroup,
    RepeatableGroupAccess,
    Workflow,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
)


def _workspace_url(workflow, *, subject_type="", subject="", step=""):
    url = reverse("access_security_workspace", kwargs={"workflow_id": workflow.pk})
    params = {"subject_type": subject_type, "subject": subject, "step": step}
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    return f"{url}?{query}" if query else url


def access_security_workspace_list(request):
    workflows = Workflow.objects.order_by("name")
    return render(request, "admin/workflow/access_security_workspace_list.html", {"title": "Access & Security Workspace", "workflows": workflows})


def _resolve_context(workflow, request):
    memberships = (
        workflow.memberships.filter(is_active=True, user__is_active=True)
        .select_related("user")
        .order_by("user__username")
    )
    steps = WorkflowStep.objects.filter(workflow=workflow, is_active=True).order_by("order")

    subject_type = request.GET.get("subject_type", "user").strip()
    subject_values = [value.strip() for value in request.GET.getlist("subject") if value.strip()]
    if subject_type not in {"user", "role"}:
        subject_type = "user"

    if subject_type == "user":
        valid_subjects = {str(membership.user_id) for membership in memberships}
        subject = next((value for value in subject_values if value in valid_subjects), "")
    else:
        valid_roles = set(dict(WorkflowMembership.Role.choices))
        subject = next((value for value in subject_values if value in valid_roles), "")

    if not subject:
        if subject_type == "user":
            membership = memberships.first()
            subject = str(membership.user_id) if membership else ""
        else:
            subject = WorkflowMembership.Role.VIEWER

    step_id = request.GET.get("step", "").strip()
    selected_step = steps.filter(pk=step_id).first() if step_id else steps.first()
    if selected_step is None and steps.exists():
        selected_step = steps.first()

    selected_user = None
    if subject_type == "user" and subject:
        selected_user = memberships.filter(user_id=subject).first()
        if selected_user is None:
            selected_user = memberships.first()
            subject = str(selected_user.user_id) if selected_user else ""

    return memberships, steps, subject_type, subject, selected_step, selected_user


def _permission_exists(workflow, subject_type, subject_value, *, action, step=None, transition=None, role=None):
    scope = {"workflow": workflow, "action": action, "step": step, "transition": transition}

    if subject_type == "role":
        permissions = WorkflowPermission.objects.filter(**scope, user__isnull=True, role=subject_value)
    else:
        permissions = WorkflowPermission.objects.filter(**scope, user_id=subject_value)

    if permissions.filter(effect=WorkflowPermission.Effect.DENY).exists():
        return False
    if permissions.filter(effect=WorkflowPermission.Effect.ALLOW).exists():
        return True

    if subject_type == "user" and role:
        permissions = WorkflowPermission.objects.filter(
            **scope,
            user__isnull=True,
            role=role,
        )
        if permissions.filter(effect=WorkflowPermission.Effect.DENY).exists():
            return False
        return permissions.filter(effect=WorkflowPermission.Effect.ALLOW).exists()

    return False


def _effective_field_access(queryset, subject_type, subject, role):
    """Mirror DynamicFormService: user rules are selected by user only; role rules are fallback."""
    if subject_type == "user":
        direct_rules = queryset.filter(user_id=subject)
        role_rules = queryset.filter(user__isnull=True, role=role) if role else queryset.none()
    else:
        direct_rules = queryset.none()
        role_rules = queryset.filter(user__isnull=True, role=subject)

    states = {}
    for rule in direct_rules.order_by("pk"):
        states.setdefault(rule.field_id, {"can_view": rule.can_view, "can_edit": rule.can_edit})

    role_states = {}
    for rule in role_rules.order_by("pk"):
        state = role_states.setdefault(rule.field_id, {"can_view": False, "can_edit": False})
        state["can_view"] = state["can_view"] or rule.can_view
        state["can_edit"] = state["can_edit"] or rule.can_edit

    for field_id, state in role_states.items():
        states.setdefault(field_id, state)
    return states


def _effective_group_access(queryset, subject_type, subject, role):
    """Mirror DynamicFormService for all repeatable-group capabilities."""
    if subject_type == "user":
        direct_rules = queryset.filter(user_id=subject)
        role_rules = queryset.filter(user__isnull=True, role=role) if role else queryset.none()
    else:
        direct_rules = queryset.none()
        role_rules = queryset.filter(user__isnull=True, role=subject)

    states = {}
    for rule in direct_rules.order_by("pk"):
        states.setdefault(rule.group_id, {
            "can_view": rule.can_view,
            "can_edit": rule.can_edit,
            "can_add": rule.can_add,
            "can_delete": rule.can_delete,
        })

    role_states = {}
    for rule in role_rules.order_by("pk"):
        state = role_states.setdefault(rule.group_id, {
            "can_view": False,
            "can_edit": False,
            "can_add": False,
            "can_delete": False,
        })
        state["can_view"] = state["can_view"] or rule.can_view
        state["can_edit"] = state["can_edit"] or rule.can_edit
        state["can_add"] = state["can_add"] or rule.can_add
        state["can_delete"] = state["can_delete"] or rule.can_delete

    for group_id, state in role_states.items():
        states.setdefault(group_id, state)
    return states


def _matrix_context(workflow, subject_type, subject, step, role=None):
    fields = list(
        FormField.objects.filter(section__form__workflow=workflow, is_active=True)
        .select_related("section", "repeatable_group")
        .order_by("section__order", "repeatable_group__order", "order", "id")
    )
    groups = list(
        FormRepeatableGroup.objects.filter(section__form__workflow=workflow, is_active=True)
        .select_related("section")
        .order_by("section__order", "order", "id")
    )
    transitions = list(
        WorkflowTransition.objects.filter(workflow=workflow, from_step=step, is_active=True)
        .select_related("from_step", "to_step")
        .order_by("to_step__order", "id")
    )

    workflow_permissions = {action: _permission_exists(workflow, subject_type, subject, action=action, role=role) for action, _label in WORKFLOW_ACTIONS}
    step_permissions = {action: _permission_exists(workflow, subject_type, subject, action=action, step=step, role=role) for action, _label in STEP_ACTIONS}
    transition_permissions = {
        transition.pk: _permission_exists(workflow, subject_type, subject, action=WorkflowPermission.Action.TRANSITION, transition=transition, role=role)
        for transition in transitions
    }

    field_rules = _effective_field_access(FieldAccess.objects.filter(field__in=fields, step=step), subject_type, subject, role)
    group_rules = _effective_group_access(RepeatableGroupAccess.objects.filter(group__in=groups, step=step), subject_type, subject, role)

    return {
        "workflow_permission_rows": [{"value": action, "label": label, "enabled": workflow_permissions[action]} for action, label in WORKFLOW_ACTIONS],
        "step_permission_rows": [{"value": action, "label": label, "enabled": step_permissions[action]} for action, label in STEP_ACTIONS],
        "field_rows": [
            {"field": field, "view": bool(field_rules.get(field.pk, {}).get("can_view")), "edit": bool(field_rules.get(field.pk, {}).get("can_edit"))}
            for field in fields
        ],
        "group_rows": [
            {"group": group, "view": bool(group_rules.get(group.pk, {}).get("can_view")), "edit": bool(group_rules.get(group.pk, {}).get("can_edit")), "add": bool(group_rules.get(group.pk, {}).get("can_add")), "delete": bool(group_rules.get(group.pk, {}).get("can_delete"))}
            for group in groups
        ],
        "transition_rows": [{"transition": transition, "allowed": transition_permissions[transition.pk]} for transition in transitions],
    }


def access_security_workspace(request, workflow_id):
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    memberships, steps, subject_type, subject, selected_step, selected_user = _resolve_context(workflow, request)

    if request.method == "POST" and request.POST.get("workspace_action") == "save_matrix":
        post_subject_type = request.POST.get("subject_type", subject_type)
        post_subject = request.POST.get("subject", subject)
        post_step = request.POST.get("step", str(selected_step.pk) if selected_step else "")
        step = steps.filter(pk=post_step).first()
        valid_subject = (post_subject_type == "user" and memberships.filter(user_id=post_subject).exists()) or (post_subject_type == "role" and post_subject in dict(WorkflowMembership.Role.choices))

        if step is None:
            messages.error(request, "مرحله انتخاب‌شده معتبر نیست.")
        elif not valid_subject:
            messages.error(request, "Subject انتخاب‌شده معتبر نیست.")
        else:
            try:
                save_access_matrix(workflow=workflow, subject_type=post_subject_type, subject_value=post_subject, step=step, post_data=request.POST)
                messages.success(request, "دسترسی‌ها با موفقیت ذخیره شدند.")
            except (TypeError, ValueError):
                messages.error(request, "اطلاعات دسترسی معتبر نیست.")
        return redirect(_workspace_url(workflow, subject_type=post_subject_type, subject=post_subject, step=post_step))

    role = selected_user.role if selected_user is not None else subject if subject_type == "role" else None
    matrix = _matrix_context(workflow, subject_type, subject, selected_step, role=role) if selected_step and subject else None

    return render(request, "admin/workflow/access_security_workspace.html", {
        "workflow": workflow,
        "memberships": memberships,
        "steps": steps,
        "selected_step": selected_step,
        "selected_step_id": selected_step.pk if selected_step else "",
        "subject_type": subject_type,
        "subject": subject,
        "selected_user": selected_user,
        "role_choices": WorkflowMembership.Role.choices,
        "workflow_actions": WORKFLOW_ACTIONS,
        "step_actions": STEP_ACTIONS,
        "matrix": matrix,
        "workflow_url": _workspace_url(workflow),
    })
