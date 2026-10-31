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

    @classmethod
    def delete_for_row(cls, *, form_data, row_id):
        """Delete FILE sidecars through the central storage lifecycle service."""
        from .file_lifecycle_services import FileLifecycleService

        files = list(cls.objects.filter(
            form_data=form_data,
            row_id=str(row_id),
        ))
        for item in files:
            FileLifecycleService.delete_form_file(item)

        return len(files)

    def __str__(self):
        return self.original_name or os.path.basename(self.file.name)



class SharedFileAsset(models.Model):
    """Database reference to an existing stored file; no file bytes are copied."""

    form_file = models.ForeignKey(
        FormFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shared_assets",
    )
    storage_backend = models.CharField(max_length=255, default="default", editable=False)
    storage_name = models.CharField(max_length=500, verbose_name="مسیر فایل در فضای ذخیره‌سازی")
    original_name = models.CharField(max_length=255, blank=True, default="")
    file_size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["storage_backend", "storage_name"], name="uniq_shared_file_storage"),
        ]

    @classmethod
    def get_or_create_for_form_file(cls, form_file):
        if not form_file.file or not form_file.file.name:
            raise ValueError("FormFile must reference an existing stored file.")
        return cls.objects.get_or_create(
            storage_backend="default",
            storage_name=form_file.file.name,
            defaults={
                "form_file": form_file,
                "original_name": form_file.original_name,
                "file_size": form_file.file_size,
                "content_type": form_file.content_type,
            },
        )

    def __str__(self):
        return self.original_name or self.storage_name.rsplit("/", 1)[-1]
