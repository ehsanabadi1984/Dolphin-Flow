from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.http import JsonResponse

from workflow.notification_services import NotificationService
from workflow.form_services import DynamicFormService
from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    FormData,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
    Notification,
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
    Display and save a workflow instance form.
    """

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
    )

    if request.method == "POST":
        try:
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=request.user,
                submitted_data=request.POST,
            )

        except ValidationError as exc:
            form_context = (
                DynamicFormService.get_form_for_step(
                    instance=instance,
                    user=request.user,
                )
            )

            transitions = (
                WorkflowAuthorizationService
                .get_allowed_transitions(
                    user=request.user,
                    workflow=instance.workflow,
                    from_step=instance.current_step,
                )
            )
            return render(
                request,
                "operator_panel/workflow_instance.html",
                {
                    "instance": instance,
                    "transitions": transitions,
                    "dynamic_form": form_context,
                    "error": str(exc),
                },
                status=400,
            )

        return redirect(
            "operator_panel:workflow_instance",
            instance_id=instance.pk,
        )

    transitions = (
        WorkflowAuthorizationService
        .get_allowed_transitions(
            user=request.user,
            workflow=instance.workflow,
            from_step=instance.current_step,
        )
    )

    dynamic_form = (
        DynamicFormService.get_form_for_step(
            instance=instance,
            user=request.user,
        )
    )
    edit_mode = request.GET.get("edit") == "1"

    return render(
        request,
        "operator_panel/workflow_instance.html",
        {
            "instance": instance,
            "transitions": transitions,
            "dynamic_form": dynamic_form,
            "edit_mode": edit_mode,
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
                "transitions": (
                    WorkflowTransition.objects.filter(
                        workflow=instance.workflow,
                        from_step=instance.current_step,
                        is_active=True,
                    )
                    .select_related(
                        "from_step",
                        "to_step",
                    )
                ),
                "error": str(exc),
            },
            status=400,
        )

    messages.success(
        request,
        f"فرآیند با موفقیت به «{transition.to_step.name}» منتقل شد.",
    )

    return redirect(
        "operator_panel:dashboard",
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
        print("START WORKFLOW REQUEST USER:", request.user, request.user.pk)
        print("START WORKFLOW:", workflow, workflow.pk)

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


@login_required
def clear_form_data(request, instance_id):
    print(
        "CLEAR FORM REQUEST:",
        request.method,
        "INSTANCE:",
        instance_id,
        "USER:",
        request.user,
    )
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

    if instance.status != WorkflowInstance.Status.ACTIVE:
        raise ValidationError(
            "این Workflow Instance فعال نیست."
        )

    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
    )

    DynamicFormService.clear_form_for_step(
        instance=instance,
        user=request.user,
    )

    from django.contrib import messages

    messages.success(
        request,
        "اطلاعات قابل ویرایش این مرحله پاک شد.",
    )

    return redirect(
        "operator_panel:workflow_instance",
        instance_id=instance.pk,
    )

@login_required
def submit_form(request, instance_id):
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

    if instance.status != WorkflowInstance.Status.ACTIVE:
        raise ValidationError(
            "این Workflow Instance فعال نیست."
        )

    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
    )

    try:
        DynamicFormService.submit_form_for_step(
            instance=instance,
            user=request.user,
        )

    except PermissionDenied:
        raise

    except ValidationError as exc:
        messages.error(
            request,
            str(exc),
        )

        return redirect(
            "operator_panel:workflow_instance",
            instance_id=instance.pk,
        )

    messages.success(
        request,
        "فرم با موفقیت ارسال شد و دیگر قابل ویرایش نیست.",
    )

    return redirect(
        "operator_panel:workflow_instance",
        instance_id=instance.pk,
    )


@login_required
def notifications(request):
    unread = NotificationService.get_unread(
        user=request.user,
    )

    data = []

    for notification in unread[:20]:
        data.append(
            {
                "id": notification.id,
                "title": notification.title,
                "message": notification.message,
                "type": notification.notification_type,
                "created_at": notification.created_at.isoformat(),
                "workflow_instance_id": (
                    notification.workflow_instance_id
                ),
            }
        )

    return JsonResponse(
        {
            "count": unread.count(),
            "notifications": data,
        }
    )


@login_required
def mark_notification_as_read(
    request,
    notification_id,
):
    if request.method != "POST":
        return JsonResponse(
            {"success": False},
            status=405,
        )

    notification = get_object_or_404(
        Notification,
        pk=notification_id,
        recipient=request.user,
    )

    success = NotificationService.mark_as_read(
        notification=notification,
        user=request.user,
    )
 
    return JsonResponse(
        {
            "success": success,
            "notification_id": notification.id,
            "is_read": notification.is_read,
        }
    )