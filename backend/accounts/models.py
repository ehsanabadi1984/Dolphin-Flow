from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class Job(models.Model):
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


class User(AbstractUser):
    class Meta(AbstractUser.Meta):
        permissions = [
            ("share_files", "اشتراک‌گذاری فایل"),
        ]

    job = models.ForeignKey(
        Job,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )

    def __str__(self):
        return self.get_full_name() or self.username


class UserPreference(models.Model):
    SESSION_TIMEOUT_CHOICES = [
        (1800, "۳۰ دقیقه"),
        (3600, "۱ ساعت"),
        (7200, "۲ ساعت"),
        (14400, "۴ ساعت"),
        (28800, "۸ ساعت"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    session_timeout = models.PositiveIntegerField(
        choices=SESSION_TIMEOUT_CHOICES,
        default=7200,
    )
    hidden_dashboard_process_ids = models.JSONField(
        default=list,
        blank=True,
    )
    sms_notifications_enabled = models.BooleanField(
        default=False,
        verbose_name="دریافت اعلان پیامکی",
    )

    class Meta:
        verbose_name = "ترجیح کاربر"
        verbose_name_plural = "ترجیحات کاربران"

    def __str__(self):
        return f"تنظیمات {self.user.username}"



class UserContactMethod(models.Model):
    class ChannelType(models.TextChoices):
        SMS = "SMS", "پیامک"

    class VerificationMethod(models.TextChoices):
        OTP = "OTP", "کد یک‌بارمصرف"
        MANUAL = "MANUAL", "تأیید دستی مدیر"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="contact_methods",
    )
    channel_type = models.CharField(
        max_length=16,
        choices=ChannelType.choices,
        default=ChannelType.SMS,
    )
    value = models.CharField(
        max_length=16,
        validators=[
            RegexValidator(
                regex=r"^\+?[0-9]{8,15}$",
                message="شماره موبایل را با ۸ تا ۱۵ رقم و بدون فاصله وارد کنید.",
            ),
        ],
        verbose_name="شماره موبایل",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="فعال",
    )
    is_verified = models.BooleanField(
        default=False,
        verbose_name="تأیید شده",
    )
    verification_method = models.CharField(
        max_length=16,
        choices=VerificationMethod.choices,
        blank=True,
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    verified_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_contact_methods",
    )
    verification_code_hash = models.CharField(
        max_length=128,
        blank=True,
    )
    verification_expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    verification_sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    verification_attempts = models.PositiveSmallIntegerField(
        default=0,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "راه ارتباطی کاربر"
        verbose_name_plural = "راه‌های ارتباطی کاربران"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "channel_type"),
                name="unique_user_contact_channel",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            previous_value = (
                type(self).objects.filter(pk=self.pk)
                .values_list("value", flat=True)
                .first()
            )
            if previous_value is not None and previous_value != self.value:
                self.is_verified = False
                self.verification_method = ""
                self.verified_at = None
                self.verified_by = None
                self.verification_code_hash = ""
                self.verification_expires_at = None
                self.verification_sent_at = None
                self.verification_attempts = 0

        if self.is_verified and self.verified_at is None:
            self.verified_at = timezone.now()
        elif not self.is_verified:
            self.verification_method = ""
            self.verified_at = None
            self.verified_by = None

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} · {self.value}"
