from django.conf import settings
from django.db import models


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

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["section", "code"],
                name="unique_form_field_code",
            ),
            models.UniqueConstraint(
                fields=["section", "order"],
                name="unique_form_field_order",
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

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"Form data - {self.instance}"