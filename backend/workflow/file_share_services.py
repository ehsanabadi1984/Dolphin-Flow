"""Application services for internal file-share message lifecycle."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import FileShareDraft, FileShareMessage, FileShareMessageEvent


class FileShareMessageService:
    """Serialize and audit every supported message status transition."""

    ALLOWED_TRANSITIONS = {
        FileShareMessage.Status.PENDING: {
            FileShareMessage.Status.READ,
            FileShareMessage.Status.CANCELLED,
            FileShareMessage.Status.EXPIRED,
        },
        FileShareMessage.Status.READ: {
            FileShareMessage.Status.RESPONDED,
            FileShareMessage.Status.CANCELLED,
            FileShareMessage.Status.EXPIRED,
        },
        FileShareMessage.Status.RESPONDED: {
            FileShareMessage.Status.COMPLETED,
            FileShareMessage.Status.CANCELLED,
            FileShareMessage.Status.EXPIRED,
        },
        FileShareMessage.Status.COMPLETED: set(),
        FileShareMessage.Status.CANCELLED: set(),
        FileShareMessage.Status.EXPIRED: set(),
    }

    STATUS_METADATA = {
        FileShareMessage.Status.READ: (
            "read_at",
            FileShareMessageEvent.EventType.READ,
        ),
        FileShareMessage.Status.RESPONDED: (
            "responded_at",
            FileShareMessageEvent.EventType.RESPONDED,
        ),
        FileShareMessage.Status.COMPLETED: (
            "completed_at",
            FileShareMessageEvent.EventType.COMPLETED,
        ),
        FileShareMessage.Status.CANCELLED: (
            "cancelled_at",
            FileShareMessageEvent.EventType.CANCELLED,
        ),
        FileShareMessage.Status.EXPIRED: (
            None,
            FileShareMessageEvent.EventType.EXPIRED,
        ),
    }

    @classmethod
    @transaction.atomic
    def transition_status(
        cls,
        *,
        message,
        to_status,
        actor=None,
        details=None,
        at=None,
    ):
        """Transition one message, update its timestamp, and append an event."""
        message_id = message.pk if isinstance(message, FileShareMessage) else message
        if not message_id:
            raise ValidationError("پیام اشتراک‌گذاری معتبر نیست.")

        locked_message = (
            FileShareMessage.objects.select_for_update()
            .get(pk=message_id)
        )
        allowed = cls.ALLOWED_TRANSITIONS.get(locked_message.status)
        if allowed is None or to_status not in allowed:
            raise ValidationError(
                "تغییر وضعیت پیام اشتراک‌گذاری مجاز نیست."
            )

        event_at = at or timezone.now()
        timestamp_field, event_type = cls.STATUS_METADATA[to_status]
        locked_message.status = to_status
        update_fields = ["status", "updated_at"]
        if timestamp_field:
            setattr(locked_message, timestamp_field, event_at)
            update_fields.append(timestamp_field)

        locked_message.save(update_fields=update_fields)
        event = FileShareMessageEvent.objects.create(
            message=locked_message,
            event_type=event_type,
            actor=actor,
            details=details or {},
        )
        return locked_message, event


class FileShareDraftService:
    """Manage pre-submit share intents and atomically finalize them on Submit."""

    @staticmethod
    def available_recipients(*, instance, sender):
        from django.contrib.auth import get_user_model
        from .models import WorkflowMembership
        return get_user_model().objects.filter(
            workflow_memberships__workflow_id=instance.workflow_id,
            workflow_memberships__is_active=True,
            is_active=True,
        ).exclude(pk=sender.pk).distinct().order_by("username")

    @classmethod
    @transaction.atomic
    def create_drafts(cls, *, instance, step, sender, form_file, recipient_ids,
                      interaction_type=FileShareMessage.InteractionType.VIEW,
                      subject="", body=""):
        from .file_share_authorization import require_file_share_permission
        from .models import WorkflowInstance, WorkflowMembership
        from .permission_context import PermissionContext

        locked_instance = WorkflowInstance.objects.select_for_update().select_related(
            "workflow", "current_step"
        ).get(pk=instance.pk)
        if locked_instance.status != WorkflowInstance.Status.ACTIVE or locked_instance.current_step_id != step.pk:
            raise ValidationError("مرحله فعلی فرآیند تغییر کرده یا فعال نیست.")
        if not WorkflowMembership.objects.filter(
            workflow_id=locked_instance.workflow_id, user=sender, is_active=True
        ).exists():
            raise ValidationError("فرستنده عضو فعال این فرآیند نیست.")
        from .form_file_models import FormFile
        form_file = FormFile.objects.select_for_update().select_related(
            "field", "field__section", "field__section__form", "form_data"
        ).get(pk=form_file.pk)
        if form_file.form_data.instance_id != locked_instance.pk:
            raise ValidationError("فایل متعلق به این فرآیند نیست.")
        if form_file.field.section.form.workflow_id != locked_instance.workflow_id:
            raise ValidationError("فیلد فایل متعلق به این فرآیند نیست.")
        require_file_share_permission(user=sender, field=form_file.field)
        permission_context = PermissionContext.build(
            workflow=locked_instance.workflow,
            form=locked_instance.workflow.form_definition,
            step=step,
            user=sender,
        )
        if not permission_context.field(form_file.field).can_view:
            raise ValidationError("فرستنده اجازه مشاهده فایل مبدأ را ندارد.")
        if form_file.field.repeatable_group_id and not permission_context.group(form_file.field.repeatable_group).can_view:
            raise ValidationError("فرستنده اجازه مشاهده گروه حاوی فایل را ندارد.")
        if interaction_type not in FileShareMessage.InteractionType.values:
            raise ValidationError("نوع تعامل معتبر نیست.")
        ids = list(dict.fromkeys(int(value) for value in recipient_ids))
        if not ids:
            raise ValidationError("حداقل یک گیرنده انتخاب کنید.")
        if sender.pk in ids:
            raise ValidationError("فرستنده نمی‌تواند گیرنده پیام خودش باشد.")
        members = set(WorkflowMembership.objects.select_for_update().filter(
            workflow_id=locked_instance.workflow_id,
            user_id__in=ids,
            is_active=True,
            user__is_active=True,
        ).values_list("user_id", flat=True))
        if set(ids) != members:
            raise ValidationError("همه گیرندگان باید عضو فعال همین فرآیند باشند.")
        return [
            FileShareDraft.objects.create(
                sender=sender, recipient_id=rid, workflow_instance=locked_instance,
                workflow_step=step, form_file=form_file, interaction_type=interaction_type,
                subject=(subject or "")[:200], body=body or "",
            ) for rid in ids
        ]

    @classmethod
    @transaction.atomic
    def update_draft(cls, *, draft_id, sender, interaction_type=None, subject=None, body=None):
        from .models import WorkflowInstance

        draft_ref = FileShareDraft.objects.filter(
            pk=draft_id, sender=sender, status=FileShareDraft.Status.DRAFT
        ).values("workflow_instance_id").first()
        if draft_ref is None:
            raise ValidationError("پیش‌نویس قابل ویرایش پیدا نشد.")
        WorkflowInstance.objects.select_for_update().get(
            pk=draft_ref["workflow_instance_id"]
        )
        draft = FileShareDraft.objects.select_for_update().get(
            pk=draft_id, sender=sender, status=FileShareDraft.Status.DRAFT
        )
        if interaction_type is not None:
            if interaction_type not in FileShareMessage.InteractionType.values:
                raise ValidationError("نوع تعامل معتبر نیست.")
            draft.interaction_type = interaction_type
        if subject is not None:
            draft.subject = str(subject)[:200]
        if body is not None:
            draft.body = str(body)
        draft.save(update_fields=["interaction_type", "subject", "body", "updated_at"])
        return draft

    @staticmethod
    @transaction.atomic
    def delete_draft(*, draft_id, sender):
        draft = FileShareDraft.objects.select_for_update().filter(
            pk=draft_id, sender=sender, status=FileShareDraft.Status.DRAFT
        ).first()
        if draft is None:
            raise ValidationError("پیش‌نویس قابل حذف پیدا نشد.")
        draft.delete()
        return True

    @classmethod
    @transaction.atomic
    def finalize_for_submit(cls, *, instance, step, sender, transition_execution, form_snapshot):
        from django.utils import timezone
        from .form_file_models import FormFile
        from .file_lifecycle_services import FileLifecycleService
        from .models import FileShareDraft, FileShareMessage, FileShareMessageEvent, Notification
        from .notification_services import NotificationService

        from .models import WorkflowMembership
        from .file_share_authorization import require_file_share_permission
        from .permission_context import PermissionContext

        drafts = list(FileShareDraft.objects.select_for_update().filter(
            workflow_instance=instance, workflow_step=step, sender=sender,
            status=FileShareDraft.Status.DRAFT,
        ).order_by("pk"))
        if drafts and not WorkflowMembership.objects.filter(
            workflow_id=instance.workflow_id, user=sender, is_active=True
        ).exists():
            raise ValidationError("فرستنده دیگر عضو فعال فرآیند نیست.")
        created = []
        for draft in drafts:
            if not draft.form_file_id:
                continue
            form_file = FormFile.objects.select_for_update().select_related("field", "form_data").get(pk=draft.form_file_id)
            if form_file.form_data.instance_id != instance.pk:
                raise ValidationError("فایل پیش‌نویس دیگر متعلق به این فرآیند نیست.")
            if not WorkflowMembership.objects.filter(
                workflow_id=instance.workflow_id, user_id=draft.recipient_id,
                is_active=True, user__is_active=True,
            ).exists():
                raise ValidationError("گیرنده دیگر عضو فعال این فرآیند نیست.")
            require_file_share_permission(user=sender, field=form_file.field)
            permission_context = PermissionContext.build(
                workflow=instance.workflow, form=instance.workflow.form_definition,
                step=step, user=sender,
            )
            if not permission_context.field(form_file.field).can_view:
                raise ValidationError("فرستنده دیگر اجازه مشاهده فایل مبدأ را ندارد.")
            if form_file.field.repeatable_group_id and not permission_context.group(form_file.field.repeatable_group).can_view:
                raise ValidationError("فرستنده دیگر اجازه مشاهده گروه حاوی فایل را ندارد.")
            asset, _ = FileLifecycleService.get_or_create_asset(form_file)
            sent_at = timezone.now()
            snapshot = {
                "file": {
                    "field_id": form_file.field_id,
                    "field_code": form_file.field.code,
                    "field_label": form_file.field.label,
                    "row_id": form_file.row_id,
                    "original_name": form_file.original_name,
                    "file_size": form_file.file_size,
                    "content_type": form_file.content_type,
                },
            }
            message = FileShareMessage.objects.create(
                asset=asset, sender=sender, recipient=draft.recipient,
                workflow_instance=instance, workflow_step=step,
                transition_execution=transition_execution,
                interaction_type=draft.interaction_type,
                status=FileShareMessage.Status.PENDING,
                subject=draft.subject, body=draft.body, form_snapshot=snapshot,
            )
            FileShareMessageEvent.objects.create(
                message=message, event_type=FileShareMessageEvent.EventType.CREATED,
                actor=sender, details={"source": "submit"},
            )
            FileShareMessageEvent.objects.create(
                message=message, event_type=FileShareMessageEvent.EventType.SENT,
                actor=sender, details={"source": "submit"},
            )
            draft.form_file = None
            draft.file_share_message = message
            draft.status = FileShareDraft.Status.CONVERTED
            draft.converted_at = sent_at
            draft.save(update_fields=["form_file", "file_share_message", "status", "converted_at", "updated_at"])
            NotificationService.create(
                recipient=draft.recipient,
                notification_type=Notification.NotificationType.FILE_SHARE_MESSAGE,
                title="فایل جدیدی برای شما به اشتراک گذاشته شد",
                message=draft.subject or f"درخواستی از فرآیند «{instance.workflow.name}»",
                workflow_instance=instance, workflow_step=step,
                transition_execution=transition_execution,
                file_share_message=message,
            )
            created.append(message)
        return created
