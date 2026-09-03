from django import template
from django.db.models import Exists, OuterRef, Q, Subquery

from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    FormData,
    InstanceDevice,
    WorkflowInstance,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransitionExecution,
)


register = template.Library()


@register.simple_tag
def is_abandoned_start(instance):
    """
    Return True when an instance is only the result of clicking
    "Start Workflow" and has no meaningful activity yet.

    This intentionally stays at the presentation layer for now so the
    workflow lifecycle itself is unchanged.
    """
    if instance.status != WorkflowInstance.Status.ACTIVE:
        return False

    if not instance.current_step_id:
        return False

    first_step_id = (
        WorkflowStep.objects
        .filter(
            workflow_id=instance.workflow_id,
            is_active=True,
        )
        .order_by("order")
        .values_list("pk", flat=True)
        .first()
    )

    if instance.current_step_id != first_step_id:
        return False

    if FormData.objects.filter(instance_id=instance.pk).exists():
        return False

    if InstanceDevice.objects.filter(
        instance_id=instance.pk,
        is_active=True,
    ).exists():
        return False

    if instance.transition_executions.exists():
        return False

    return True


@register.simple_tag(takes_context=True)
def startable_workflows(context):
    """Return workflows the current user is authorized to start."""
    request = context.get("request")
    if not request or not request.user.is_authenticated:
        return []

    return (
        WorkflowAuthorizationService
        .get_startable_workflows(request.user)
        .order_by("name")
    )


@register.simple_tag(takes_context=True)
def sidebar_counts(context):
    """Return live counts used by the operator sidebar."""
    request = context.get("request")
    if not request or not request.user.is_authenticated:
        return {
            "tasks": 0,
            "pending": 0,
            "active": 0,
        }

    user = request.user

    active_instances = (
        WorkflowInstance.objects
        .filter(status=WorkflowInstance.Status.ACTIVE)
        .select_related("workflow", "current_step")
        .filter(
            workflow__memberships__user=user,
            workflow__memberships__is_active=True,
        )
        .distinct()
    )

    tasks = 0
    pending = 0

    for instance in active_instances:
        step = instance.current_step
        if not step:
            continue

        if step.assigned_to_id == user.pk:
            tasks += 1

        can_execute = WorkflowAuthorizationService.has_permission(
            user=user,
            workflow=instance.workflow,
            action=WorkflowPermission.Action.EXECUTE,
            step=step,
            instance=instance,
        )
        can_transition = bool(
            WorkflowAuthorizationService.get_allowed_transitions(
                user=user,
                workflow=instance.workflow,
                from_step=step,
            )
        )

        if can_execute or can_transition:
            pending += 1

    return {
        "tasks": tasks,
        "pending": pending,
        "active": active_instances.count(),
    }


@register.simple_tag
def recent_processes(user, limit=10):
    """Return the user's newest meaningful workflow instances."""
    if not user or not user.is_authenticated:
        return []

    first_step_id = Subquery(
        WorkflowStep.objects
        .filter(
            workflow_id=OuterRef("workflow_id"),
            is_active=True,
        )
        .order_by("order")
        .values("pk")[:1]
    )

    has_form_data = Exists(
        FormData.objects.filter(instance_id=OuterRef("pk"))
    )
    has_active_device = Exists(
        InstanceDevice.objects.filter(
            instance_id=OuterRef("pk"),
            is_active=True,
        )
    )
    has_transition = Exists(
        WorkflowTransitionExecution.objects.filter(
            instance_id=OuterRef("pk")
        )
    )

    abandoned_start = (
        Q(
            status=WorkflowInstance.Status.ACTIVE,
            current_step_id=first_step_id,
        )
        & ~has_form_data
        & ~has_active_device
        & ~has_transition
    )

    return list(
        WorkflowInstance.objects
        .filter(started_by=user)
        .exclude(status=WorkflowInstance.Status.DRAFT)
        .exclude(abandoned_start)
        .select_related("workflow", "current_step")
        .order_by("-started_at")[:limit]
    )
