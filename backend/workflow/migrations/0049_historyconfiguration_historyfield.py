from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0048_formfield_layout_order_formrepeatablegroup_layout_order"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoryConfiguration",
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
                    "name",
                    models.CharField(
                        blank=True,
                        max_length=150,
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "form",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="history_configuration",
                        to="workflow.formdefinition",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="HistoryField",
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
                    "display_label",
                    models.CharField(
                        blank=True,
                        max_length=200,
                    ),
                ),
                (
                    "display_order",
                    models.PositiveIntegerField(default=0),
                ),
                (
                    "is_enabled",
                    models.BooleanField(default=True),
                ),
                (
                    "configuration",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fields",
                        to="workflow.historyconfiguration",
                    ),
                ),
                (
                    "form_field",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="history_fields",
                        to="workflow.formfield",
                    ),
                ),
            ],
            options={
                "ordering": ["display_order", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="historyfield",
            constraint=models.UniqueConstraint(
                fields=("configuration", "form_field"),
                name="unique_history_field_configuration",
            ),
        ),
    ]
