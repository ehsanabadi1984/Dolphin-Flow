from django import template

from workflow.authorization import WorkflowAuthorizationService
from workflow.models import FormData, InstanceDevice, WorkflowInstance, WorkflowStep


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
