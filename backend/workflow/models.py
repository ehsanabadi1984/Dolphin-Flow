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
    )

    reported_problem = models.TextField(
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
        return (
            f"{self.workflow.name}: "
            f"{self.from_step.name} → {self.to_step.name}"
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

class FormField(models.Model):

    class FieldType(models.TextChoices):
        TEXT = "TEXT", "متن"
        TEXTAREA = "TEXTAREA", "متن چندخطی"
        NUMBER = "NUMBER", "عدد"
        DATE = "DATE", "تاریخ"
        DATETIME = "DATETIME", "تاریخ و زمان"
        BOOLEAN = "BOOLEAN", "بله/خیر"
        SELECT = "SELECT", "انتخابی"

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

    label = models.CharField(
        max_length=200,
    )

    help_text = models.TextField(
        blank=True,
    )

    is_required = models.BooleanField(
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

    def clean(self):
        super().clean()

        if self.repeatable_group:
            if self.repeatable_group.section_id != self.section_id:
                raise ValidationError(
                    "گروه تکرارشونده باید متعلق به همان Section فیلد باشد."
                )

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

    class Meta:
        ordering = ["field"]

    def __str__(self):
        subject = self.user or self.role or "GLOBAL"
        return f"{self.field} - {subject}"


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