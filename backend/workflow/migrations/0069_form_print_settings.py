# Generated for configurable form printing.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0068_formfield_default_value"),
    ]

    operations = [
        migrations.CreateModel(
            name="FormPrintSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_title", models.CharField(blank=True, default="", max_length=200, verbose_name="عنوان سند چاپی")),
                ("subtitle", models.CharField(blank=True, default="", max_length=250, verbose_name="زیرعنوان سند")),
                ("header_text", models.TextField(blank=True, default="", verbose_name="متن سربرگ")),
                ("footer_text", models.TextField(blank=True, default="", verbose_name="متن پابرگ")),
                ("page_size", models.CharField(choices=[("A4", "A4"), ("A5", "A5")], default="A4", max_length=2, verbose_name="اندازه کاغذ")),
                ("orientation", models.CharField(choices=[("PORTRAIT", "عمودی"), ("LANDSCAPE", "افقی")], default="PORTRAIT", max_length=10, verbose_name="جهت صفحه")),
                ("show_workflow_name", models.BooleanField(default=True, verbose_name="نمایش نام فرایند")),
                ("show_instance_number", models.BooleanField(default=True, verbose_name="نمایش شماره فرایند")),
                ("show_created_at", models.BooleanField(default=True, verbose_name="نمایش تاریخ ایجاد")),
                ("show_empty_values", models.BooleanField(default=False, verbose_name="نمایش فیلدهای خالی")),
                ("show_signatures", models.BooleanField(default=False, verbose_name="نمایش محل امضا")),
                ("signature_count", models.PositiveSmallIntegerField(default=2, verbose_name="تعداد محل امضا")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")),
                ("form", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="print_settings", to="workflow.formdefinition", verbose_name="فرم")),
            ],
            options={
                "verbose_name": "تنظیمات چاپ فرم",
                "verbose_name_plural": "تنظیمات چاپ فرم",
            },
        ),
        migrations.CreateModel(
            name="FormPrintSectionSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=True, verbose_name="چاپ این بخش")),
                ("title_override", models.CharField(blank=True, default="", max_length=200, verbose_name="عنوان جایگزین در چاپ")),
                ("print_order", models.PositiveIntegerField(default=0, verbose_name="ترتیب چاپ")),
                ("section", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="print_settings", to="workflow.formsection", verbose_name="بخش فرم")),
            ],
            options={
                "verbose_name": "تنظیمات چاپ بخش",
                "verbose_name_plural": "تنظیمات چاپ بخش",
                "ordering": ["print_order", "pk"],
            },
        ),
        migrations.CreateModel(
            name="FormPrintFieldSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=True, verbose_name="چاپ شود")),
                ("title_override", models.CharField(blank=True, default="", max_length=200, verbose_name="عنوان جایگزین در چاپ")),
                ("print_order", models.PositiveIntegerField(default=0, verbose_name="ترتیب چاپ")),
                ("group_layout", models.CharField(choices=[("TABLE", "جدول"), ("BLOCKS", "بلوک‌های جداگانه")], default="TABLE", max_length=10, verbose_name="نحوه نمایش گروه")),
                ("field", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="print_settings", to="workflow.formfield", verbose_name="فیلد")),
                ("repeatable_group", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="print_settings", to="workflow.formrepeatablegroup", verbose_name="گروه تکرارشونده")),
            ],
            options={
                "verbose_name": "تنظیمات چاپ فیلد یا گروه",
                "verbose_name_plural": "تنظیمات چاپ فیلدها و گروه‌ها",
                "ordering": ["print_order", "pk"],
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(("field__isnull", False), ("repeatable_group__isnull", True))
                            | models.Q(("field__isnull", True), ("repeatable_group__isnull", False))
                        ),
                        name="print_field_or_group_exactly_one",
                    ),
                    models.UniqueConstraint(fields=("field",), name="unique_print_settings_field"),
                    models.UniqueConstraint(fields=("repeatable_group",), name="unique_print_settings_group"),
                ],
            },
        ),
    ]
