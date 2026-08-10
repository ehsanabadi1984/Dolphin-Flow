from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowTransition,
)

from workflow.services import WorkflowExecutionService


@login_required
def dashboard(request):
    workflows = (
        Workflow.objects
        .filter(
            is_active=True,
            memberships__user=request.user,
            memberships__is_active=True,
        )
        .distinct()
        .order_by("name")
    )

    instances = (
        WorkflowInstance.objects
        .filter(
            started_by=request.user,
        )
        .select_related(
            "workflow",
            "current_step",
        )
        .order_by("-started_at")
    )

    return render(
        request,
        "operator_panel/dashboard.html",
        {
            "user": request.user,
            "workflows": workflows,
            "instances": instances,
        },
    )


@login_required
def workflow_instance(request, instance_id):
    """
    Display a workflow instance and its available transitions.
    """

    instance = get_object_or_404(
        WorkflowInstance.objects.select_related(
            "workflow",
            "current_step",
        ),
        pk=instance_id,
    )

    # ---------------------------------------------------------
    # Authorization: VIEW
    # ---------------------------------------------------------

    from workflow.authorization import (
        WorkflowAuthorizationService,
    )

    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action="VIEW",
        step=instance.current_step,
    )

    transitions = (
        WorkflowTransition.objects
        .filter(
            workflow=instance.workflow,
            from_step=instance.current_step,
            is_active=True,
        )
        .select_related(
            "from_step",
            "to_step",
        )
    )

    return render(
        request,
        "operator_panel/workflow_instance.html",
        {
            "instance": instance,
            "transitions": transitions,
        },
    )


@login_required
def execute_transition(request, instance_id, transition_id):
    """
    Execute a workflow transition for an instance.
    """

    if request.method != "POST":
        return redirect(
            "operator_panel:workflow_instance",
            instance_id=instance_id,
        )

    instance = get_object_or_404(
        WorkflowInstance.objects.select_related(
            "workflow",
            "current_step",
        ),
        pk=instance_id,
    )

    transition = get_object_or_404(
        WorkflowTransition.objects.select_related(
            "workflow",
            "from_step",
            "to_step",
        ),
        pk=transition_id,
    )

    try:
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=transition,
            user=request.user,
            notes=request.POST.get("notes", ""),
        )

    except PermissionDenied:
        raise

    except ValidationError as exc:
        return render(
            request,
            "operator_panel/workflow_instance.html",
            {
                "instance": instance,
                "transitions": WorkflowTransition.objects.filter(
                    workflow=instance.workflow,
                    from_step=instance.current_step,
                    is_active=True,
                ).select_related(
                    "from_step",
                    "to_step",
                ),
                "error": str(exc),
            },
            status=400,
        )

    return redirect(
        "operator_panel:workflow_instance",
        instance_id=instance.pk,
    )


@login_required
def start_workflow(request, workflow_id):
    """
    Start a new workflow instance.
    """

    if request.method != "POST":
        return redirect(
            "operator_panel:dashboard",
        )

    workflow = get_object_or_404(
        Workflow,
        pk=workflow_id,
        is_active=True,
    )

    try:
        instance = WorkflowExecutionService.start_workflow(
            workflow=workflow,
            user=request.user,
        )

    except PermissionDenied:
        raise

    except ValidationError as exc:
        return render(
            request,
            "operator_panel/dashboard.html",
            {
                "user": request.user,
                "error": str(exc),
            },
            status=400,
        )

    return redirect(
        "operator_panel:workflow_instance",
        instance_id=instance.pk,
    )