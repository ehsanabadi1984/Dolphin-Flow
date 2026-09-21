from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0047_alter_formfield_field_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="formrepeatablegroup",
            name="parent_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="child_groups",
                to="workflow.formrepeatablegroup",
            ),
        ),
        migrations.CreateModel(
            name="RepeatableRow",
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
                ("row_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rows",
                        to="workflow.formrepeatablegroup",
                    ),
                ),
                (
                    "instance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="repeatable_rows",
                        to="workflow.workflowinstance",
                    ),
                ),
                (
                    "instance_device",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="repeatable_row",
                        to="workflow.instancedevice",
                    ),
                ),
                (
                    "parent_row",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="child_rows",
                        to="workflow.repeatablerow",
                    ),
                ),
            ],
            options={
                "ordering": ["group", "row_order", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="repeatablerow",
            constraint=models.UniqueConstraint(
                condition=models.Q(("parent_row__isnull", True)),
                fields=("instance", "group", "row_order"),
                name="unique_repeatable_root_row_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="repeatablerow",
            constraint=models.UniqueConstraint(
                condition=models.Q(("parent_row__isnull", False)),
                fields=("instance", "group", "parent_row", "row_order"),
                name="unique_repeatable_child_row_order",
            ),
        ),
        migrations.CreateModel(
            name="RepeatableRowValue",
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
                ("text_value", models.TextField(blank=True, null=True)),
                (
                    "decimal_value",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=20,
                        null=True,
                    ),
                ),
                ("date_value", models.DateField(blank=True, null=True)),
                (
                    "datetime_value",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "boolean_value",
                    models.BooleanField(blank=True, null=True),
                ),
                (
                    "reference_id",
                    models.CharField(
                        blank=True,
                        max_length=150,
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "field",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="repeatable_row_values",
                        to="workflow.formfield",
                    ),
                ),
                (
                    "lookup_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="repeatable_row_values",
                        to="workflow.lookupitem",
                    ),
                ),
                (
                    "row",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="values",
                        to="workflow.repeatablerow",
                    ),
                ),
                (
                    "static_choice_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="repeatable_row_values",
                        to="workflow.staticchoiceitem",
                    ),
                ),
            ],
            options={
                "ordering": ["field__order", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="repeatablerowvalue",
            constraint=models.UniqueConstraint(
                fields=("row", "field"),
                name="unique_repeatable_row_field_value",
            ),
        ),
    ]
