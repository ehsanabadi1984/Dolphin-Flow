from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workflow", "0083_sms_template_global_fallback")]

    operations = [
        migrations.AddField(
            model_name="smstemplate",
            name="title_template",
            field=models.TextField(blank=True, verbose_name="عنوان پیامک"),
        ),
        migrations.AlterField(
            model_name="smstemplate",
            name="body_template",
            field=models.TextField(verbose_name="متن پیامک"),
        ),
        migrations.AddField(
            model_name="smstemplate",
            name="legacy_format",
            field=models.BooleanField(default=True, editable=False),
        ),
        migrations.AlterField(
            model_name="smstemplate",
            name="legacy_format",
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
