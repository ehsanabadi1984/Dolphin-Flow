from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0052_historyconfiguration_existing"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemBranding",
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
                    "system_name",
                    models.CharField(
                        default="DolphinPlus",
                        max_length=150,
                        verbose_name="نام سیستم",
                    ),
                ),
                (
                    "short_name",
                    models.CharField(
                        default="DolphinPlus",
                        max_length=100,
                        verbose_name="نام کوتاه",
                    ),
                ),
                (
                    "browser_title",
                    models.CharField(
                        default="DolphinPlus",
                        max_length=200,
                        verbose_name="عنوان مرورگر",
                    ),
                ),
                (
                    "sidebar_subtitle",
                    models.CharField(
                        default="Process Management",
                        max_length=200,
                        verbose_name="زیرعنوان سایدبار",
                    ),
                ),
                (
                    "primary_logo",
                    models.FileField(
                        blank=True,
                        upload_to="branding/",
                        verbose_name="لوگوی اصلی",
                    ),
                ),
                (
                    "sidebar_logo",
                    models.FileField(
                        blank=True,
                        upload_to="branding/",
                        verbose_name="لوگوی سایدبار",
                    ),
                ),
                (
                    "favicon",
                    models.FileField(
                        blank=True,
                        upload_to="branding/",
                        verbose_name="Favicon",
                    ),
                ),
                (
                    "sidebar_symbol",
                    models.CharField(
                        default="+",
                        help_text="نماد یا آیکون متنی کنار عنوان سایدبار؛ مانند +، ★ یا یک نماد Unicode دیگر.",
                        max_length=20,
                        verbose_name="نماد سایدبار",
                    ),
                ),
                (
                    "logo_alt_text",
                    models.CharField(
                        default="DolphinPlus",
                        max_length=200,
                        verbose_name="متن جایگزین لوگو",
                    ),
                ),
            ],
            options={
                "verbose_name": "هویت و برندینگ",
                "verbose_name_plural": "هویت و برندینگ",
            },
        ),
    ]
