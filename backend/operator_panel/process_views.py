import re
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from workflow.models import WorkflowInstance
from workflow.acceptance_queue_services import PendingAcceptanceQueueService
from workflow.services import WorkflowExecutionService
from workflow.process_summary_services import ProcessSummaryService

from .dashboard_enhancements import DashboardEnhancementService
from .dashboard_services import DashboardService, _can_take_action_q


FORM_NUMBER_PATTERN = re.compile(r"^(?P<date>\d{6})-(?P<pk>\d{6})$")


@login_required
def pending_acceptances(request):
    """List pending acceptance decisions available to the authenticated user."""
    queryset = PendingAcceptanceQueueService(request.user).get_queryset()
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "operator_panel/pending_acceptances.html",
        {
            "page_obj": page_obj,
            "executions": page_obj.object_list,
            "page_title": "تأییدهای در انتظار",
            "page_breadcrumb": "تأییدهای در انتظار",
        },
    )


@login_required
def pending_acceptance_detail(request, transition_execution_id):
    """Display a pending acceptance item as a read-only workflow form."""
    if request.method != "GET":
        raise PermissionDenied(
            "صفحه تأیید دریافت فقط به صورت خواندنی قابل مشاهده است."
        )

    transition_execution = (
        PendingAcceptanceQueueService(request.user)
        .get_queryset()
        .filter(pk=transition_execution_id)
        .select_related(
            "instance",
            "transition",
            "transition__from_step",
            "transition__to_step",
        )
        .first()
    )

    if transition_execution is None:
        raise PermissionDenied(
            "این مورد در صف تأیید دریافت شما نیست."
        )

    from operator_panel import views

    return views.workflow_instance(
        request,
        transition_execution.instance_id,
        _pending_acceptance=True,
        _pending_acceptance_step=transition_execution.transition.to_step,
    )



@login_required
@require_POST
def accept_pending_acceptance(request, transition_execution_id):
    """Accept a pending acceptance execution available to the user."""
    transition_execution = (
        PendingAcceptanceQueueService(request.user)
        .get_queryset()
        .filter(pk=transition_execution_id)
        .first()
    )

    if transition_execution is None:
        raise PermissionDenied(
            "این مورد در صف تأیید دریافت شما نیست."
        )

    try:
        WorkflowExecutionService.accept_transition_execution(
            transition_execution=transition_execution,
            user=request.user,
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "دریافت با موفقیت تأیید شد.")

    return redirect("operator_panel:pending_acceptances")


@login_required
@require_POST
def reject_pending_acceptance(request, transition_execution_id):
    """Reject a pending acceptance execution available to the user."""
    transition_execution = (
        PendingAcceptanceQueueService(request.user)
        .get_queryset()
        .filter(pk=transition_execution_id)
        .first()
    )

    if transition_execution is None:
        raise PermissionDenied(
            "این مورد در صف تأیید دریافت شما نیست."
        )

    try:
        WorkflowExecutionService.reject_transition_execution(
            transition_execution=transition_execution,
            user=request.user,
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            "دریافت رد شد و فرآیند به مرحله مربوطه بازگشت.",
        )

    return redirect("operator_panel:pending_acceptances")


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
    page_instances = list(page_obj.object_list)
    summaries = ProcessSummaryService.get_for_instances(
        instances=page_instances,
        user=request.user,
    )
    for instance in page_instances:
        instance.process_summary = summaries.get(instance.pk, [])

    return render(request, "operator_panel/my_processes.html", {
        "page_obj": page_obj,
        "instances": page_instances,
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


@login_required
def waiting_for_others(request):
    """List all active processes started by the user and assigned to another operator."""
    instances = DashboardEnhancementService(request.user).waiting_for_others_queryset()
    paginator = Paginator(instances, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "operator_panel/waiting_for_others.html", {
        "page_obj": page_obj,
        "instances": page_obj.object_list,
        "page_title": "در انتظار اقدام دیگران",
        "page_breadcrumb": "در انتظار اقدام دیگران",
    })


@login_required
def unfinished_processes(request):
    """Show all active processes started by the user, including hidden dashboard items."""
    service = DashboardEnhancementService(request.user)
    instances = service.unfinished_processes_queryset(include_hidden=True)
    paginator = Paginator(instances, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_instances = list(page_obj.object_list)
    service.dashboard._attach_dashboard_state(page_instances, now=timezone.now())
    hidden_ids = service.hidden_process_ids()

    for instance in page_instances:
        instance.dashboard_hidden = instance.pk in hidden_ids

    return render(request, "operator_panel/unfinished_processes.html", {
        "page_obj": page_obj,
        "instances": page_instances,
        "hidden_ids": hidden_ids,
        "page_title": "فرآیندهای نیمه‌تمام من",
        "page_breadcrumb": "فرآیندهای نیمه‌تمام من",
    })


@login_required
@require_POST
def hide_dashboard_process(request, instance_id):
    service = DashboardEnhancementService(request.user)
    if service.unfinished_processes_queryset(include_hidden=True).filter(pk=instance_id).exists():
        service.hide_process(instance_id)
    return redirect("operator_panel:dashboard")


@login_required
@require_POST
def restore_dashboard_process(request, instance_id):
    service = DashboardEnhancementService(request.user)
    service.restore_process(instance_id)
    return redirect("operator_panel:unfinished_processes")
