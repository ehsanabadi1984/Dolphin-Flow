from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from workflow.authorization import WorkflowAuthorizationService
from workflow.history_browser_service import HistoryBrowserService
from workflow.history_permissions import HISTORY_ACTION
from workflow.models import (
    Device,
    InstanceDevice,
    WorkflowInstance,
)


@login_required
def workflow_history(request, instance_id):
    instance = get_object_or_404(
        WorkflowInstance.objects.select_related(
            "workflow",
            "current_step",
        ),
        pk=instance_id,
    )

    history = HistoryBrowserService.get_history(
        user=request.user,
        instance_id=instance.pk,
    )

    if not history and HistoryBrowserService.has_stored_history(
        instance_id=instance.pk,
    ):
        raise PermissionDenied("کاربر اجازه مشاهده سوابق این فرآیند را ندارد.")

    return render(
        request,
        "operator_panel/history.html",
        {
            "instance": instance,
            "device": None,
            "history": history,
            "legacy_histories": [],
            "history_title": "سوابق اجرای فرآیند",
            "history_subtitle": instance.workflow.name,
            "page_title": "سوابق",
            "page_breadcrumb": "سوابق",
        },
    )


@login_required
def device_history(request, instance_id, device_id):
    instance = get_object_or_404(
        WorkflowInstance.objects.select_related(
            "workflow",
            "current_step",
        ),
        pk=instance_id,
    )

    device = get_object_or_404(
        Device,
        pk=device_id,
        workflow_instances__instance=instance,
    )

    history = HistoryBrowserService.get_history(
        device_id=device_id,
        user=request.user,
    )

    legacy_histories = []
    if not history and not HistoryBrowserService.has_stored_history(
        device_id=device_id,
    ):
        WorkflowAuthorizationService.require_permission(
            user=request.user,
            workflow=instance.workflow,
            action=HISTORY_ACTION,
        )

        legacy_histories = (
            InstanceDevice.objects.filter(
                device=device,
                instance__workflow__memberships__user=request.user,
                instance__workflow__memberships__is_active=True,
            )
            .select_related(
                "instance",
                "instance__workflow",
                "instance__current_step",
            )
            .distinct()
            .order_by("-received_at")
        )

    elif not history and HistoryBrowserService.has_stored_history(
        device_id=device_id,
    ):
        raise PermissionDenied("کاربر اجازه مشاهده سوابق این دستگاه را ندارد.")

    return render(
        request,
        "operator_panel/history.html",
        {
            "instance": instance,
            "device": device,
            "history": history,
            "legacy_histories": legacy_histories,
            "history_title": "سوابق دستگاه",
            "history_subtitle": str(device),
            "page_title": "سوابق",
            "page_breadcrumb": "سوابق",
        },
    )
