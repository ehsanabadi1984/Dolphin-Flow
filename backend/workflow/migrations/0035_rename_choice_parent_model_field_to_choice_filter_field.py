from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0034_formfield_choice_parent_model_field"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE workflow_formfield
                RENAME COLUMN choice_parent_model_field
                TO choice_filter_field;
            """,
            reverse_sql="""
                ALTER TABLE workflow_formfield
                RENAME COLUMN choice_filter_field
                TO choice_parent_model_field;
            """,
        ),
    ]