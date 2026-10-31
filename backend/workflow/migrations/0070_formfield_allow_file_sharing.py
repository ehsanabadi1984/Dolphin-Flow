from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0069_form_print_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="formfield",
            name="allow_file_sharing",
            field=models.BooleanField(
                default=False,
                help_text="فقط برای فیلدهای بارگذاری فایل قابل استفاده است.",
                verbose_name="اجازه اشتراک‌گذاری فایل",
            ),
        ),
        migrations.AddConstraint(
            model_name="formfield",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("field_type", "FILE"))
                    | models.Q(("allow_file_sharing", False))
                ),
                name="formfield_share_only_file",
            ),
        ),
    ]
