from django.core.exceptions import ValidationError
from django.db import models

from .models import WorkflowStepExecution


class HistoryConfiguration(models.Model):
    form = models.OneToOneField(
        "workflow.FormDefinition",
        on_delete=models.PROTECT,
        related_name="history_configuration",
    )

    name = models.CharField(
        max_length=150,
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

    def __str__(self):
        return self.name or f"History - {self.form.name}"


class HistoryField(models.Model):
    configuration = models.ForeignKey(
        HistoryConfiguration,
        on_delete=models.CASCADE,
        related_name="fields",
    )

    form_field = models.ForeignKey(
        "workflow.FormField",
        on_delete=models.PROTECT,
        related_name="history_fields",
    )

    display_label = models.CharField(
        max_length=200,
        blank=True,
    )

    display_order = models.PositiveIntegerField(
        default=0,
    )

    is_enabled = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["display_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["configuration", "form_field"],
                name="unique_history_field_configuration",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.configuration_id
            and self.form_field_id
            and self.configuration.form_id
            != self.form_field.section.form_id
        ):
            raise ValidationError(
                {
                    "form_field": (
                        "فیلد History باید متعلق به همان Form "
                        "تعریف‌شده در History Configuration باشد."
                    )
                }
            )

    def __str__(self):
        return self.display_label or self.form_field.label


class HistoryRecord(WorkflowStepExecution):
    """Proxy model exposing stored History snapshots in Admin."""

    class Meta:
        proxy = True
        verbose_name = "سابقه"
        verbose_name_plural = "سوابق"
