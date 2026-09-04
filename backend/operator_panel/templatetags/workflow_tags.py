from django import template

from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    FormData,
    InstanceDevice,
    WorkflowInstance,
    WorkflowStep,
)
from operator_panel.dashboard_services import DashboardService


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
    """
    Return workflows the current user is authorized to start.

    On the dashboard the queryset is already part of the view context, so
    it is reused instead of being recomputed for the sidebar.
    """
    request = context.get("request")
    if not request or not request.user.is_authenticated:
        return []

    existing = context.get("startable_workflows")
    if existing is not None:
        return existing

    return (
        WorkflowAuthorizationService
        .get_startable_workflows(request.user)
        .order_by("name")
    )


@register.simple_tag(takes_context=True)
def sidebar_counts(context):
    """
    Return workflow counts using the dashboard's shared semantics.

    On the dashboard the counters are part of the view context (computed
    once by DashboardService.get_context), so they are reused instead of
    being recomputed for the sidebar.
    """
    request = context.get("request")
    if not request or not request.user.is_authenticated:
        return {
            "tasks": 0,
            "pending": 0,
            "active": 0,
        }

    existing = context.get("sidebar_counts")
    if existing is not None:
        return existing

    return DashboardService(request.user).get_sidebar_counts()


@register.simple_tag
def recent_processes(user, limit=10):
    """Return the user's newest meaningful workflow instances."""
    if not user or not user.is_authenticated:
        return []

    return list(
        DashboardService.meaningful_instance_queryset(user)[:limit]
    )
