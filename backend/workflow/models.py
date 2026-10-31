import re
import uuid
from django.conf import settings
from django.db import models, transaction
from django.core.exceptions import ValidationError


class Workflow(models.Model):
    name = models.CharField(
        max_length=150,
        unique=True,
    )

    code = models.CharField(
        max_length=50,
        unique=True,
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"WF_{uuid.uuid4().hex[:8].upper()}"

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class WorkflowMembership(models.Model):

    class Role(models.TextChoices):
        VIEWER = "VIEWER", "مشاهده‌کننده"
        EXECUTOR = "EXECUTOR", "مجری"
        MANAGER = "MANAGER", "مدیر"


    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.PROTECT,
        related_name="memberships",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workflow_memberships",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.EXECUTOR,
    )    

    is_active = models.BooleanField(
        default=True,
    )

    joined_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "user"],
                name="unique_workflow_membership",
            ),
        ]
        ordering = ["workflow", "user"]

    def __str__(self):
        return (
            f"{self.workflow.name} - "
            f"{self.user} - "
            f"{self.get_role_display()}"
        )
class WorkflowStep(models.Model):
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.PROTECT,
        related_name="steps",
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_workflow_steps",
    )

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
        editable=False,
    )

    description = models.TextField(
        blank=True,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["workflow", "order"]

        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "code"],
                name="unique_workflow_step_code",
            ),
            models.UniqueConstraint(
                fields=["workflow", "order"],
                name="unique_workflow_step_order",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"STEP_{uuid.uuid4().hex[:8].upper()}"

        super().save(*args, **kwargs)


    def __str__(self):
        return f"{self.workflow.name} - {self.name}"


class WorkflowInstance(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "پیش‌نویس"
        ACTIVE = "ACTIVE", "فعال"
        COMPLETED = "COMPLETED", "تکمیل شده"
        CANCELLED = "CANCELLED", "لغو شده"
        SUSPENDED = "SUSPENDED", "معلق"


    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.PROTECT,
        related_name="instances",
    )

    current_step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_instances",
    )


    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="started_workflow_instances",
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )    

    started_at = models.DateTimeField(
        auto_now_add=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )    

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return (
            f"{self.workflow.name} - "
            f"#{self.pk}"
        )


class DeviceType(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True,
    )

    code = models.CharField(
        max_length=50,
        unique=True,
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    
    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"TYPE_{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class DeviceModel(models.Model):
    device_type = models.ForeignKey(
        DeviceType,
        on_delete=models.PROTECT,
        related_name="models",
    )

    brand = models.CharField(
        max_length=100,
    )

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["brand", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["device_type", "code"],
                name="unique_device_model_code",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"MODEL_{uuid.uuid4().hex[:8].upper()}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.brand} {self.name}"

class Device(models.Model):
    device_model = models.ForeignKey(
        DeviceModel,
        on_delete=models.PROTECT,
        related_name="devices",
    )

    description = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.device_model}"

class DeviceIdentifier(models.Model):

    class IdentifierType(models.TextChoices):
        IMEI = "IMEI", "IMEI"
        SERIAL_NUMBER = "SERIAL_NUMBER", "شماره سریال"
        MAC_ADDRESS = "MAC_ADDRESS", "MAC Address"

    device = models.ForeignKey(
        Device,
        on_delete=models.PROTECT,
        related_name="identifiers",
    )

    identifier_type = models.CharField(
        max_length=30,
        choices=IdentifierType.choices,
    )

    value = models.CharField(
        max_length=150,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["identifier_type", "value"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "identifier_type",
                    "value",
                ],
                name="unique_device_identifier",
            ),
        ]

    def __str__(self):
        return f"{self.get_identifier_type_display()}: {self.value}"

class InstanceDevice(models.Model):
    class DeviceOrigin(models.TextChoices):
        EXISTING = "EXISTING", "دستگاه موجود"
        NEW = "NEW", "دستگاه جدید"

    instance = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.PROTECT,
        related_name="instance_devices",
    )

    device = models.ForeignKey(
        Device,
        on_delete=models.PROTECT,
        related_name="workflow_instances",
        null=True,
        blank=True,
    )

    device_origin = models.CharField(
        max_length=20,
        choices=DeviceOrigin.choices,
        null=True,
        blank=True,
    )

    draft_imei = models.CharField(
        max_length=150,
        blank=True,
    )

    draft_device_model = models.ForeignKey(
        DeviceModel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="draft_instance_devices",
    )

    draft_device_type = models.ForeignKey(
        DeviceType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="draft_instance_devices",
    )

    reported_problem = models.TextField(
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    warranty_status = models.CharField(
        max_length=30,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        blank=True,
    )
    is_active = models.BooleanField(
        default=True,
    )
    received_at = models.DateTimeField(
        auto_now_add=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-received_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["instance", "device"],
                name="unique_instance_device",
            ),
        ]

class WorkflowStepExecution(models.Model):
    instance = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.PROTECT,
        related_name="step_executions",
        null=True,
        blank=True,
    )

    workflow_step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        related_name="executions",
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workflow_step_executions",
    )

    performed_at = models.DateTimeField(
        auto_now_add=True,
    )

    notes = models.TextField(
        blank=True,
    )

    data = models.JSONField(
        default=dict,
        blank=True,
    )

    is_submitted = models.BooleanField(
        default=False,
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    sla_started_at = models.DateTimeField(
    null=True,
    blank=True,
    )

    sla_due_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    sla_warning_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    sla_warning_sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    sla_completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    sla_breached_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["performed_at"]

    def __str__(self):
        return (
            f"{self.workflow_step.workflow.name} - "
            f"{self.workflow_step.name} - "
            f"{self.performed_by}"
        )

class WorkflowTransition(models.Model):
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.PROTECT,
        related_name="transitions",
    )

    from_step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        related_name="outgoing_transitions",
    )

    to_step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        related_name="incoming_transitions",
        null=True,
        blank=True,
    )

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
        blank=True,
        editable=False,
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    requires_acceptance = models.BooleanField(
        default=False,
    )

    reject_to_step = models.ForeignKey(
        "WorkflowStep",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="acceptance_reject_target_transitions",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["workflow", "from_step", "to_step"]

        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "code"],
                name="unique_workflow_transition_code",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"TRANS_{uuid.uuid4().hex[:8].upper()}"

        super().save(*args, **kwargs)

    def __str__(self):
        if self.to_step:
            return (
                f"{self.workflow.name}: "
                f"{self.from_step.name} → {self.to_step.name}"
            )
        return (
            f"{self.workflow.name}: "
            f"{self.from_step.name} → [FINISH]"
        )

class WorkflowTransitionExecution(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "در انتظار تأیید"
        ACCEPTED = "ACCEPTED", "تأیید شده"
        REJECTED = "REJECTED", "رد شده"

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACCEPTED,
    )

    instance = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.PROTECT,
        related_name="transition_executions",
    )

    transition = models.ForeignKey(
        WorkflowTransition,
        on_delete=models.PROTECT,
        related_name="executions",
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workflow_transition_executions",
    )

    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accepted_workflow_transition_executions",
    )

    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rejected_workflow_transition_executions",
    )

    performed_at = models.DateTimeField(
        auto_now_add=True,
    )

    notes = models.TextField(
        blank=True,
    )

    data = models.JSONField(
        default=dict,
        blank=True,
    )

    class Meta:
        ordering = ["performed_at"]

    def __str__(self):
        return (
            f"{self.instance} - "
            f"{self.transition.name} - "
            f"{self.performed_by}"
        )

class WorkflowPermission(models.Model):
    class Action(models.TextChoices):
        VIEW = "VIEW", "مشاهده"
        EXECUTE = "EXECUTE", "اجرا"
        START = "START", "شروع فرآیند"
        TRANSITION = "TRANSITION", "تغییر مرحله"
        MANAGE = "MANAGE", "مدیریت"
        STEP_ACTION = "STEP_ACTION", "عملیات مرحله"

    class Effect(models.TextChoices):
        ALLOW = "ALLOW", "مجاز"
        DENY = "DENY", "ممنوع"

    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.PROTECT,
        related_name="permissions",
    )

    step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="permissions",
    )

    transition = models.ForeignKey(
        WorkflowTransition,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="permissions",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_permissions",
    )

    role = models.CharField(
        max_length=30,
        choices=WorkflowMembership.Role.choices,
        null=True,
        blank=True,
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
    )

    action_code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )

    effect = models.CharField(
        max_length=10,
        choices=Effect.choices,
        default=Effect.ALLOW,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["workflow", "action"]

        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        action="STEP_ACTION",
                        action_code__isnull=False,
                    )
                    | models.Q(
                        ~models.Q(action="STEP_ACTION"),
                        action_code__isnull=True,
                    )
                ),
                name="workflow_permission_step_action_code",
            ),
        ]

    def __str__(self):
        subject = self.user or self.role or "GLOBAL"

        target = (
            self.step
            or self.transition
            or self.workflow
        )

        return (
            f"{self.workflow.name} - "
            f"{subject} - "
            f"{target} - "
            f"{self.action} - "
            f"{self.effect}"
        )

class Notification(models.Model):

    class NotificationType(models.TextChoices):
        WORKFLOW_STARTED = (
            "WORKFLOW_STARTED",
            "شروع فرآیند",
        )
        STEP_ENTERED = (
            "STEP_ENTERED",
            "ورود به مرحله",
        )
        TRANSITION_EXECUTED = (
            "TRANSITION_EXECUTED",
            "تغییر مرحله",
        )
        ACTION_REQUIRED = (
            "ACTION_REQUIRED",
            "نیاز به اقدام",
        )
        WORKFLOW_COMPLETED = (
            "WORKFLOW_COMPLETED",
            "تکمیل فرآیند",
        )
        WORKFLOW_CANCELLED = (
            "WORKFLOW_CANCELLED",
            "لغو فرآیند",
        )
        SLA_WARNING = (
            "SLA_WARNING",
            "هشدار SLA",
        )
        SLA_BREACHED = (
            "SLA_BREACHED",
            "نقض SLA",
        )
        FILE_SHARE_MESSAGE = (
            "FILE_SHARE_MESSAGE",
            "پیام اشتراک‌گذاری فایل",
        )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notifications",
    )

    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
    )

    title = models.CharField(
        max_length=200,
    )

    message = models.TextField()

    workflow_instance = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notifications",
    )

    workflow_step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notifications",
    )

    transition_execution = models.ForeignKey(
        WorkflowTransitionExecution,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notifications",
    )

    file_share_message = models.ForeignKey(
        "workflow.FileShareMessage",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notifications",
    )

    is_read = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.recipient} - "
            f"{self.title}"
        )

class FileShareMessage(models.Model):
    class InteractionType(models.TextChoices):
        VIEW = "VIEW", "اشتراک‌گذاری برای مشاهده"
        RESPONSE = "RESPONSE", "درخواست پاسخ یا دریافت اطلاعات"
        ACTION = "ACTION", "درخواست انجام اقدام"
        REVIEW = "REVIEW", "درخواست بررسی یا تأیید فایل"

    class Status(models.TextChoices):
        PENDING = "PENDING", "در انتظار"
        READ = "READ", "مشاهده شده"
        RESPONDED = "RESPONDED", "پاسخ داده شده"
        COMPLETED = "COMPLETED", "تکمیل شده"
        CANCELLED = "CANCELLED", "لغو شده"
        EXPIRED = "EXPIRED", "منقضی شده"

    asset = models.ForeignKey("workflow.SharedFileAsset", on_delete=models.PROTECT, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_file_share_messages")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_file_share_messages")
    workflow_instance = models.ForeignKey(WorkflowInstance, on_delete=models.PROTECT, related_name="file_share_messages")
    workflow_step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT, null=True, blank=True, related_name="file_share_messages")
    transition_execution = models.ForeignKey(WorkflowTransitionExecution, on_delete=models.PROTECT, null=True, blank=True, related_name="file_share_messages")
    interaction_type = models.CharField(max_length=20, choices=InteractionType.choices, default=InteractionType.VIEW)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    subject = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(blank=True, default="")
    form_snapshot = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-sent_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["PENDING", "READ", "RESPONDED", "COMPLETED", "CANCELLED", "EXPIRED"]), name="fshare_msg_status_valid"),
            models.CheckConstraint(condition=(models.Q(status="CANCELLED", cancelled_at__isnull=False) | (~models.Q(status="CANCELLED") & models.Q(cancelled_at__isnull=True))), name="fshare_msg_cancel_date"),
            models.CheckConstraint(condition=(models.Q(completed_at__isnull=True) | models.Q(status="COMPLETED")), name="fshare_msg_complete_date"),
            models.CheckConstraint(condition=(models.Q(responded_at__isnull=True) | models.Q(status__in=["RESPONDED", "COMPLETED"])), name="fshare_msg_response_date"),
            models.CheckConstraint(condition=(models.Q(read_at__isnull=True) | ~models.Q(status="PENDING")), name="fshare_msg_read_date"),
            models.CheckConstraint(condition=(models.Q(read_at__isnull=True) | models.Q(read_at__gte=models.F("sent_at"))), name="fshare_msg_read_after_sent"),
            models.CheckConstraint(condition=(models.Q(responded_at__isnull=True) | models.Q(responded_at__gte=models.F("sent_at"))), name="fshare_msg_response_after_sent"),
            models.CheckConstraint(condition=(models.Q(completed_at__isnull=True) | models.Q(completed_at__gte=models.F("sent_at"))), name="fshare_msg_complete_after_sent"),
            models.CheckConstraint(condition=(models.Q(cancelled_at__isnull=True) | models.Q(cancelled_at__gte=models.F("sent_at"))), name="fshare_msg_cancel_after_sent"),
        ]

    def save(self, *args, **kwargs):
        from .form_file_models import SharedFileAsset
        from .file_lifecycle_services import (
            ACTIVE_SHARE_STATUSES,
            FileLifecycleService,
        )

        previous_status = None

        with transaction.atomic():
            # Serialize all lifecycle transitions for this message. Read the
            # previous status only after acquiring the row lock; otherwise two
            # concurrent saves can both make decisions from the same stale
            # status and schedule cleanup incorrectly.
            if self.pk:
                locked_message = (
                    type(self).objects.select_for_update()
                    .only("status", "asset_id")
                    .get(pk=self.pk)
                )
                previous_status = locked_message.status

            if self.asset_id:
                locked_asset = SharedFileAsset.objects.select_for_update().get(pk=self.asset_id)
                if (
                    self.status in ACTIVE_SHARE_STATUSES
                    and (
                        locked_asset.cleanup_pending
                        or locked_asset.storage_deleted_at is not None
                    )
                ):
                    raise ValidationError({
                        "asset": "فایل در حال پاک‌سازی است و امکان فعال‌کردن پیام آن وجود ندارد."
                    })

            # A terminal message must never become active again: its storage
            # dependency may already have been released and the file deleted.
            terminal_statuses = {
                self.Status.CANCELLED,
                self.Status.EXPIRED,
            }
            if (
                previous_status in terminal_statuses
                and self.status in ACTIVE_SHARE_STATUSES
            ):
                raise ValidationError({
                    "status": "پیام لغو یا منقضی‌شده قابل فعال‌سازی مجدد نیست."
                })

            super().save(*args, **kwargs)

            if (
                previous_status in ACTIVE_SHARE_STATUSES
                and self.status not in ACTIVE_SHARE_STATUSES
            ):
                FileLifecycleService.schedule_asset_cleanup(self.asset_id)

    def __str__(self):
        return f"{self.sender} → {self.recipient} - {self.get_interaction_type_display()}"


class FileShareMessageEvent(models.Model):
    class EventType(models.TextChoices):
        CREATED = "CREATED", "ایجاد"
        SENT = "SENT", "ارسال"
        READ = "READ", "مشاهده"
        RESPONDED = "RESPONDED", "پاسخ"
        COMPLETED = "COMPLETED", "تکمیل"
        CANCELLED = "CANCELLED", "لغو"
        EXPIRED = "EXPIRED", "انقضا"
        DOWNLOADED = "DOWNLOADED", "دریافت فایل"

    message = models.ForeignKey(FileShareMessage, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="file_share_message_events")
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["message", "created_at"], name="fshare_event_msg_date_idx")]

    def __str__(self):
        return f"{self.message_id} - {self.get_event_type_display()}"


class FileShareDraft(models.Model):
    """Sender-owned pre-submit intent; converted rows remain as audit history."""
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "پیش‌نویس"
        CONVERTED = "CONVERTED", "تبدیل‌شده به پیام"

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="file_share_drafts_sent")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="file_share_drafts_received")
    workflow_instance = models.ForeignKey(WorkflowInstance, on_delete=models.PROTECT, related_name="file_share_drafts")
    workflow_step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT, related_name="file_share_drafts")
    form_file = models.ForeignKey("workflow.FormFile", on_delete=models.CASCADE, null=True, blank=True, related_name="share_drafts")
    file_share_message = models.OneToOneField(FileShareMessage, on_delete=models.PROTECT, null=True, blank=True, related_name="source_draft")
    interaction_type = models.CharField(max_length=20, choices=FileShareMessage.InteractionType.choices, default=FileShareMessage.InteractionType.VIEW)
    subject = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    converted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(status="DRAFT", form_file__isnull=False, file_share_message__isnull=True, converted_at__isnull=True)
                    | models.Q(status="CONVERTED", form_file__isnull=True, file_share_message__isnull=False, converted_at__isnull=False)
                ),
                name="fshare_draft_state_consistent",
            ),
            models.CheckConstraint(
                condition=~models.Q(sender=models.F("recipient")),
                name="fshare_draft_sender_diff",
            ),
        ]

    def clean(self):
        super().clean()
        if self.sender_id and self.recipient_id and self.sender_id == self.recipient_id:
            raise ValidationError({"recipient": "فرستنده و گیرنده نمی‌توانند یک نفر باشند."})

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(
            pk=self.pk, status=self.Status.CONVERTED
        ).exists():
            raise ValidationError("پیش‌نویس تبدیل‌شده به پیام قابل ویرایش نیست.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(
            pk=self.pk, status=self.Status.CONVERTED
        ).exists():
            raise ValidationError("سابقه پیش‌نویس تبدیل‌شده قابل حذف نیست.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.sender} → {self.recipient} - {self.get_status_display()}"


class FormDefinition(models.Model):
    workflow = models.OneToOneField(
        Workflow,
        on_delete=models.PROTECT,
        related_name="form_definition",
    )

    name = models.CharField(
        max_length=150,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.name


class FormSection(models.Model):
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.PROTECT,
        related_name="sections",
    )

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
    )

    description = models.TextField(
        blank=True,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["form", "code"],
                name="unique_form_section_code",
            ),
            models.UniqueConstraint(
                fields=["form", "order"],
                name="unique_form_section_order",
            ),
        ]

    def __str__(self):
        return f"{self.form.name} - {self.name}"

class FormRepeatableGroup(models.Model):

    class GroupType(models.TextChoices):
        NORMAL = "NORMAL", "گروه معمولی"
        DEVICE = "DEVICE", "گروه دستگاه‌ها"

    class DisplayType(models.TextChoices):
        LIST = "LIST", "لیست"
        TABLE = "TABLE", "جدول"

    section = models.ForeignKey(
        FormSection,
        on_delete=models.PROTECT,
        related_name="repeatable_groups",
    )

    parent_group = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="child_groups",
    )

    name = models.CharField(
        max_length=150,
    )

    label = models.CharField(
        max_length=200,
        default="",
    )

    code = models.CharField(
        max_length=50,
    )

    group_type = models.CharField(
        max_length=20,
        choices=GroupType.choices,
        default=GroupType.NORMAL,
    )

    display_type = models.CharField(
        max_length=20,
        choices=DisplayType.choices,
        default=DisplayType.LIST,
    )

    description = models.TextField(
        blank=True,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    # Top-level display position of the group within its section.
    # Independent of ``order`` (group ordering) and used only for
    # the mixed field/group layout. NULL means "not explicitly
    # positioned yet"; the service sorts NULLs deterministically
    # to the end.
    layout_order = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    is_required = models.BooleanField(
        default=False,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["section", "code"],
                name="unique_repeatable_group_code",
            ),
            models.UniqueConstraint(
                fields=["section", "order"],
                name="unique_repeatable_group_order",
            ),
        ]

    def clean(self):
        super().clean()

        if not self.parent_group_id:
            return

        if self.parent_group_id == self.pk:
            raise ValidationError({"parent_group": "یک گروه نمی‌تواند والد خودش باشد."})

        parent = self.parent_group

        if parent.section_id != self.section_id:
            raise ValidationError({"parent_group": "گروه والد باید متعلق به همان Section باشد."})

        current = parent
        visited = set()

        while current is not None:
            if current.pk in visited:
                raise ValidationError({"parent_group": "زنجیره گروه‌های تکرارشونده دارای چرخه است."})
            visited.add(current.pk)
            if current.pk == self.pk:
                raise ValidationError({"parent_group": "انتخاب این گروه باعث ایجاد چرخه می‌شود."})
            current = current.parent_group

    def __str__(self):
        return (
            f"{self.section.name} - "
            f"{self.label or self.name}"
        )

class StaticChoiceSet(models.Model):

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
        unique=True,
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class StaticChoiceItem(models.Model):

    choice_set = models.ForeignKey(
        StaticChoiceSet,
        on_delete=models.PROTECT,
        related_name="items",
    )

    value = models.CharField(
        max_length=100,
    )

    label = models.CharField(
        max_length=200,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["order", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["choice_set", "value"],
                name="unique_static_choice_value",
            ),
        ]

    def __str__(self):
        return f"{self.choice_set.name} - {self.label}"


class LookupList(models.Model):

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
        unique=True,
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LookupItem(models.Model):

    lookup_list = models.ForeignKey(
        LookupList,
        on_delete=models.PROTECT,
        related_name="items",
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )

    value = models.CharField(
        max_length=100,
    )

    label = models.CharField(
        max_length=200,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["order", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["lookup_list", "value"],
                name="unique_lookup_item_value",
            ),
        ]

    def __str__(self):
        return self.label

class FormField(models.Model):

    class FieldType(models.TextChoices):
        TEXT = "TEXT", "متن"
        TEXTAREA = "TEXTAREA", "متن چندخطی"
        NUMBER = "NUMBER", "عدد"
        DATE = "DATE", "تاریخ"
        DATETIME = "DATETIME", "تاریخ و زمان"
        BOOLEAN = "BOOLEAN", "بله/خیر"
        SELECT = "SELECT", "انتخابی"
        FORMULA = "FORMULA", "فرمول"
        FILE = "FILE", "بارگذاری فایل"

    class Calendar(models.TextChoices):
        GREGORIAN = "GREGORIAN", "میلادی"
        JALALI = "JALALI", "شمسی"

    class SystemKey(models.TextChoices):
        NONE = "NONE", "بدون اتصال سیستمی"

        DEVICE_TYPE = "DEVICE_TYPE", "نوع دستگاه"
        DEVICE_MODEL = "DEVICE_MODEL", "مدل دستگاه"
        IMEI = "IMEI", "IMEI"
        REPORTED_PROBLEM = "REPORTED_PROBLEM", "شرح مشکل"
        DESCRIPTION = "DESCRIPTION", "توضیحات تکمیلی"
        WARRANTY_STATUS = "WARRANTY_STATUS", "وضعیت گارانتی"
        STATUS = "STATUS", "وضعیت دستگاه"

    class ChoiceSource(models.TextChoices):
        NONE = "NONE", "بدون منبع"
        STATIC = "STATIC", "گزینه‌های ثابت"
        LOOKUP = "LOOKUP", "لیست داده‌ای"
        MODEL = "MODEL", "مدل سیستم"

    section = models.ForeignKey(
        FormSection,
        on_delete=models.PROTECT,
        related_name="fields",
    )

    repeatable_group = models.ForeignKey(
        FormRepeatableGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fields",
    )

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
    )

    field_type = models.CharField(
        max_length=20,
        choices=FieldType.choices,
        default=FieldType.TEXT,
    )

    calendar = models.CharField(
        max_length=10,
        choices=Calendar.choices,
        default=Calendar.GREGORIAN,
    )

    choice_source = models.CharField(
        max_length=20,
        choices=ChoiceSource.choices,
        default=ChoiceSource.NONE,
    )

    choice_model = models.ForeignKey(
        "contenttypes.ContentType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="form_fields",
    )

    choice_static_set = models.ForeignKey(
        "StaticChoiceSet",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="form_fields",
    )

    choice_lookup_list = models.ForeignKey(
        "LookupList",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="form_fields",
    )

    choice_label_field = models.CharField(
        max_length=100,
        blank=True,
    )

    choice_value_field = models.CharField(
        max_length=100,
        blank=True,
    )

    choice_parent_field = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dependent_choice_fields",
    )

    choice_filter_field = models.CharField(
        max_length=100,
        blank=True,
    )

    label = models.CharField(
        max_length=200,
    )

    help_text = models.TextField(
        blank=True,
    )

    default_value = models.TextField(
        blank=True,
        default="",
        verbose_name="متن پیش‌فرض",
    )

    is_required = models.BooleanField(
        default=False,
    )

    allow_file_sharing = models.BooleanField(
        default=False,
        verbose_name="اجازه اشتراک‌گذاری فایل",
        help_text="فقط برای فیلدهای بارگذاری فایل قابل استفاده است.",
    )

    show_in_process_summary = models.BooleanField(
        default=False,
    )

    # Number fields store up to six decimal places, while each form field
    # controls how many decimal places are presented/accepted in the UI.
    # Two places is the default so ordinary numeric fields do not render
    # artificial trailing zeros.
    decimal_places = models.PositiveSmallIntegerField(
        default=2,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    # Top-level display position of the field within its section.
    # Independent of ``order`` (field ordering / repeatable-group
    # ordering) and used only for the mixed field/group layout.
    # NULL means "not explicitly positioned yet"; the service sorts
    # NULLs deterministically to the end.
    layout_order = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    choices = models.JSONField(
        default=list,
        blank=True,
    )

    system_key = models.CharField(
        max_length=30,
        choices=SystemKey.choices,
        default=SystemKey.NONE,
    )

    @property
    def number_step(self):
        if self.field_type != self.FieldType.NUMBER:
            return None
        return 1 / (10 ** self.decimal_places)

    def clean(self):
        super().clean()

        # File sharing is meaningful only for uploaded-file fields.
        if self.field_type != self.FieldType.FILE:
            self.allow_file_sharing = False

        # --------------------------------------------------
        # General Validation
        # --------------------------------------------------

        if self.repeatable_group:
            if self.repeatable_group.section_id != self.section_id:
                raise ValidationError(
                    "گروه تکرارشونده باید متعلق به همان Section فیلد باشد."
                )

        # --------------------------------------------------
        # Number Precision Validation
        # --------------------------------------------------

        if self.field_type == self.FieldType.NUMBER:
            if not 0 <= self.decimal_places <= 6:
                raise ValidationError({
                    "decimal_places": (
                        "تعداد ارقام اعشار باید بین ۰ تا ۶ باشد."
                    )
                })
        elif self.decimal_places != 2:
            self.decimal_places = 2

        # --------------------------------------------------
        # Choice Source Validation
        # --------------------------------------------------

        # NONE
        if self.choice_source == self.ChoiceSource.NONE:

            if self.choice_model_id:
                raise ValidationError(
                    {
                        "choice_model": (
                            "وقتی منبع گزینه‌ها «بدون منبع» است، "
                            "مدل سیستم نباید مشخص شود."
                        )
                    }
                )

            if self.choice_static_set_id:
                raise ValidationError(
                    {
                        "choice_static_set": (
                            "وقتی منبع گزینه‌ها «بدون منبع» است، "
                            "مجموعه گزینه‌های ثابت نباید مشخص شود."
                        )
                    }
                )

            if self.choice_lookup_list_id:
                raise ValidationError(
                    {
                        "choice_lookup_list": (
                            "وقتی منبع گزینه‌ها «بدون منبع» است، "
                            "لیست داده‌ای نباید مشخص شود."
                        )
                    }
                )

            if self.choice_label_field:
                raise ValidationError(
                    {
                        "choice_label_field": (
                            "فیلد نمایش فقط برای منبع «مدل سیستم» "
                            "قابل استفاده است."
                        )
                    }
                )

            if self.choice_value_field:
                raise ValidationError(
                    {
                        "choice_value_field": (
                            "فیلد مقدار فقط برای منبع «مدل سیستم» "
                            "قابل استفاده است."
                        )
                    }
                )

        # --------------------------------------------------
        # STATIC
        # --------------------------------------------------

        elif self.choice_source == self.ChoiceSource.STATIC:

            if not self.choice_static_set_id:
                raise ValidationError(
                    {
                        "choice_static_set": (
                            "برای منبع «گزینه‌های ثابت» "
                            "باید یک مجموعه گزینه انتخاب شود."
                        )
                    }
                )

            if self.choice_model_id:
                raise ValidationError(
                    {
                        "choice_model": (
                            "مدل سیستم فقط برای منبع "
                            "«مدل سیستم» قابل استفاده است."
                        )
                    }
                )

            if self.choice_lookup_list_id:
                raise ValidationError(
                    {
                        "choice_lookup_list": (
                            "لیست داده‌ای فقط برای منبع "
                            "«لیست داده‌ای» قابل استفاده است."
                        )
                    }
                )

            if self.choice_label_field:
                raise ValidationError(
                    {
                        "choice_label_field": (
                            "فیلد نمایش فقط برای منبع "
                            "«مدل سیستم» قابل استفاده است."
                        )
                    }
                )

            if self.choice_value_field:
                raise ValidationError(
                    {
                        "choice_value_field": (
                            "فیلد مقدار فقط برای منبع "
                            "«مدل سیستم» قابل استفاده است."
                        )
                    }
                )

            if self.choice_parent_field_id:
                raise ValidationError(
                    {
                        "choice_parent_field": (
                            "وابستگی والد/فرزند فعلاً برای "
                            "گزینه‌های ثابت پشتیبانی نمی‌شود."
                        )
                    }
                )

        # --------------------------------------------------
        # LOOKUP
        # --------------------------------------------------

        elif self.choice_source == self.ChoiceSource.LOOKUP:

            if not self.choice_lookup_list_id:
                raise ValidationError(
                    {
                        "choice_lookup_list": (
                            "برای منبع «لیست داده‌ای» "
                            "باید یک لیست داده‌ای انتخاب شود."
                        )
                    }
                )

            if self.choice_model_id:
                raise ValidationError(
                    {
                        "choice_model": (
                            "مدل سیستم فقط برای منبع "
                            "«مدل سیستم» قابل استفاده است."
                        )
                    }
                )

            if self.choice_static_set_id:
                raise ValidationError(
                    {
                        "choice_static_set": (
                            "مجموعه گزینه‌های ثابت فقط برای منبع "
                            "«گزینه‌های ثابت» قابل استفاده است."
                        )
                    }
                )

            if self.choice_label_field:
                raise ValidationError(
                    {
                        "choice_label_field": (
                            "فیلد نمایش فقط برای منبع "
                            "«مدل سیستم» قابل استفاده است."
                        )
                    }
                )

            if self.choice_value_field:
                raise ValidationError(
                    {
                        "choice_value_field": (
                            "فیلد مقدار فقط برای منبع "
                            "«مدل سیستم» قابل استفاده است."
                        )
                    }
                )

        # --------------------------------------------------
        # MODEL
        # --------------------------------------------------

        elif self.choice_source == self.ChoiceSource.MODEL:

            if not self.choice_model_id:
                raise ValidationError(
                    {
                        "choice_model": (
                            "برای منبع «مدل سیستم» "
                            "باید یک مدل انتخاب شود."
                        )
                    }
                )

            if not self.choice_label_field:
                raise ValidationError(
                    {
                        "choice_label_field": (
                            "فیلد نمایش برای منبع «مدل سیستم» "
                            "الزامی است."
                        )
                    }
                )

            if not self.choice_value_field:
                raise ValidationError(
                    {
                        "choice_value_field": (
                            "فیلد مقدار برای منبع «مدل سیستم» "
                            "الزامی است."
                        )
                    }
                )

            if self.choice_static_set_id:
                raise ValidationError(
                    {
                        "choice_static_set": (
                            "مجموعه گزینه‌های ثابت فقط برای منبع "
                            "«گزینه‌های ثابت» قابل استفاده است."
                        )
                    }
                )

            if self.choice_lookup_list_id:
                raise ValidationError(
                    {
                        "choice_lookup_list": (
                            "لیست داده‌ای فقط برای منبع "
                            "«لیست داده‌ای» قابل استفاده است."
                        )
                    }
                )

            model_class = self.choice_model.model_class()

            if not model_class:
                raise ValidationError(
                    {
                        "choice_model": (
                            "مدل انتخاب‌شده معتبر نیست."
                        )
                    }
                )

            available_fields = {
                field.name
                for field in model_class._meta.get_fields()
                if getattr(field, "concrete", False)
                and not getattr(field, "auto_created", False)
            }

            available_value_fields = available_fields | {"id"}

            if self.choice_label_field not in available_fields:
                raise ValidationError(
                    {
                        "choice_label_field": (
                            "فیلد نمایش انتخاب‌شده "
                            "در مدل وجود ندارد."
                        )
                    }
                )

            if self.choice_value_field not in available_value_fields:
                raise ValidationError(
                    {
                        "choice_value_field": (
                            "فیلد مقدار انتخاب‌شده "
                            "در مدل وجود ندارد."
                        )
                    }
                )

        # --------------------------------------------------
        # Parent / Dependency Validation
        # --------------------------------------------------

        if self.choice_parent_field_id:

            # یک فیلد نمی‌تواند والد خودش باشد.
            if self.choice_parent_field_id == self.pk:
                raise ValidationError(
                    {
                        "choice_parent_field": (
                            "یک فیلد نمی‌تواند والد خودش باشد."
                        )
                    }
                )

            parent = self.choice_parent_field

            # Parent باید متعلق به همان Form باشد.
            if parent.section.form_id != self.section.form_id:
                raise ValidationError(
                    {
                        "choice_parent_field": (
                            "فیلد والد باید متعلق به همان Form باشد."
                        )
                    }
                )

            # Parent باید SELECT باشد.
            if parent.field_type != self.FieldType.SELECT:
                raise ValidationError(
                    {
                        "choice_parent_field": (
                            "فیلد والد باید از نوع «انتخابی» باشد."
                        )
                    }
                )

            # --------------------------------------------------
            # MODEL → MODEL
            # --------------------------------------------------

            if self.choice_source == self.ChoiceSource.MODEL:

                if parent.choice_source != self.ChoiceSource.MODEL:
                    raise ValidationError(
                        {
                            "choice_parent_field": (
                                "فیلد والد برای وابستگی مدل باید "
                                "نیز از منبع «مدل سیستم» باشد."
                            )
                        }
                    )

                if not self.choice_filter_field:
                    raise ValidationError(
                        {
                            "choice_filter_field": (
                                "برای یک فیلد وابسته، "
                                "فیلد ارتباط با والد باید مشخص شود."
                            )
                        }
                    )

                if not self.choice_model_id:
                    raise ValidationError(
                        {
                            "choice_model": (
                                "برای بررسی وابستگی، "
                                "مدل گزینه‌ها باید مشخص باشد."
                            )
                        }
                    )

                model_class = self.choice_model.model_class()

                if not model_class:
                    raise ValidationError(
                        {
                            "choice_model": (
                                "مدل گزینه‌های انتخابی معتبر نیست."
                            )
                        }
                    )

                available_fields = {
                    field.name
                    for field in model_class._meta.get_fields()
                    if getattr(field, "concrete", False)
                    and not getattr(field, "auto_created", False)
                }

                if self.choice_filter_field not in available_fields:
                    raise ValidationError(
                        {
                            "choice_filter_field": (
                                "فیلد ارتباط با والد "
                                "در مدل گزینه‌ها وجود ندارد."
                            )
                        }
                    )

            # --------------------------------------------------
            # LOOKUP → LOOKUP
            # --------------------------------------------------

            elif self.choice_source == self.ChoiceSource.LOOKUP:

                if parent.choice_source != self.ChoiceSource.LOOKUP:
                    raise ValidationError(
                        {
                            "choice_parent_field": (
                                "فیلد والد برای وابستگی لیست داده‌ای "
                                "باید نیز از منبع «لیست داده‌ای» باشد."
                            )
                        }
                    )

                if (
                    parent.choice_lookup_list_id
                    != self.choice_lookup_list_id
                ):
                    raise ValidationError(
                        {
                            "choice_parent_field": (
                                "فیلد والد و فیلد فرزند باید "
                                "از یک لیست داده‌ای استفاده کنند."
                            )
                        }
                    )

            # STATIC و NONE نباید Parent داشته باشند.
            else:

                raise ValidationError(
                    {
                        "choice_parent_field": (
                            "وابستگی والد/فرزند فقط برای "
                            "منابع «مدل سیستم» و «لیست داده‌ای» "
                            "قابل استفاده است."
                        )
                    }
                )

            # --------------------------------------------------
            # Cycle Detection
            # --------------------------------------------------

            current = parent
            visited = set()

            while current:

                if current.pk in visited:
                    raise ValidationError(
                        {
                            "choice_parent_field": (
                                "زنجیره فیلدهای وابسته دارای چرخه است."
                            )
                        }
                    )

                visited.add(current.pk)

                if current.pk == self.pk:
                    raise ValidationError(
                        {
                            "choice_parent_field": (
                                "انتخاب این فیلد باعث ایجاد "
                                "چرخه در وابستگی می‌شود."
                            )
                        }
                    )

                current = current.choice_parent_field

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["section", "code"],
                name="unique_form_field_code",
            ),
            models.UniqueConstraint(
                fields=["section", "order"],
                condition=models.Q(
                    repeatable_group__isnull=True,
                ),
                name="unique_form_field_order",
            ),
            models.UniqueConstraint(
                fields=["repeatable_group", "order"],
                condition=models.Q(
                    repeatable_group__isnull=False,
                ),
                name="unique_repeatable_field_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(field_type="FILE")
                    | models.Q(allow_file_sharing=False)
                ),
                name="formfield_share_only_file",
            ),
        ]

    def __str__(self):
        return f"{self.section.name} - {self.label}"


class RepeatableRow(models.Model):

    instance = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.PROTECT,
        related_name="repeatable_rows",
    )

    group = models.ForeignKey(
        FormRepeatableGroup,
        on_delete=models.PROTECT,
        related_name="rows",
    )

    parent_row = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="child_rows",
    )

    row_order = models.PositiveIntegerField(default=0)

    instance_device = models.OneToOneField(
        InstanceDevice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="repeatable_row",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if self.group_id and self.instance_id:
            if self.group.section.form.workflow_id != self.instance.workflow_id:
                raise ValidationError(
                    "گروه تکرارشونده و WorkflowInstance باید متعلق به یک Workflow باشند."
                )

        if self.parent_row_id:
            if self.parent_row_id == self.pk:
                raise ValidationError({"parent_row": "یک Row نمی‌تواند والد خودش باشد."})

            parent = self.parent_row
            if parent.instance_id != self.instance_id:
                raise ValidationError({"parent_row": "Row والد باید متعلق به همان WorkflowInstance باشد."})

            if not self.group.parent_group_id:
                raise ValidationError({"parent_row": "این گروه parent_group ندارد و نمی‌تواند زیر یک Row دیگر قرار بگیرد."})

            if parent.group_id != self.group.parent_group_id:
                raise ValidationError({"parent_row": "Row والد باید متعلق به parent_group همین گروه باشد."})

            current = parent
            visited = set()
            while current is not None:
                if current.pk in visited:
                    raise ValidationError({"parent_row": "زنجیره Rowهای والد دارای چرخه است."})
                visited.add(current.pk)
                if current.pk == self.pk:
                    raise ValidationError({"parent_row": "انتخاب این Row باعث ایجاد چرخه می‌شود."})
                current = current.parent_row

        if self.instance_device_id:
            if self.group.group_type != FormRepeatableGroup.GroupType.DEVICE:
                raise ValidationError({"instance_device": "InstanceDevice فقط می‌تواند به Row گروه DEVICE متصل شود."})
            if self.instance_device.instance_id != self.instance_id:
                raise ValidationError({"instance_device": "InstanceDevice باید متعلق به همان WorkflowInstance باشد."})

    class Meta:
        ordering = ["group", "row_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "group", "row_order"],
                condition=models.Q(parent_row__isnull=True),
                name="unique_repeatable_root_row_order",
            ),
            models.UniqueConstraint(
                fields=["instance", "group", "parent_row", "row_order"],
                condition=models.Q(parent_row__isnull=False),
                name="unique_repeatable_child_row_order",
            ),
        ]

    def __str__(self):
        return f"{self.group.name} - Row #{self.pk or 'new'}"


class RepeatableRowValue(models.Model):

    row = models.ForeignKey(
        RepeatableRow,
        on_delete=models.PROTECT,
        related_name="values",
    )

    field = models.ForeignKey(
        FormField,
        on_delete=models.PROTECT,
        related_name="repeatable_row_values",
    )

    text_value = models.TextField(null=True, blank=True)
    decimal_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    date_value = models.DateField(null=True, blank=True)
    datetime_value = models.DateTimeField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)

    static_choice_item = models.ForeignKey(
        StaticChoiceItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="repeatable_row_values",
    )

    lookup_item = models.ForeignKey(
        LookupItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="repeatable_row_values",
    )

    reference_id = models.CharField(max_length=150, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if not self.row_id or not self.field_id:
            return

        if self.field.repeatable_group_id != self.row.group_id:
            raise ValidationError({"field": "فیلد باید متعلق به همان RepeatableGroup ردیف باشد."})

        if self.field.system_key != FormField.SystemKey.NONE:
            raise ValidationError({"field": "فیلدهای سیستمی نباید به‌صورت RepeatableRowValue ذخیره شوند."})

        value_fields = {
            "text_value": self.text_value,
            "decimal_value": self.decimal_value,
            "date_value": self.date_value,
            "datetime_value": self.datetime_value,
            "boolean_value": self.boolean_value,
            "static_choice_item": self.static_choice_item_id,
            "lookup_item": self.lookup_item_id,
            "reference_id": self.reference_id,
        }

        if self.field.field_type in (FormField.FieldType.TEXT, FormField.FieldType.TEXTAREA):
            expected = ["text_value"]
        elif self.field.field_type == FormField.FieldType.NUMBER:
            expected = ["decimal_value"]
        elif self.field.field_type == FormField.FieldType.DATE:
            expected = ["date_value"]
        elif self.field.field_type == FormField.FieldType.DATETIME:
            expected = ["datetime_value"]
        elif self.field.field_type == FormField.FieldType.BOOLEAN:
            expected = ["boolean_value"]
        elif self.field.field_type == FormField.FieldType.SELECT:
            if self.field.choice_source == FormField.ChoiceSource.STATIC:
                expected = ["static_choice_item"]
                if self.static_choice_item_id and self.static_choice_item.choice_set_id != self.field.choice_static_set_id:
                    raise ValidationError({"static_choice_item": "گزینه انتخاب‌شده متعلق به مجموعه گزینه این فیلد نیست."})
            elif self.field.choice_source == FormField.ChoiceSource.LOOKUP:
                expected = ["lookup_item"]
                if self.lookup_item_id and self.lookup_item.lookup_list_id != self.field.choice_lookup_list_id:
                    raise ValidationError({"lookup_item": "گزینه انتخاب‌شده متعلق به لیست داده‌ای این فیلد نیست."})
            elif self.field.choice_source == FormField.ChoiceSource.MODEL:
                expected = ["reference_id"]

                if not self.field.choice_model_id:
                    raise ValidationError({"field": "برای SELECT با منبع MODEL باید مدل انتخاب شود."})
                if not self.field.choice_value_field:
                    raise ValidationError({"field": "برای SELECT با منبع MODEL باید فیلد مقدار مشخص شود."})

                model_class = self.field.choice_model.model_class()
                if model_class is None:
                    raise ValidationError({"field": "مدل انتخاب‌شده برای SELECT معتبر نیست."})

                try:
                    model_field = model_class._meta.get_field(
                        self.field.choice_value_field
                    )
                except Exception:
                    raise ValidationError({
                        "reference_id": "فیلد مقدار انتخاب‌شده برای مدل معتبر نیست."
                    })

                if not getattr(model_field, "concrete", False):
                    raise ValidationError({
                        "reference_id": "فیلد مقدار انتخاب‌شده باید یک فیلد concrete باشد."
                    })

                if not model_class.objects.filter(
                    **{self.field.choice_value_field: self.reference_id}
                ).exists():
                    raise ValidationError({
                        "reference_id": "مقدار انتخاب‌شده در مدل مقصد وجود ندارد."
                    })
            else:
                raise ValidationError({"field": "فیلد SELECT باید منبع گزینه معتبر داشته باشد."})
        else:
            raise ValidationError({"field": "این نوع FormField هنوز برای RepeatableRowValue پشتیبانی نمی‌شود."})

        for name, value in value_fields.items():
            if name in expected:
                if value is None:
                    raise ValidationError({name: "مقدار این فیلد باید مشخص شود."})
            elif value is not None:
                raise ValidationError({name: "برای این نوع FormField نباید مقدار ذخیره شود."})

    class Meta:
        ordering = ["field__order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["row", "field"],
                name="unique_repeatable_row_field_value",
            ),
        ]

    def __str__(self):
        return f"{self.row} - {self.field.label}"


class FieldAccess(models.Model):
    field = models.ForeignKey(
        FormField,
        on_delete=models.PROTECT,
        related_name="access_rules",
    )

    step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="field_access_rules",
    )

    role = models.CharField(
        max_length=20,
        choices=WorkflowMembership.Role.choices,
        null=True,
        blank=True,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="field_access_rules",
    )

    can_view = models.BooleanField(
        default=True,
    )

    can_edit = models.BooleanField(
        default=False,
    )

    def clean(self):
        super().clean()

        if self.can_edit and not self.can_view:
            raise ValidationError(
                "برای ویرایش فیلد، دسترسی مشاهده نیز باید فعال باشد."
            )

        if not self.field_id or not self.step_id:
            return

        field_workflow_id = (
            self.field.section.form.workflow_id
        )

        if self.step.workflow_id != field_workflow_id:
            raise ValidationError(
                "مرحله انتخاب‌ شده باید متعلق به فرآیند همین فرم باشد."
            )

    class Meta:
        ordering = ["field"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(can_edit=False) | models.Q(can_view=True),
                name="field_access_edit_requires_view",
            ),
        ]

    def __str__(self):
        subject = self.user or self.role or "GLOBAL"
        return f"{self.field} - {subject}"


class RepeatableGroupAccess(models.Model):
    group = models.ForeignKey(
        FormRepeatableGroup,
        on_delete=models.PROTECT,
        related_name="access_rules",
    )

    step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="repeatable_group_access_rules",
    )

    role = models.CharField(
        max_length=20,
        choices=WorkflowMembership.Role.choices,
        null=True,
        blank=True,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="repeatable_group_access_rules",
    )

    can_view = models.BooleanField(
        default=True,
    )

    can_edit = models.BooleanField(
        default=False,
    )

    can_add = models.BooleanField(
        default=False,
    )

    can_delete = models.BooleanField(
        default=False,
    )

    def clean(self):
        super().clean()

        if self.can_edit and not self.can_view:
            raise ValidationError(
                "برای ویرایش گروه، دسترسی مشاهده نیز باید فعال باشد."
            )

        if not self.group_id or not self.step_id:
            return

        group_workflow_id = (
            self.group.section.form.workflow_id
        )

        if self.step.workflow_id != group_workflow_id:
            raise ValidationError(
                "مرحله انتخاب‌شده باید متعلق به فرآیند همین فرم باشد."
            )

    class Meta:
        ordering = ["group"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(can_edit=False) | models.Q(can_view=True),
                name="repeatable_group_access_edit_requires_view",
            ),
        ]

    def __str__(self):
        subject = self.user or self.role or "GLOBAL"
        return f"{self.group} - {subject}"

class FormData(models.Model):
    instance = models.OneToOneField(
        WorkflowInstance,
        on_delete=models.PROTECT,
        related_name="form_data",
    )

    data = models.JSONField(
        default=dict,
        blank=True,
    )

    is_submitted = models.BooleanField(
        default=False,
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_form_data",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"Form data - {self.instance}"

class BusinessCalendar(models.Model):
    name = models.CharField(
        max_length=150,
        unique=True,
    )

    timezone = models.CharField(
        max_length=64,
        default="Asia/Tehran",
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.name

class WeeklySchedule(models.Model):

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    calendar = models.ForeignKey(
        BusinessCalendar,
        on_delete=models.PROTECT,
        related_name="weekly_schedules",
    )

    weekday = models.PositiveSmallIntegerField(
        choices=Weekday.choices,
    )

    is_working = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["weekday"]

        constraints = [
            models.UniqueConstraint(
                fields=["calendar", "weekday"],
                name="unique_calendar_weekday",
            ),
        ]

    def __str__(self):
        return f"{self.calendar.name} - {self.get_weekday_display()}"

class WorkingInterval(models.Model):
    weekly_schedule = models.ForeignKey(
        WeeklySchedule,
        on_delete=models.CASCADE,
        related_name="intervals",
    )

    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["start_time"]

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError(
                "زمان شروع باید قبل از زمان پایان باشد."
            )

        overlapping = WorkingInterval.objects.filter(
            weekly_schedule=self.weekly_schedule,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        )

        if self.pk:
            overlapping = overlapping.exclude(pk=self.pk)

        if overlapping.exists():
            raise ValidationError(
                "بازه زمانی با یک بازه دیگر هم‌پوشانی دارد."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.start_time} - {self.end_time}"

class CalendarException(models.Model):

    class Status(models.TextChoices):
        WORKING = "WORKING", "Working"
        NON_WORKING = "NON_WORKING", "Non-working"

    calendar = models.ForeignKey(
        BusinessCalendar,
        on_delete=models.PROTECT,
        related_name="exceptions",
    )

    date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
    )

    title = models.CharField(
        max_length=150,
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = ["date"]

        constraints = [
            models.UniqueConstraint(
                fields=["calendar", "date"],
                name="unique_calendar_exception_date",
            ),
        ]

    def __str__(self):
        return (
            f"{self.calendar.name} - "
            f"{self.date} - "
            f"{self.status}"
        )

class CalendarExceptionInterval(models.Model):
    exception = models.ForeignKey(
        "CalendarException",
        on_delete=models.CASCADE,
        related_name="intervals",
    )

    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["start_time"]

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError(
                "زمان شروع باید قبل از زمان پایان باشد."
            )

        if not self.exception_id:
            return

        if self.exception.status != CalendarException.Status.WORKING:
            raise ValidationError(
                "برای یک Exception غیرکاری نمی‌توان بازه زمانی تعریف کرد."
            )

        overlapping = CalendarExceptionInterval.objects.filter(
            exception=self.exception,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        )

        if self.pk:
            overlapping = overlapping.exclude(pk=self.pk)

        if overlapping.exists():
            raise ValidationError(
                "بازه زمانی با یک بازه دیگر هم‌پوشانی دارد."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.start_time} - {self.end_time}"

class WorkflowStepSLA(models.Model):
    step = models.OneToOneField(
        WorkflowStep,
        on_delete=models.PROTECT,
        related_name="sla",
    )

    calendar = models.ForeignKey(
        BusinessCalendar,
        on_delete=models.PROTECT,
        related_name="step_slas",
    )

    duration = models.DurationField()

    warning_before = models.DurationField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )


class FormPrintSettings(models.Model):
    """Document-level print settings, kept separate from the form definition."""

    class PageSize(models.TextChoices):
        A4 = "A4", "A4"
        A5 = "A5", "A5"

    class Orientation(models.TextChoices):
        PORTRAIT = "PORTRAIT", "عمودی"
        LANDSCAPE = "LANDSCAPE", "افقی"

    form = models.OneToOneField(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="print_settings",
        verbose_name="فرم",
    )
    document_title = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="عنوان سند چاپی",
    )
    subtitle = models.CharField(
        max_length=250,
        blank=True,
        default="",
        verbose_name="زیرعنوان سند",
    )
    header_text = models.TextField(
        blank=True,
        default="",
        verbose_name="متن سربرگ",
    )
    footer_text = models.TextField(
        blank=True,
        default="",
        verbose_name="متن پابرگ",
    )
    page_size = models.CharField(
        max_length=2,
        choices=PageSize.choices,
        default=PageSize.A4,
        verbose_name="اندازه کاغذ",
    )
    orientation = models.CharField(
        max_length=10,
        choices=Orientation.choices,
        default=Orientation.PORTRAIT,
        verbose_name="جهت صفحه",
    )
    show_workflow_name = models.BooleanField(
        default=True,
        verbose_name="نمایش نام فرایند",
    )
    show_instance_number = models.BooleanField(
        default=True,
        verbose_name="نمایش شماره فرایند",
    )
    show_created_at = models.BooleanField(
        default=True,
        verbose_name="نمایش تاریخ ایجاد",
    )
    show_empty_values = models.BooleanField(
        default=False,
        verbose_name="نمایش فیلدهای خالی",
    )
    show_signatures = models.BooleanField(
        default=False,
        verbose_name="نمایش محل امضا",
    )
    signature_count = models.PositiveSmallIntegerField(
        default=2,
        verbose_name="تعداد محل امضا",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="آخرین ویرایش",
    )

    class Meta:
        verbose_name = "تنظیمات چاپ فرم"
        verbose_name_plural = "تنظیمات چاپ فرم"

    def __str__(self):
        return f"تنظیمات چاپ - {self.form}"


class FormPrintSectionSettings(models.Model):
    """Print visibility, title and ordering for an individual form section."""

    section = models.OneToOneField(
        FormSection,
        on_delete=models.CASCADE,
        related_name="print_settings",
        verbose_name="بخش فرم",
    )
    is_enabled = models.BooleanField(
        default=True,
        verbose_name="چاپ این بخش",
    )
    title_override = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="عنوان جایگزین در چاپ",
    )
    print_order = models.PositiveIntegerField(
        default=0,
        verbose_name="ترتیب چاپ",
    )

    class Meta:
        ordering = ["print_order", "pk"]
        verbose_name = "تنظیمات چاپ بخش"
        verbose_name_plural = "تنظیمات چاپ بخش"

    def __str__(self):
        return f"تنظیمات چاپ بخش - {self.section}"


class FormPrintFieldSettings(models.Model):
    """Print settings for either one normal field or one repeatable group."""

    class GroupLayout(models.TextChoices):
        TABLE = "TABLE", "جدول"
        BLOCKS = "BLOCKS", "بلوک‌های جداگانه"

    field = models.ForeignKey(
        FormField,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="print_settings",
        verbose_name="فیلد",
    )
    repeatable_group = models.ForeignKey(
        FormRepeatableGroup,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="print_settings",
        verbose_name="گروه تکرارشونده",
    )
    is_enabled = models.BooleanField(
        default=True,
        verbose_name="چاپ شود",
    )
    title_override = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="عنوان جایگزین در چاپ",
    )
    print_order = models.PositiveIntegerField(
        default=0,
        verbose_name="ترتیب چاپ",
    )
    group_layout = models.CharField(
        max_length=10,
        choices=GroupLayout.choices,
        default=GroupLayout.TABLE,
        verbose_name="نحوه نمایش گروه",
    )

    class Meta:
        ordering = ["print_order", "pk"]
        verbose_name = "تنظیمات چاپ فیلد یا گروه"
        verbose_name_plural = "تنظیمات چاپ فیلدها و گروه‌ها"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(field__isnull=False, repeatable_group__isnull=True)
                    | models.Q(field__isnull=True, repeatable_group__isnull=False)
                ),
                name="print_field_or_group_exactly_one",
            ),
            models.UniqueConstraint(
                fields=["field"],
                name="unique_print_settings_field",
            ),
            models.UniqueConstraint(
                fields=["repeatable_group"],
                name="unique_print_settings_group",
            ),
        ]

    def clean(self):
        super().clean()
        if (self.field_id is None) == (self.repeatable_group_id is None):
            raise ValidationError(
                "تنظیمات چاپ باید دقیقاً به یک فیلد یا یک گروه تکرارشونده متصل باشد."
            )

    def __str__(self):
        target = self.field or self.repeatable_group
        return f"تنظیمات چاپ - {target}"

