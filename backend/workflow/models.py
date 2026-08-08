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
        return f"{self.workflow.name} - {self.user}"

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
