from calendar import monthrange
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
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


class BackupStorageDestination(models.Model):
    class BackendType(models.TextChoices):
        SMB = "SMB", "SMB"
        SFTP = "SFTP", "SFTP"
        MOUNTED_FOLDER = "MOUNTED_FOLDER", "پوشه Mount شده (Legacy)"

    name = models.CharField(max_length=150, unique=True, verbose_name="نام مقصد")
    backend_type = models.CharField(
        max_length=20,
        choices=BackendType.choices,
        default=BackendType.SMB,
        verbose_name="نوع اتصال",
    )
    host = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="آدرس سرور",
        help_text="IP یا نام DNS مقصد؛ مثلاً 192.168.1.50",
    )
    port = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="پورت",
        help_text="در صورت خالی بودن، پورت پیش‌فرض پروتکل استفاده می‌شود.",
    )
    share = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="نام Share",
        help_text="برای SMB؛ مثلاً DolphinBackup",
    )
    remote_path = models.CharField(
        max_length=512,
        blank=True,
        verbose_name="مسیر مقصد",
        help_text="مسیر داخل Share در SMB یا مسیر پوشه در SFTP.",
    )
    username = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="نام کاربری",
    )
    encrypted_password = models.TextField(
        blank=True,
        editable=False,
        verbose_name="رمزنگاری‌شده",
    )
    enabled = models.BooleanField(default=True, verbose_name="فعال")
    description = models.TextField(blank=True, verbose_name="توضیحات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="ایجاد شده")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")

    class Meta:
        ordering = ["name"]
        verbose_name = "مقصد ذخیره‌سازی شبکه"
        verbose_name_plural = "مقصدهای ذخیره‌سازی شبکه"

    def __str__(self):
        return self.name

    @property
    def password_configured(self):
        return bool(self.encrypted_password)

    def set_password(self, raw_password):
        from .storage import encrypt_storage_secret
        self.encrypted_password = encrypt_storage_secret(raw_password or "")

    def get_password(self):
        from .storage import decrypt_storage_secret
        return decrypt_storage_secret(self.encrypted_password)

    def clean(self):
        super().clean()
        if not self.name.strip():
            raise ValidationError({"name": "نام مقصد الزامی است."})

        if self.backend_type == self.BackendType.MOUNTED_FOLDER:
            if not self.remote_path.strip():
                raise ValidationError({"remote_path": "مسیر مقصد الزامی است."})
            if not Path(self.remote_path).is_absolute():
                raise ValidationError({"remote_path": "مسیر مقصد باید یک مسیر مطلق باشد."})
            return

        if not self.host.strip():
            raise ValidationError({"host": "آدرس سرور الزامی است."})

        if self.backend_type == self.BackendType.SMB:
            if not self.share.strip():
                raise ValidationError({"share": "نام Share برای SMB الزامی است."})
            if not self.username.strip():
                raise ValidationError({"username": "نام کاربری برای SMB الزامی است."})
            if not self.encrypted_password:
                raise ValidationError({"username": "رمز عبور مقصد هنوز تنظیم نشده است."})

        elif self.backend_type == self.BackendType.SFTP:
            if not self.remote_path.strip():
                raise ValidationError({"remote_path": "مسیر مقصد برای SFTP الزامی است."})
            if not self.username.strip():
                raise ValidationError({"username": "نام کاربری برای SFTP الزامی است."})
            if not self.encrypted_password:
                raise ValidationError({"username": "رمز عبور مقصد هنوز تنظیم نشده است."})

class BackupSchedule(models.Model):
    class Frequency(models.TextChoices):
        ONCE = "ONCE", "یک‌بار"
        DAILY = "DAILY", "روزانه"
        WEEKLY = "WEEKLY", "هفتگی"
        MONTHLY = "MONTHLY", "ماهانه"
        INTERVAL = "INTERVAL", "دوره‌ای"

    class Destination(models.TextChoices):
        LOCAL = "LOCAL", "محلی"
        NETWORK = "NETWORK", "شبکه"
        BOTH = "BOTH", "محلی + شبکه"

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "دوشنبه"
        TUESDAY = 1, "سه‌شنبه"
        WEDNESDAY = 2, "چهارشنبه"
        THURSDAY = 3, "پنج‌شنبه"
        FRIDAY = 4, "جمعه"
        SATURDAY = 5, "شنبه"
        SUNDAY = 6, "یکشنبه"

    name = models.CharField(max_length=150, verbose_name="نام زمان‌بندی")
    enabled = models.BooleanField(default=True, verbose_name="فعال")
    frequency = models.CharField(
        max_length=20,
        choices=Frequency.choices,
        verbose_name="نوع زمان‌بندی",
    )
    run_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="زمان اجرا",
        help_text="برای اجرای یک‌باره استفاده می‌شود.",
    )
    time_of_day = models.TimeField(
        null=True,
        blank=True,
        verbose_name="ساعت اجرا",
    )
    weekday = models.PositiveSmallIntegerField(
        choices=Weekday.choices,
        null=True,
        blank=True,
        verbose_name="روز هفته",
    )
    day_of_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="روز ماه",
    )
    interval_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="فاصله اجرا (دقیقه)",
    )
    starts_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="شروع دوره‌ای",
        help_text="برای زمان‌بندی دوره‌ای، نقطه شروع محاسبه فاصله اجرا.",
    )
    include_media = models.BooleanField(
        default=True,
        verbose_name="شامل فایل‌های رسانه",
    )
    destination = models.CharField(
        max_length=20,
        choices=Destination.choices,
        default=Destination.LOCAL,
        verbose_name="مقصد",
    )
    network_storage = models.ForeignKey(
        BackupStorageDestination,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="schedules",
        verbose_name="مقصد شبکه",
    )
    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="آخرین اجرا",
        editable=False,
    )
    next_run_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="اجرای بعدی",
        editable=False,
    )
    last_status = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="وضعیت آخرین اجرا",
        editable=False,
    )
    last_error = models.TextField(
        blank=True,
        verbose_name="خطای آخرین اجرا",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="ایجاد شده")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")

    class Meta:
        ordering = ["name", "-created_at"]
        verbose_name = "زمان‌بندی پشتیبان‌گیری"
        verbose_name_plural = "زمان‌بندی‌های پشتیبان‌گیری"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        if not self.name.strip():
            raise ValidationError({"name": "نام زمان‌بندی الزامی است."})

        required = {
            self.Frequency.ONCE: ("run_at", self.run_at, "زمان اجرا"),
            self.Frequency.DAILY: ("time_of_day", self.time_of_day, "ساعت اجرا"),
            self.Frequency.WEEKLY: ("time_of_day", self.time_of_day, "ساعت اجرا"),
            self.Frequency.MONTHLY: ("time_of_day", self.time_of_day, "ساعت اجرا"),
            self.Frequency.INTERVAL: ("interval_minutes", self.interval_minutes, "فاصله اجرا"),
        }
        field_name, value, label = required[self.frequency]
        if value is None:
            raise ValidationError({field_name: f"{label} برای این نوع زمان‌بندی الزامی است."})

        if self.frequency == self.Frequency.WEEKLY and self.weekday is None:
            raise ValidationError({"weekday": "روز هفته برای زمان‌بندی هفتگی الزامی است."})

        if self.frequency == self.Frequency.MONTHLY:
            if self.day_of_month is None:
                raise ValidationError({"day_of_month": "روز ماه برای زمان‌بندی ماهانه الزامی است."})
            if not 1 <= self.day_of_month <= 31:
                raise ValidationError({"day_of_month": "روز ماه باید بین ۱ تا ۳۱ باشد."})

        if self.frequency == self.Frequency.INTERVAL:
            if self.interval_minutes is None or self.interval_minutes < 1:
                raise ValidationError({"interval_minutes": "فاصله اجرا باید حداقل ۱ دقیقه باشد."})
            if self.starts_at is None:
                raise ValidationError({"starts_at": "زمان شروع برای زمان‌بندی دوره‌ای الزامی است."})

        if self.destination in (self.Destination.NETWORK, self.Destination.BOTH):
            if self.network_storage_id is None:
                raise ValidationError({"network_storage": "برای مقصد شبکه باید یک مقصد ذخیره‌سازی انتخاب شود."})
            if self.network_storage is not None and not self.network_storage.enabled:
                raise ValidationError({"network_storage": "مقصد ذخیره‌سازی انتخاب‌شده غیرفعال است."})
        elif self.network_storage_id is not None:
            raise ValidationError({"network_storage": "برای مقصد محلی، مقصد شبکه نباید انتخاب شود."})

    def calculate_next_run(self, now=None):
        """Return the next occurrence for this schedule."""
        now = now or timezone.now()
        local_now = timezone.localtime(now)
        current_tz = timezone.get_current_timezone()

        if self.frequency == self.Frequency.ONCE:
            return self.run_at if self.run_at and self.run_at > now else (
                now if self.run_at else None
            )

        if self.frequency == self.Frequency.DAILY:
            candidate = local_now.replace(
                hour=self.time_of_day.hour,
                minute=self.time_of_day.minute,
                second=0,
                microsecond=0,
            )
            if candidate <= local_now:
                candidate += timedelta(days=1)
            return candidate.astimezone(current_tz)

        if self.frequency == self.Frequency.WEEKLY:
            days_ahead = (self.weekday - local_now.weekday()) % 7
            candidate = local_now + timedelta(days=days_ahead)
            candidate = candidate.replace(
                hour=self.time_of_day.hour,
                minute=self.time_of_day.minute,
                second=0,
                microsecond=0,
            )
            if candidate <= local_now:
                candidate += timedelta(days=7)
            return candidate.astimezone(current_tz)

        if self.frequency == self.Frequency.MONTHLY:
            year, month = local_now.year, local_now.month
            for _ in range(24):
                last_day = monthrange(year, month)[1]
                day = min(self.day_of_month, last_day)
                candidate = local_now.replace(
                    year=year,
                    month=month,
                    day=day,
                    hour=self.time_of_day.hour,
                    minute=self.time_of_day.minute,
                    second=0,
                    microsecond=0,
                )
                if candidate > local_now:
                    return candidate.astimezone(current_tz)
                if month == 12:
                    year, month = year + 1, 1
                else:
                    month += 1
            return None

        if self.frequency == self.Frequency.INTERVAL:
            anchor = self.starts_at
            if anchor is None:
                return None
            if anchor > now:
                return anchor
            return now + timedelta(minutes=self.interval_minutes)

        return None

    def prepare_next_run(self, now=None):
        self.next_run_at = self.calculate_next_run(now or timezone.now())

    def save(self, *args, **kwargs):
        if self._state.adding and self.next_run_at is None:
            self.next_run_at = (
                self.calculate_next_run()
                if self.enabled
                else None
            )
        super().save(*args, **kwargs)


class Backup(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RUNNING = "RUNNING", "در حال اجرا"
        SUCCESS = "SUCCESS", "موفق"
        FAILED = "FAILED", "ناموفق"

    class Destination(models.TextChoices):
        LOCAL = "LOCAL", "محلی"
        NETWORK = "NETWORK", "شبکه"
        BOTH = "BOTH", "محلی + شبکه"

    class NetworkStatus(models.TextChoices):
        NOT_REQUESTED = "NOT_REQUESTED", "بدون انتقال شبکه"
        PENDING = "PENDING", "در انتظار انتقال"
        SUCCESS = "SUCCESS", "انتقال موفق"
        FAILED = "FAILED", "انتقال ناموفق"

    filename = models.CharField(max_length=255, blank=True, help_text="نام فایل نهایی بایگانی (بدون مسیر).")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    storage_path = models.CharField(max_length=512, blank=True)
    size = models.BigIntegerField(null=True, blank=True, help_text="حجم کل فایل بایگانی به بایت.")
    database_size = models.BigIntegerField(null=True, blank=True, help_text="حجم فایل dump پایگاه داده به بایت.")
    media_size = models.BigIntegerField(null=True, blank=True, help_text="حجم بایگانی فایل‌های رسانه به بایت.")
    includes_media = models.BooleanField(default=True)
    checksum = models.CharField(max_length=64, blank=True, help_text="SHA-256 فایل نهایی بایگانی.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_backups")
    is_pre_restore_backup = models.BooleanField(default=False, help_text="پشتیبان امنیتی خودکار پیش از بازیابی.")

    schedule = models.ForeignKey(
        BackupSchedule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backups",
        verbose_name="زمان‌بندی",
    )
    destination = models.CharField(
        max_length=20,
        choices=Destination.choices,
        default=Destination.LOCAL,
        verbose_name="مقصد",
    )
    network_storage = models.ForeignKey(
        BackupStorageDestination,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backups",
        verbose_name="مقصد شبکه",
    )
    network_status = models.CharField(
        max_length=20,
        choices=NetworkStatus.choices,
        default=NetworkStatus.NOT_REQUESTED,
        verbose_name="وضعیت انتقال شبکه",
    )
    network_storage_path = models.CharField(max_length=512, blank=True, verbose_name="مسیر شبکه")
    network_size = models.BigIntegerField(null=True, blank=True, verbose_name="حجم فایل شبکه")
    network_checksum = models.CharField(max_length=64, blank=True, verbose_name="SHA-256 شبکه")
    network_copied_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان انتقال شبکه")
    network_error = models.TextField(blank=True, verbose_name="خطای انتقال شبکه")

    class SourceType(models.TextChoices):
        LOCAL_CREATED = "LOCAL_CREATED", "ایجاد محلی"
        IMPORTED = "IMPORTED", "وارد شده"

    source_type = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.LOCAL_CREATED, help_text="منبع ایجاد این پشتیبان.")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "پشتیبان‌گیری"
        verbose_name_plural = "پشتیبان‌گیری‌ها"
        permissions = [
            ("create_backup", "می‌تواند پشتیبان‌گیری جدید ایجاد کند"),
            ("download_backup", "می‌تواند فایل پشتیبان را دانلود کند"),
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
    """A single restore operation and its audit trail."""
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RESTORING = "RESTORING", "در حال بازیابی"
        SUCCESS = "SUCCESS", "موفق"
        FAILED = "FAILED", "ناموفق"

    backup = models.ForeignKey(Backup, null=True, blank=True, on_delete=models.SET_NULL, related_name="restores")
    archive_filename = models.CharField(max_length=255, blank=True)
    product_version = models.CharField(max_length=50, blank=True)
    database_engine = models.CharField(max_length=50, blank=True)
    database_backup_format = models.CharField(max_length=50, blank=True)
    includes_media = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_restores")
    requested_by_username = models.CharField(max_length=150, blank=True)
    pre_restore_backup = models.ForeignKey(Backup, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    pre_restore_backup_filename = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "بازیابی"
        verbose_name_plural = "بازیابی‌ها"
        permissions = [("restore_backup", "می‌تواند پشتیبان را بازیابی کند")]

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
