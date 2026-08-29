from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.contenttypes.models import ContentType
from workflow.device_services import DeviceService


from workflow.notification_services import NotificationService
from workflow.form_services import DynamicFormService
from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    Device,
    DeviceIdentifier,
    FormData,
    FormRepeatableGroup,
    InstanceDevice,
    RepeatableGroupAccess,
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
from workflow.instance_device_services import InstanceDeviceService


def formfield_model_fields(request):
    content_type_id = request.GET.get("content_type")

    if not content_type_id:
        return JsonResponse({"fields": []})

    try:
        content_type = ContentType.objects.get(pk=content_type_id)
    except ContentType.DoesNotExist:
        return JsonResponse({"fields": []})

    model = content_type.model_class()

    fields = []

    for field in model._meta.get_fields():
        if not getattr(field, "concrete", False):
            continue

        if getattr(field, "auto_created", False):
            continue

        if not getattr(field, "editable", True):
            continue

        fields.append({
            "name": field.name,
            "label": str(field.verbose_name),
        })

    return JsonResponse({"fields": fields})

@login_required
def lookup_device_by_imei(request):
    if request.method != "GET":
        return JsonResponse(
            {"error": "روش درخواست نامعتبر است."},
            status=405,
        )

    imei = request.GET.get("imei", "").strip()

    if not imei:
        return JsonResponse({
            "exists": False,
        })

    device = DeviceService.get_device_by_identifier(
        identifier_type=DeviceIdentifier.IdentifierType.IMEI,
        value=imei,
    )

    if device is None:
        return JsonResponse({
            "exists": False,
        })

    device_model = device.device_model

    return JsonResponse({
        "exists": True,
        "device_id": device.pk,
        "device_type_id": device_model.device_type_id,
        "device_model_id": device_model.pk,
    })

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
        .exclude(
            status=WorkflowInstance.Status.DRAFT,
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

            print("========== DEVICE POST DEBUG ==========")
            print(request.POST)
            print("========================================")

            DynamicFormService.save_form_for_step(
                instance=instance,
                user=request.user,
                submitted_data=request.POST,
            )

        except ValidationError as exc:
            print("========== POST DEVICE DATA ==========")

            for key, value in request.POST.items():
                if "_" in key:
                    print("POST:", key, "=", value)

            print("======================================")
            form_context = (
                DynamicFormService.get_form_for_step(
                    instance=instance,
                    user=request.user,
                    submitted_data=request.POST,
                )
            )

            # normal fields
            for section in form_context["sections"]:
                for item in section["fields"]:
                    if item["field"].code in request.POST:
                        item["value"] = request.POST.get(
                            item["field"].code,
                            "",
                        )

            # non-device repeatable groups
            for section in form_context["sections"]:
                for group in section["repeatable_groups"]:
                    if group["group"].group_type == "DEVICE":
                        continue

                    group_code = group["group"].code

                    items = DynamicFormService._parse_repeatable_data(
                        submitted_data=request.POST,
                        group_code=group_code,
                    )

                    for index, raw_item in enumerate(items):
                        if index >= len(group["items"]):
                            break

                        for item_field in group["items"][index]["fields"]:
                            field_code = item_field["field"].code

                            if field_code in raw_item:
                                item_field["value"] = raw_item[field_code]

            edit_mode = True
            validation_errors = getattr(exc, "messages", [])
            print("VALIDATION_ERRORS:", repr(validation_errors))
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
                    "edit_mode": edit_mode,
                    "validation_errors": validation_errors,
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
    current_step_execution = (
        instance.step_executions
        .filter(
            workflow_step=instance.current_step,
        )
        .order_by("-performed_at")
        .first()
    )

    form_data = (
        FormData.objects
        .filter(
            instance=instance,
        )
        .first()
    )

    has_saved_data = (
        form_data is not None
        and bool(form_data.data)
    )

    if current_step_execution and current_step_execution.is_submitted:
        # مرحله فعلی Submit شده → کاملاً قفل
        edit_mode = False

    elif has_saved_data:
        # Save شده ولی Submit نشده 
        edit_mode = True

    else:
        # هنوز چیزی Save نشده → فرم از ابتدا قابل ویرایش است
        edit_mode = True

    return render(
        request,
        "operator_panel/workflow_instance.html",
        {
            "instance": instance,
            "transitions": transitions,
            "dynamic_form": dynamic_form,
            "edit_mode": edit_mode,
            "current_step_execution": current_step_execution,
        },
    )


def _require_device_group_edit_permission(*, instance, user, group_code):
    current_execution = (
        instance.step_executions
        .filter(workflow_step=instance.current_step)
        .order_by("-performed_at")
        .first()
    )
    if instance.status != WorkflowInstance.Status.ACTIVE or (
        current_execution and current_execution.is_submitted
    ):
        raise ValidationError("این مرحله دیگر قابل ویرایش نیست.")

    group = get_object_or_404(
        FormRepeatableGroup,
        code=group_code,
        group_type=FormRepeatableGroup.GroupType.DEVICE,
        is_active=True,
        section__form__workflow=instance.workflow,
        section__form__is_active=True,
    )
    roles = instance.workflow.memberships.filter(
        user=user,
        is_active=True,
    ).values_list("role", flat=True)
    rules = RepeatableGroupAccess.objects.filter(
        group=group,
        step=instance.current_step,
    )
    user_rule = rules.filter(user=user).first()
    can_edit = (
        user_rule.can_edit
        if user_rule
        else rules.filter(role__in=roles, user__isnull=True, can_edit=True).exists()
    )
    if not can_edit:
        raise PermissionDenied("کاربر اجازه حذف دستگاه را ندارد.")
    return group


@login_required
def delete_device(request, instance_id, group_code, instance_device_id):
    if request.method != "POST":
        return redirect("operator_panel:workflow_instance", instance_id=instance_id)

    instance = get_object_or_404(
        WorkflowInstance.objects.select_related("workflow", "current_step"),
        pk=instance_id,
    )
    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
    )
    _require_device_group_edit_permission(
        instance=instance,
        user=request.user,
        group_code=group_code,
    )
    instance_device = get_object_or_404(
        InstanceDevice,
        pk=instance_device_id,
        instance=instance,
        is_active=True,
    )
    InstanceDeviceService.deactivate_device(instance_device=instance_device)
    messages.success(request, "دستگاه از این فرآیند حذف شد.")
    return redirect("operator_panel:workflow_instance", instance_id=instance.pk)


@login_required
def device_history(request, instance_id, device_id):
    instance = get_object_or_404(
        WorkflowInstance.objects.select_related("workflow", "current_step"),
        pk=instance_id,
    )
    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
    )
    device = get_object_or_404(
        Device,
        pk=device_id,
        workflow_instances__instance=instance,
    )
    histories = (
        InstanceDevice.objects.filter(
            device=device,
            instance__workflow__memberships__user=request.user,
            instance__workflow__memberships__is_active=True,
        )
        .select_related("instance", "instance__workflow", "instance__current_step")
        .distinct()
        .order_by("-received_at")
    )
    return render(
        request,
        "operator_panel/device_history.html",
        {"instance": instance, "device": device, "histories": histories},
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
