import os
import uuid

from django.conf import settings
from django.db import models


def workflow_form_file_upload_to(instance, filename):
    safe_name = os.path.basename(filename).replace("/", "_").replace("\\", "_")
    return (
        f"workflow_forms/{instance.form_data.instance_id}/"
        f"{instance.field.code}/{uuid.uuid4().hex}_{safe_name}"
    )


class FormFile(models.Model):
    form_data = models.ForeignKey(
        "workflow.FormData",
        on_delete=models.PROTECT,
        related_name="files",
    )
    field = models.ForeignKey(
        "workflow.FormField",
        on_delete=models.PROTECT,
        related_name="form_files",
    )
    row_id = models.CharField(max_length=100, blank=True, default="")
    file = models.FileField(upload_to=workflow_form_file_upload_to)
    original_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_form_files",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["field", "row_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["form_data", "field", "row_id"],
                name="unique_form_file_per_field_row",
            )
        ]

    def __str__(self):
        return self.original_name or os.path.basename(self.file.name)
