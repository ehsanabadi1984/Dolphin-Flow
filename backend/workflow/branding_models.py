from django.db import models


class SystemBranding(models.Model):
    """Global, singleton branding configuration for Dolphin-Flow."""

    system_name = models.CharField(
        max_length=150,
        default="DolphinPlus",
        verbose_name="نام سیستم",
    )
    short_name = models.CharField(
        max_length=100,
        default="DolphinPlus",
        verbose_name="نام کوتاه",
    )
    browser_title = models.CharField(
        max_length=200,
        default="DolphinPlus",
        verbose_name="عنوان مرورگر",
    )
    sidebar_subtitle = models.CharField(
        max_length=200,
        default="Process Management",
        verbose_name="زیرعنوان سایدبار",
    )
    primary_logo = models.FileField(
        upload_to="branding/",
        blank=True,
        verbose_name="لوگوی اصلی",
    )
    sidebar_logo = models.FileField(
        upload_to="branding/",
        blank=True,
        verbose_name="لوگوی سایدبار",
    )
    favicon = models.FileField(
        upload_to="branding/",
        blank=True,
        verbose_name="Favicon",
    )
    sidebar_symbol = models.CharField(
        max_length=20,
        default="+",
        verbose_name="نماد سایدبار",
        help_text="نماد یا آیکون متنی کنار عنوان سایدبار؛ مانند +، ★ یا یک نماد Unicode دیگر.",
    )
    logo_alt_text = models.CharField(
        max_length=200,
        default="DolphinPlus",
        verbose_name="متن جایگزین لوگو",
    )

    class Meta:
        verbose_name = "هویت و برندینگ"
        verbose_name_plural = "هویت و برندینگ"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_current(cls):
        branding = cls.objects.first()
        if branding:
            return branding
        return cls()

    def __str__(self):
        return self.system_name or "هویت و برندینگ"
