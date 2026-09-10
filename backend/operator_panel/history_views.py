from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from workflow.authorization import WorkflowAuthorizationService
from workflow.history_services import HistoryService
from workflow.models import (
    Device,
    InstanceDevice,
    WorkflowInstance,
    WorkflowPermission,
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

    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
        instance=instance,
    )

    device = get_object_or_404(
        Device,
        pk=device_id,
        workflow_instances__instance=instance,
    )

    history = HistoryService.get_device_history(
        device_id=device_id,
        user=request.user,
    )

    # Keep pre-Phase-2 history visible until those records are naturally
    # replaced by immutable snapshots. New records are rendered only from
    # the stored snapshot and never read back from live InstanceDevice data.
    legacy_histories = []
    if not history:
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

    return render(
        request,
        "operator_panel/history.html",
        {
            "instance": instance,
            "device": device,
            "history": history,
            "legacy_histories": legacy_histories,
            "page_title": "سوابق",
            "page_breadcrumb": "سوابق",
        },
    )
