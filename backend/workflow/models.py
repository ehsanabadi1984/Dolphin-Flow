import re
import uuid
from django.conf import settings
from django.db import models
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

    section = models.ForeignKey(
        FormSection,
        on_delete=models.PROTECT,
        related_name="repeatable_groups",
    )

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
    )

    group_type = models.CharField(
        max_length=20,
        choices=GroupType.choices,
        default=GroupType.NORMAL,
    )

    description = models.TextField(
        blank=True,
    )

    order = models.PositiveIntegerField(
        default=0,
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

    def __str__(self):
        return (
            f"{self.section.name} - "
            f"{self.name}"
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

    is_required = models.BooleanField(
        default=False,
    )

    is_history_enabled = models.BooleanField(
        default=False,
    )

    order = models.PositiveIntegerField(
        default=0,
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


    def clean(self):
        super().clean()

        # --------------------------------------------------
        # General Validation
        # --------------------------------------------------

        if self.repeatable_group:
            if self.repeatable_group.section_id != self.section_id:
                raise ValidationError(
                    "گروه تکرارشونده باید متعلق به همان Section فیلد باشد."
                )

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
        ]

    def __str__(self):
        return f"{self.section.name} - {self.label}"


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

    def clean(self):
        super().clean()

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