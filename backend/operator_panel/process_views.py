import re
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from workflow.models import WorkflowInstance

from .dashboard_services import DashboardService, _can_take_action_q


FORM_NUMBER_PATTERN = re.compile(r"^(?P<date>\d{6})-(?P<pk>\d{6})$")


@login_required
def my_processes(request):
    """List the authenticated user's meaningful workflow instances."""
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    workflow_id = request.GET.get("workflow", "").strip()

    instances = DashboardService(request.user).my_processes_queryset()
    workflows = (
        instances.values("workflow_id", "workflow__name")
        .distinct().order_by("workflow__name")
    )

    if search:
        search_filter = (
            Q(workflow__name__icontains=search)
            | Q(workflow__code__icontains=search)
            | Q(current_step__name__icontains=search)
        )
        form_number_match = FORM_NUMBER_PATTERN.fullmatch(search)
        if form_number_match:
            form_date = datetime.strptime(form_number_match.group("date"), "%y%m%d").date()
            form_pk = int(form_number_match.group("pk"))
            search_filter |= Q(pk=form_pk, started_at__date=form_date)
        elif search.isdigit():
            search_filter |= Q(pk=int(search))
        instances = instances.filter(search_filter)

    if status:
        instances = instances.filter(status=status)
    if workflow_id.isdigit():
        instances = instances.filter(workflow_id=int(workflow_id))

    paginator = Paginator(instances, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "operator_panel/my_processes.html", {
        "page_obj": page_obj,
        "instances": page_obj.object_list,
        "workflows": workflows,
        "status_choices": WorkflowInstance.Status.choices,
        "search": search,
        "selected_status": status,
        "selected_workflow": workflow_id,
        "page_title": "فرآیندهای من",
        "page_breadcrumb": "فرآیندهای من",
    })


@login_required
def assigned_tasks(request):
    """List active workflow instances whose current step is assigned to the user."""
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    workflow_id = request.GET.get("workflow", "").strip()

    service = DashboardService(request.user)
    instances = (
        service._accessible_active_queryset()
        .filter(current_step__assigned_to_id=request.user.pk)
        .filter(_can_take_action_q(request.user))
    )

    workflows = (
        instances.values("workflow_id", "workflow__name")
        .distinct().order_by("workflow__name")
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
    return render(request, "operator_panel/assigned_tasks.html", {
        "page_obj": page_obj,
        "instances": page_obj.object_list,
        "workflows": workflows,
        "status_choices": WorkflowInstance.Status.choices,
        "search": search,
        "selected_status": status,
        "selected_workflow": workflow_id,
        "page_title": "وظایف اختصاص‌یافته به من",
        "page_breadcrumb": "وظایف اختصاص‌یافته به من",
    })
