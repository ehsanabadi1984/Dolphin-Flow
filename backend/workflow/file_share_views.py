"""Recipient-scoped internal file-share endpoints; message ownership is the grant."""
import json
from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from .file_share_services import FileShareDraftService, FileShareMessageService
from .models import FileShareDraft, FileShareMessage, FileShareMessageEvent, WorkflowInstance, WorkflowStep
from .form_file_models import FormFile


def _payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError("بدنه درخواست JSON معتبر نیست.")


@login_required
def file_share_inbox(request):
    if request.method == "GET":
        qs = FileShareMessage.objects.filter(recipient=request.user).select_related("sender", "asset")
        drafts = FileShareDraft.objects.filter(sender=request.user, status=FileShareDraft.Status.DRAFT).select_related("recipient", "form_file")
        instance_id = request.GET.get("instance_id")
        recipients = []
        if instance_id and instance_id.isdigit():
            instance = get_object_or_404(WorkflowInstance, pk=int(instance_id))
            try:
                recipients = [{
                    "id": user.pk, "username": user.get_username(),
                    "label": str(user),
                } for user in FileShareDraftService.available_recipients(
                    instance=instance, sender=request.user
                )]
            except ValidationError as exc:
                return JsonResponse({"error": str(exc)}, status=403)
        return JsonResponse({
            "available_recipients": recipients,
            "sent_messages": [{
                "id": m.pk, "recipient": str(m.recipient), "subject": m.subject,
                "status": m.status, "file_name": m.asset.original_name,
                "sent_at": m.sent_at.isoformat(),
                "recall_url": f"/operator/file-shares/messages/{m.pk}/recall/",
            } for m in FileShareMessage.objects.filter(sender=request.user).select_related("recipient", "asset")[:100]],
            "messages": [{
                "id": m.pk, "sender": str(m.sender), "subject": m.subject,
                "body": m.body, "status": m.status, "interaction_type": m.interaction_type,
                "file_name": m.asset.original_name, "sent_at": m.sent_at.isoformat(),
                "url": f"/operator/file-shares/messages/{m.pk}/",
            } for m in qs[:100]],
            "drafts": [{
                "id": d.pk, "recipient": str(d.recipient),
                "file_name": d.form_file.original_name if d.form_file_id else "",
                "subject": d.subject, "interaction_type": d.interaction_type,
            } for d in drafts[:100]],
        })
    if request.method != "POST":
        return JsonResponse({"error": "روش درخواست نامعتبر است."}, status=405)
    try:
        data = _payload(request)
        instance = get_object_or_404(WorkflowInstance, pk=data.get("instance_id"))
        step = get_object_or_404(WorkflowStep, pk=data.get("step_id"))
        form_file = get_object_or_404(FormFile, pk=data.get("form_file_id"))
        drafts = FileShareDraftService.create_drafts(
            instance=instance, step=step, sender=request.user, form_file=form_file,
            recipient_ids=data.get("recipient_ids") or [],
            interaction_type=data.get("interaction_type", FileShareMessage.InteractionType.VIEW),
            subject=data.get("subject", ""), body=data.get("body", ""),
        )
    except (ValidationError, TypeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"draft_ids": [d.pk for d in drafts]}, status=201)


@login_required
@require_POST
def file_share_draft_update(request, draft_id):
    try:
        data = _payload(request)
        draft = FileShareDraftService.update_draft(
            draft_id=draft_id, sender=request.user,
            interaction_type=data.get("interaction_type"),
            subject=data.get("subject"), body=data.get("body"),
        )
    except (ValidationError, TypeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({
        "id": draft.pk, "subject": draft.subject, "body": draft.body,
        "interaction_type": draft.interaction_type,
    })


@login_required
@require_POST
def file_share_draft_delete(request, draft_id):
    try:
        FileShareDraftService.delete_draft(draft_id=draft_id, sender=request.user)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=404)
    return JsonResponse({"success": True})


@login_required
@require_GET
def file_share_message_detail(request, message_id):
    message = get_object_or_404(FileShareMessage.objects.select_related("asset", "sender"), pk=message_id, recipient=request.user)
    if message.status in {FileShareMessage.Status.CANCELLED, FileShareMessage.Status.EXPIRED}:
        raise PermissionDenied("این پیام دیگر فعال نیست.")
    if message.status == FileShareMessage.Status.PENDING:
        FileShareMessageService.transition_status(message=message, to_status=FileShareMessage.Status.READ, actor=request.user)
        message.refresh_from_db()
    from .models import Notification
    from .notification_services import NotificationService
    for notification in Notification.objects.filter(
        file_share_message=message, recipient=request.user, is_read=False
    ):
        NotificationService.mark_as_read(notification=notification, user=request.user)
    return JsonResponse({
        "id": message.pk, "sender": str(message.sender), "subject": message.subject,
        "body": message.body, "interaction_type": message.interaction_type,
        "status": message.status, "file_name": message.asset.original_name,
        "file_size": message.asset.file_size, "content_type": message.asset.content_type,
        "form_snapshot": message.form_snapshot,
        "download_url": f"/operator/file-shares/messages/{message.pk}/download/",
    })


@login_required
@require_GET
def file_share_message_download(request, message_id):
    message = get_object_or_404(FileShareMessage.objects.select_related("asset"), pk=message_id, recipient=request.user)
    if message.status not in {FileShareMessage.Status.PENDING, FileShareMessage.Status.READ, FileShareMessage.Status.RESPONDED, FileShareMessage.Status.COMPLETED}:
        raise PermissionDenied("دسترسی به فایل این پیام فعال نیست.")
    asset = message.asset
    if asset.storage_backend != "default" or asset.storage_deleted_at is not None:
        raise PermissionDenied("فایل این پیام در دسترس نیست.")
    try:
        stream = default_storage.open(asset.storage_name, "rb")
    except (FileNotFoundError, OSError):
        raise Http404
    FileShareMessageEvent.objects.create(message=message, event_type=FileShareMessageEvent.EventType.DOWNLOADED, actor=request.user)
    response = FileResponse(stream, as_attachment=True, filename=asset.original_name or Path(asset.storage_name).name)
    if asset.content_type:
        response["Content-Type"] = asset.content_type
    return response



@login_required
@require_POST
@transaction.atomic
def file_share_message_respond(request, message_id):
    message = get_object_or_404(
        FileShareMessage, pk=message_id, recipient=request.user
    )
    try:
        data = _payload(request)
        response_text = str(data.get("response", "")).strip()
        if not response_text:
            raise ValidationError("متن پاسخ نمی‌تواند خالی باشد.")
        if message.interaction_type == FileShareMessage.InteractionType.VIEW:
            raise ValidationError("برای این پیام امکان ارسال پاسخ تعریف نشده است.")
        if message.status == FileShareMessage.Status.PENDING:
            FileShareMessageService.transition_status(
                message=message,
                to_status=FileShareMessage.Status.READ,
                actor=request.user,
            )
        FileShareMessageService.transition_status(
            message=message,
            to_status=FileShareMessage.Status.RESPONDED,
            actor=request.user,
            details={"response": response_text[:10000]},
        )
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"success": True, "status": FileShareMessage.Status.RESPONDED})


@login_required
@require_POST
def file_share_message_complete(request, message_id):
    message = get_object_or_404(
        FileShareMessage, pk=message_id, recipient=request.user
    )
    try:
        FileShareMessageService.transition_status(
            message=message,
            to_status=FileShareMessage.Status.COMPLETED,
            actor=request.user,
            details={"source": "recipient_completion"},
        )
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"success": True, "status": FileShareMessage.Status.COMPLETED})


@login_required
@require_POST
def file_share_message_recall(request, message_id):
    message = get_object_or_404(FileShareMessage, pk=message_id, sender=request.user)
    try:
        FileShareMessageService.transition_status(message=message, to_status=FileShareMessage.Status.CANCELLED, actor=request.user, details={"source": "sender_recall"})
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"success": True})
