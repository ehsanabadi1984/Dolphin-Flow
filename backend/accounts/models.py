from django.contrib.auth.models import AbstractUser
from django.db import models


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

    class Meta:
        verbose_name = "ترجیح کاربر"
        verbose_name_plural = "ترجیحات کاربران"

    def __str__(self):
        return f"تنظیمات {self.user.username}"
