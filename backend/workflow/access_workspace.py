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
    return render(
        request,
        "admin/workflow/access_security_workspace_list.html",
        {"title": "Access & Security Workspace", "workflows": workflows},
    )


def _resolve_context(workflow, request):
    memberships = (
        workflow.memberships
        .filter(is_active=True, user__is_active=True)
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

    step_id = request.GET.get("step", "").strip()

    if not subject:
        if subject_type == "user":
            membership = memberships.first()
            subject = str(membership.user_id) if membership else ""
        else:
            subject = WorkflowMembership.Role.VIEWER

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


def _subject_filter(subject_type, subject):
    if subject_type == "user":
        return {"user_id": subject, "role__isnull": True}
    return {"user__isnull": True, "role": subject}


def _permission_exists(workflow, subject_type, subject_value, *, action, step=None, transition=None):
    return WorkflowPermission.objects.filter(
        workflow=workflow,
        action=action,
        effect=WorkflowPermission.Effect.ALLOW,
        step=step,
        transition=transition,
        **_subject_filter(subject_type, subject_value),
    ).exists()


def _matrix_context(workflow, subject_type, subject, step):
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

    workflow_permissions = {
        action: _permission_exists(workflow, subject_type, subject, action=action)
        for action, _label in WORKFLOW_ACTIONS
    }
    step_permissions = {
        action: _permission_exists(workflow, subject_type, subject, action=action, step=step)
        for action, _label in STEP_ACTIONS
    }
    transition_permissions = {
        transition.pk: _permission_exists(
            workflow,
            subject_type,
            subject,
            action=WorkflowPermission.Action.TRANSITION,
            transition=transition,
        )
        for transition in transitions
    }

    field_rules = FieldAccess.objects.filter(
        field__in=fields,
        step=step,
        **_subject_filter(subject_type, subject),
    )
    field_rules = {rule.field_id: rule for rule in field_rules}

    group_rules = RepeatableGroupAccess.objects.filter(
        group__in=groups,
        step=step,
        **_subject_filter(subject_type, subject),
    )
    group_rules = {rule.group_id: rule for rule in group_rules}

    return {
        "workflow_permission_rows": [
            {"value": action, "label": label, "enabled": workflow_permissions[action]}
            for action, label in WORKFLOW_ACTIONS
        ],
        "step_permission_rows": [
            {"value": action, "label": label, "enabled": step_permissions[action]}
            for action, label in STEP_ACTIONS
        ],
        "field_rows": [
            {
                "field": field,
                "view": bool(field_rules.get(field.pk) and field_rules[field.pk].can_view),
                "edit": bool(field_rules.get(field.pk) and field_rules[field.pk].can_edit),
            }
            for field in fields
        ],
        "group_rows": [
            {
                "group": group,
                "view": bool(group_rules.get(group.pk) and group_rules[group.pk].can_view),
                "edit": bool(group_rules.get(group.pk) and group_rules[group.pk].can_edit),
                "add": bool(group_rules.get(group.pk) and group_rules[group.pk].can_add),
                "delete": bool(group_rules.get(group.pk) and group_rules[group.pk].can_delete),
            }
            for group in groups
        ],
        "transition_rows": [
            {"transition": transition, "allowed": transition_permissions[transition.pk]}
            for transition in transitions
        ],
    }


def access_security_workspace(request, workflow_id):
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    memberships, steps, subject_type, subject, selected_step, selected_user = _resolve_context(
        workflow,
        request,
    )

    if request.method == "POST" and request.POST.get("workspace_action") == "save_matrix":
        post_subject_type = request.POST.get("subject_type", subject_type)
        post_subject = request.POST.get("subject", subject)
        post_step = request.POST.get("step", str(selected_step.pk) if selected_step else "")
        step = steps.filter(pk=post_step).first()
        valid_subject = (
            post_subject_type == "user" and memberships.filter(user_id=post_subject).exists()
        ) or (
            post_subject_type == "role"
            and post_subject in dict(WorkflowMembership.Role.choices)
        )

        if step is None:
            messages.error(request, "مرحله انتخاب‌شده معتبر نیست.")
        elif not valid_subject:
            messages.error(request, "Subject انتخاب‌شده معتبر نیست.")
        else:
            try:
                save_access_matrix(
                    workflow=workflow,
                    subject_type=post_subject_type,
                    subject_value=post_subject,
                    step=step,
                    post_data=request.POST,
                )
                messages.success(request, "دسترسی‌ها با موفقیت ذخیره شدند.")
            except (TypeError, ValueError):
                messages.error(request, "اطلاعات دسترسی معتبر نیست.")

        return redirect(
            _workspace_url(
                workflow,
                subject_type=post_subject_type,
                subject=post_subject,
                step=post_step,
            )
        )

    matrix = _matrix_context(workflow, subject_type, subject, selected_step) if selected_step and subject else None

    return render(
        request,
        "admin/workflow/access_security_workspace.html",
        {
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
        },
    )
