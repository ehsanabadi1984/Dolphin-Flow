# Preserve workflow-entry and assignment history independently from step executions.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _user_label(user):
    if user is None:
        return ""
    full_name = " ".join(
        part for part in (user.first_name, user.last_name) if part
    ).strip()
    return full_name or user.get_username()


def _iso(value):
    return value.isoformat() if value else None


def preserve_existing_history(apps, schema_editor):
    AssignmentHistory = apps.get_model("workflow", "WorkflowStepAssignmentHistory")
    StepExecution = apps.get_model("workflow", "WorkflowStepExecution")
    InstanceEvent = apps.get_model("workflow", "WorkflowInstanceEvent")

    for assignment in AssignmentHistory.objects.select_related("step_execution").iterator():
        execution = assignment.step_execution
        assignment.workflow_step_id = execution.workflow_step_id
        assignment.instance_id = execution.instance_id
        assignment.save(update_fields=["workflow_step", "instance"])

    for execution in (
        StepExecution.objects
        .filter(instance_id__isnull=False)
        .select_related("entered_by", "performed_by", "assigned_to", "completed_by")
        .iterator()
    ):
        data = execution.data if isinstance(execution.data, dict) else {}
        override = data.get("override")
        has_override = isinstance(override, dict) or AssignmentHistory.objects.filter(
            step_execution_id=execution.pk,
            source="OVERRIDE",
        ).exists()
        actor = execution.entered_by or execution.performed_by
        details = {
            "execution_id": execution.pk,
            "actor_source": (
                "entered_by" if execution.entered_by_id
                else "performed_by_legacy" if execution.performed_by_id
                else "unknown"
            ),
            "notes": execution.notes or "",
            "is_submitted": execution.is_submitted,
            "submitted_at": _iso(execution.submitted_at),
            "assigned_at": _iso(execution.assigned_at),
            "completed_by_id": execution.completed_by_id,
            "completed_by_label": _user_label(execution.completed_by),
            "sla_started_at": _iso(execution.sla_started_at),
            "sla_due_at": _iso(execution.sla_due_at),
            "sla_warning_at": _iso(execution.sla_warning_at),
            "sla_warning_sent_at": _iso(execution.sla_warning_sent_at),
            "sla_completed_at": _iso(execution.sla_completed_at),
            "sla_breached_at": _iso(execution.sla_breached_at),
            "history": data.get("history"),
            "override": override if isinstance(override, dict) else {},
        }
        InstanceEvent.objects.get_or_create(
            instance_id=execution.instance_id,
            execution_id=execution.pk,
            defaults={
                "workflow_step_id": execution.workflow_step_id,
                "event_type": "OVERRIDE" if has_override else "STEP_ENTERED",
                "actor_id": actor.pk if actor else None,
                "actor_label": _user_label(actor),
                "assigned_to_id": execution.assigned_to_id,
                "assigned_to_label": _user_label(execution.assigned_to),
                "occurred_at": execution.performed_at,
                "details": details,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0093_workflowstepassignmenthistory_rejection_source"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowstepassignmenthistory",
            name="instance",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assignment_history",
                to="workflow.workflowinstance",
                verbose_name="نمونه فرآیند",
            ),
        ),
        migrations.AddField(
            model_name="workflowstepassignmenthistory",
            name="workflow_step",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assignment_history",
                to="workflow.workflowstep",
                verbose_name="مرحله",
            ),
        ),
        migrations.AlterField(
            model_name="workflowstepassignmenthistory",
            name="step_execution",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assignment_history",
                to="workflow.workflowstepexecution",
                verbose_name="نوبت اجرا (در صورت وجود)",
            ),
        ),
        migrations.CreateModel(
            name="WorkflowInstanceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("STEP_ENTERED", "ورود به مرحله"), ("OVERRIDE", "اصلاح مسیر توسط مدیر")], max_length=20, verbose_name="نوع رویداد")),
                ("actor_label", models.CharField(blank=True, max_length=255, verbose_name="نام ثبت‌شده عامل در زمان رویداد")),
                ("assigned_to_label", models.CharField(blank=True, max_length=255, verbose_name="نام ثبت‌شده مسئول در زمان ورود")),
                ("execution_id", models.PositiveBigIntegerField(blank=True, null=True, verbose_name="شناسه تاریخی نوبت اجرا")),
                ("occurred_at", models.DateTimeField(db_index=True, verbose_name="زمان وقوع رویداد")),
                ("details", models.JSONField(blank=True, default=dict, verbose_name="جزئیات و snapshot رویداد")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="workflow_instance_events", to=settings.AUTH_USER_MODEL, verbose_name="عامل ثبت رویداد")),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="workflow_instance_event_assignments", to=settings.AUTH_USER_MODEL, verbose_name="مسئول ثبت‌شده در زمان ورود")),
                ("instance", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="audit_events", to="workflow.workflowinstance", verbose_name="نمونه فرآیند")),
                ("workflow_step", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="instance_events", to="workflow.workflowstep", verbose_name="مرحله")),
            ],
            options={
                "verbose_name": "رویداد فرآیند",
                "verbose_name_plural": "رویدادهای فرآیند",
                "ordering": ["occurred_at", "pk"],
            },
        ),
        migrations.RunPython(preserve_existing_history, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="workflowstepassignmenthistory",
            name="workflow_step",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assignment_history",
                to="workflow.workflowstep",
                verbose_name="مرحله",
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowinstanceevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(("execution_id__isnull", False)),
                fields=("instance", "execution_id"),
                name="uniq_wf_event_instance_execution",
            ),
        ),
    ]
