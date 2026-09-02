from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q, Subquery
from django.shortcuts import render

from workflow.models import (
    FormData,
    InstanceDevice,
    WorkflowInstance,
    WorkflowStep,
    WorkflowTransitionExecution,
)


@login_required
def my_processes(request):
    """List the authenticated user's meaningful workflow instances."""
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    workflow_id = request.GET.get("workflow", "").strip()

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

    instances = (
        WorkflowInstance.objects
        .filter(started_by=request.user)
        .exclude(status=WorkflowInstance.Status.DRAFT)
        .exclude(abandoned_start)
        .select_related("workflow", "current_step")
        .order_by("-started_at")
    )

    if search:
        search_filter = (
            Q(workflow__name__icontains=search)
            | Q(workflow__code__icontains=search)
            | Q(current_step__name__icontains=search)
        )
        if search.isdigit():
            search_filter |= Q(pk=int(search))
        instances = instances.filter(search_filter)

    if status:
        instances = instances.filter(status=status)

    if workflow_id.isdigit():
        instances = instances.filter(workflow_id=int(workflow_id))

    workflows = (
        WorkflowInstance.objects
        .filter(started_by=request.user)
        .exclude(status=WorkflowInstance.Status.DRAFT)
        .values("workflow_id", "workflow__name")
        .distinct()
        .order_by("workflow__name")
    )

    paginator = Paginator(instances, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "operator_panel/my_processes.html",
        {
            "page_obj": page_obj,
            "instances": page_obj.object_list,
            "workflows": workflows,
            "status_choices": WorkflowInstance.Status.choices,
            "search": search,
            "selected_status": status,
            "selected_workflow": workflow_id,
        },
    )
