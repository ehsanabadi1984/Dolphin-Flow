from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_backup_filename(now=None):
    """Build a deterministic backup filename, e.g. DolphinFlow_Backup_2026-09-04_020000.dfbak."""
    now = now or timezone.localtime(timezone.now())
    return f"DolphinFlow_Backup_{now:%Y-%m-%d_%H%M%S}.dfbak"


def humanize_duration(duration):
    """Render a timedelta as a short Persian human string (used by Backup/Restore)."""
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

    # True when this archive is the automatic safety snapshot taken right
    # before a Restore overwrites the database/media. Such snapshots are
    # created only by the Restore pipeline and are kept out of the normal
    # user-facing backup list semantics.
    is_pre_restore_backup = models.BooleanField(
        default=False,
        help_text="پشتیبان امنیتی خودکار پیش از بازیابی.",
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
        return humanize_duration(self.duration)


class Restore(models.Model):
    """A single restore operation and its audit trail.

    Restoring the database replaces every row in the current database with the
    data from the archive, including any rows of this model. For that reason
    this model keeps plain-text snapshots (``archive_filename``,
    ``requested_by_username``, manifest summary) that survive the database
    replacement, and the worker records the terminal status either on the
    original row (when it still exists) or on a freshly created audit row in
    the restored database.
    """

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RESTORING = "RESTORING", "در حال بازیابی"
        SUCCESS = "SUCCESS", "موفق"
        FAILED = "FAILED", "ناموفق"

    # Source archive record (local-storage phase). Nullable so a future
    # network/cloud source does not depend on a local Backup row.
    backup = models.ForeignKey(
        Backup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="restores",
    )

    # Snapshot of the archive file name; survives the database replacement.
    archive_filename = models.CharField(
        max_length=255,
        blank=True,
    )

    # Manifest summary snapshots (audit values read from the archive).
    product_version = models.CharField(
        max_length=50,
        blank=True,
    )

    database_engine = models.CharField(
        max_length=50,
        blank=True,
    )

    database_backup_format = models.CharField(
        max_length=50,
        blank=True,
    )

    includes_media = models.BooleanField(
        default=True,
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

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_restores",
    )

    # Username snapshot; survives the database replacement (the restored
    # database may not contain the requesting user any more).
    requested_by_username = models.CharField(
        max_length=150,
        blank=True,
    )

    # The automatic safety snapshot taken right before the destructive steps.
    # Its DB row is normally replaced together with the database, so the file
    # name is snapshotted here as well and the row is re-created after a
    # successful restore.
    pre_restore_backup = models.ForeignKey(
        Backup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    pre_restore_backup_filename = models.CharField(
        max_length=255,
        blank=True,
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
        verbose_name = "بازیابی"
        verbose_name_plural = "بازیابی‌ها"
        permissions = [
            (
                "restore_backup",
                "می‌تواند پشتیبان را بازیابی کند",
            ),
        ]

    def __str__(self):
        return self.archive_filename or f"Restore #{self.pk}"

    @property
    def duration(self):
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None

    @property
    def duration_display(self):
        return humanize_duration(self.duration)
