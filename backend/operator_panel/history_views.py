from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from workflow.authorization import WorkflowAuthorizationService
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

    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=HISTORY_ACTION,
    )

    return redirect(
        f"{reverse('operator_panel:workflow_instance', args=[instance.pk])}?source=history"
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

    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=HISTORY_ACTION,
    )

    previous_instance = (
        InstanceDevice.objects
        .filter(device=device)
        .exclude(instance_id=instance.pk)
        .select_related(
            "instance",
            "instance__workflow",
            "instance__current_step",
        )
        .order_by("-instance__started_at", "-received_at")
        .values_list("instance", flat=True)
        .first()
    )

    if previous_instance is None:
        raise PermissionDenied(
            "برای این دستگاه سابقه ثبت‌شده‌ای وجود ندارد."
        )

    return redirect(
        f"{reverse('operator_panel:workflow_instance', args=[previous_instance])}?source=history_device"
    )
