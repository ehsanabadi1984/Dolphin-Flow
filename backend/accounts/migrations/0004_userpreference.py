from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_job_remove_user_role_user_job"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserPreference",
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
                    "session_timeout",
                    models.PositiveIntegerField(
                        choices=[
                            (1800, "۳۰ دقیقه"),
                            (3600, "۱ ساعت"),
                            (7200, "۲ ساعت"),
                            (14400, "۴ ساعت"),
                            (28800, "۸ ساعت"),
                        ],
                        default=7200,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="preferences",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "verbose_name": "ترجیح کاربر",
                "verbose_name_plural": "ترجیحات کاربران",
            },
        ),
    ]
