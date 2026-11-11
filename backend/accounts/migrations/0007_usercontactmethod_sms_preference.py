import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_user_share_files_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="sms_notifications_enabled",
            field=models.BooleanField(
                default=False,
                verbose_name="دریافت اعلان پیامکی",
            ),
        ),
        migrations.CreateModel(
            name="UserContactMethod",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "channel_type",
                    models.CharField(
                        choices=[("SMS", "پیامک")],
                        default="SMS",
                        max_length=16,
                    ),
                ),
                (
                    "value",
                    models.CharField(
                        max_length=16,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="شماره موبایل را با ۸ تا ۱۵ رقم و بدون فاصله وارد کنید.",
                                regex=r"^\+?[0-9]{8,15}$",
                            ),
                        ],
                        verbose_name="شماره موبایل",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="فعال"),
                ),
                (
                    "is_verified",
                    models.BooleanField(default=False, verbose_name="تأیید شده"),
                ),
                (
                    "verification_method",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("OTP", "کد یک‌بارمصرف"),
                            ("MANUAL", "تأیید دستی مدیر"),
                        ],
                        max_length=16,
                    ),
                ),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                (
                    "verification_code_hash",
                    models.CharField(blank=True, max_length=128),
                ),
                (
                    "verification_expires_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "verification_sent_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("verification_attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contact_methods",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "verified_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="verified_contact_methods",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "راه ارتباطی کاربر",
                "verbose_name_plural": "راه‌های ارتباطی کاربران",
            },
        ),
        migrations.AddConstraint(
            model_name="usercontactmethod",
            constraint=models.UniqueConstraint(
                fields=("user", "channel_type"),
                name="unique_user_contact_channel",
            ),
        ),
    ]
