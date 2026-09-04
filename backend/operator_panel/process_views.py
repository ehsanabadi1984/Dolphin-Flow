from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from workflow.models import WorkflowInstance

from .dashboard_services import DashboardService


@login_required
def my_processes(request):
    """
    List the authenticated user's meaningful workflow instances.

    The canonical population (meaningful instances started by the user
    in an active workflow that the user can still open) is shared with
    the sidebar "فرآیندهای من" badge and the dashboard active panels, so
    the badge always equals the ACTIVE rows of this page and every row
    is reachable under the authorization the instance view enforces.
    """
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    workflow_id = request.GET.get("workflow", "").strip()

    instances = DashboardService(request.user).my_processes_queryset()

    # Workflow filter options come from the full canonical population
    # (not the active search/status filters).
    workflows = (
        instances
        .values("workflow_id", "workflow__name")
        .distinct()
        .order_by("workflow__name")
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
            "page_title": "فرآیندهای من",
            "page_breadcrumb": "فرآیندهای من",
        },
    )
