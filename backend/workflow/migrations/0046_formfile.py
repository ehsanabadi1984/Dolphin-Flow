from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import workflow.form_file_models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0045_instancedevice_draft_device_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="FormFile",
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
                ("row_id", models.CharField(blank=True, default="", max_length=100)),
                (
                    "file",
                    models.FileField(
                        upload_to=workflow.form_file_models.workflow_form_file_upload_to,
                    ),
                ),
                ("original_name", models.CharField(blank=True, max_length=255)),
                ("file_size", models.PositiveBigIntegerField(default=0)),
                ("content_type", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "field",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="form_files",
                        to="workflow.formfield",
                    ),
                ),
                (
                    "form_data",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="files",
                        to="workflow.formdata",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_form_files",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["field", "row_id", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="formfile",
            constraint=models.UniqueConstraint(
                fields=("form_data", "field", "row_id"),
                name="unique_form_file_per_field_row",
            ),
        ),
    ]
