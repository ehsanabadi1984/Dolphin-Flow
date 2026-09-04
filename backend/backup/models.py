from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_backup_filename(now=None):
    """Build a deterministic backup filename, e.g. DolphinFlow_Backup_2026-09-04_020000.dfbak."""
    now = now or timezone.localtime(timezone.now())
    return f"DolphinFlow_Backup_{now:%Y-%m-%d_%H%M%S}.dfbak"


class Backup(models.Model):
    """A single backup archive (a ``.dfbak`` file) and its execution state."""

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RUNNING = "RUNNING", "در حال اجرا"
        SUCCESS = "SUCCESS", "موفق"
        FAILED = "FAILED", "ناموفق"

    filename = models.CharField(
        max_length=255,
        blank=True,
        help_text="نام فایل نهایی بایگانی (بدون مسیر).",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # Relative key inside the active backup storage backend (e.g. the file name
    # inside BACKUP_ROOT for the local backend). Never an arbitrary path.
    storage_path = models.CharField(
        max_length=512,
        blank=True,
    )

    size = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="حجم کل فایل بایگانی به بایت.",
    )

    database_size = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="حجم فایل dump پایگاه داده به بایت.",
    )

    media_size = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="حجم بایگانی فایل‌های رسانه به بایت.",
    )

    includes_media = models.BooleanField(
        default=True,
    )

    checksum = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 فایل نهایی بایگانی.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_backups",
    )

    error_message = models.TextField(
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
        verbose_name = "پشتیبان‌گیری"
        verbose_name_plural = "پشتیبان‌گیری‌ها"
        permissions = [
            (
                "create_backup",
                "می‌تواند پشتیبان‌گیری جدید ایجاد کند",
            ),
            (
                "download_backup",
                "می‌تواند فایل پشتیبان را دانلود کند",
            ),
        ]

    def __str__(self):
        return self.filename or f"Backup #{self.pk}"

    @property
    def duration(self):
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None

    @property
    def duration_display(self):
        duration = self.duration
        if duration is None:
            return "—"

        total_seconds = int(duration.total_seconds())
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if hours:
            return f"{hours} ساعت و {minutes} دقیقه"
        if minutes:
            return f"{minutes} دقیقه و {seconds} ثانیه"
        return f"{seconds} ثانیه"