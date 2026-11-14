from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workflow", "0084_sms_template_title_and_variables")]

    operations = [
        migrations.AddField(
            model_name="workflowsmssettings",
            name="sms_verification_template",
            field=models.TextField(
                default="کد تأیید شماره موبایل شما در Dolphin-Flow: {{ code }}",
                help_text="متغیر الزامی و ثابت: {{ code }}",
                verbose_name="متن پیامک تأیید شماره موبایل",
            ),
        ),
    ]
