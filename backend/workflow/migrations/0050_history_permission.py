from django.db import migrations


HISTORY_ACTION = "HISTORY"
VIEW_ACTION = "VIEW"


def forwards(apps, schema_editor):
    WorkflowPermission = apps.get_model("workflow", "WorkflowPermission")

    view_permissions = WorkflowPermission.objects.filter(
        action=VIEW_ACTION,
    ).values(
        "workflow_id",
        "step_id",
        "transition_id",
        "user_id",
        "role",
        "effect",
    )

    for permission in view_permissions.iterator():
        exists = WorkflowPermission.objects.filter(
            workflow_id=permission["workflow_id"],
            step_id=permission["step_id"],
            transition_id=permission["transition_id"],
            user_id=permission["user_id"],
            role=permission["role"],
            action=HISTORY_ACTION,
            effect=permission["effect"],
        ).exists()

        if exists:
            continue

        WorkflowPermission.objects.create(
            workflow_id=permission["workflow_id"],
            step_id=permission["step_id"],
            transition_id=permission["transition_id"],
            user_id=permission["user_id"],
            role=permission["role"],
            action=HISTORY_ACTION,
            effect=permission["effect"],
        )


def backwards(apps, schema_editor):
    # HISTORY permissions are valid data after the migration. Do not delete
    # them on rollback because that could remove permissions created manually
    # after the migration was applied.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0049_historyconfiguration_historyfield"),
    ]

    operations = [
        migrations.RunPython(
            forwards,
            backwards,
        ),
    ]
