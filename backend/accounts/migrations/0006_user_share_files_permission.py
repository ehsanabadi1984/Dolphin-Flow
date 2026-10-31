from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_userpreference_hidden_dashboard_process_ids"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": [
                    ("share_files", "اشتراک‌گذاری فایل"),
                ],
                "verbose_name": "user",
                "verbose_name_plural": "users",
            },
        ),
    ]
