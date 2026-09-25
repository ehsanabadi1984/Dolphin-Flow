from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

from workflow.form_file_models import FormFile
from workflow.history_models import HistoryConfiguration, HistoryField
from workflow.models import (
    BusinessCalendar,
    CalendarException,
    CalendarExceptionInterval,
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    Notification,
    RepeatableGroupAccess,
    RepeatableRow,
    RepeatableRowValue,
    WorkflowInstance,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
)


DELETE_MODELS = (
    ("Notification", Notification),
    ("FormFile", FormFile),
    ("RepeatableRowValue", RepeatableRowValue),
    ("RepeatableRow", RepeatableRow),
    ("InstanceDevice", InstanceDevice),
    ("FormData", FormData),
    ("WorkflowTransitionExecution", WorkflowTransitionExecution),
    ("WorkflowStepExecution", WorkflowStepExecution),
    ("WorkflowInstance", WorkflowInstance),
    ("HistoryField", HistoryField),
    ("HistoryConfiguration", HistoryConfiguration),
    ("FieldAccess", FieldAccess),
    ("RepeatableGroupAccess", RepeatableGroupAccess),
    ("FormField", FormField),
    ("FormRepeatableGroup", FormRepeatableGroup),
    ("FormSection", FormSection),
    ("FormDefinition", FormDefinition),
)


class Command(BaseCommand):
    help = (
        "Reset workflow form/runtime data while preserving users, "
        "workflow definitions, permissions, device master data, "
        "data sources, SLA and calendar configuration."
    )

    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report what would be deleted; make no changes.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Confirm the destructive operation.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        confirmed = options["yes"]

        self._write_scope()

        if dry_run:
            self._report_counts()
            self.stdout.write(self.style.WARNING("DRY RUN: no data was changed."))
            return

        if not confirmed:
            raise CommandError(
                "This operation deletes workflow forms and runtime data. "
                "Re-run with --yes, or use --dry-run first."
            )

        with transaction.atomic():
            self._delete_runtime_data()
            self._delete_form_configuration()

        self.stdout.write(self.style.SUCCESS("Workflow data reset completed."))
        self._report_counts()

    def _write_scope(self):
        self.stdout.write("Preserved:")
        self.stdout.write(
            "  users, workflows, memberships, steps, transitions, "
            "workflow permissions"
        )
        self.stdout.write(
            "  device type/model/device/identifier master data"
        )
        self.stdout.write(
            "  static choices, lookup lists/items, other data sources"
        )
        self.stdout.write(
            "  SLA and business-calendar configuration"
        )
        self.stdout.write("Deleted:")
        self.stdout.write(
            "  form definitions/sections/fields/repeatable groups/access rules"
        )
        self.stdout.write(
            "  history configuration, runtime instances, executions, "
            "form data, repeatable rows and FILE sidecars"
        )

    def _report_counts(self):
        for label, model in DELETE_MODELS:
            self.stdout.write(f"  {label}: {model.objects.count()}")

    def _delete_runtime_data(self):
        # Notifications must disappear before the execution/instance rows
        # they reference because their FKs use PROTECT.
        Notification.objects.all().delete()

        self._delete_form_files()

        RepeatableRowValue.objects.all().delete()
        self._delete_repeatable_rows()
        InstanceDevice.objects.all().delete()
        FormData.objects.all().delete()

        WorkflowTransitionExecution.objects.all().delete()
        WorkflowStepExecution.objects.all().delete()
        WorkflowInstance.objects.all().delete()

    def _delete_form_files(self):
        files = list(
            FormFile.objects.exclude(file="").values_list("file", flat=True)
        )
        FormFile.objects.all().delete()

        for file_name in files:
            if not file_name:
                continue
            storage = FormFile._meta.get_field("file").storage
            transaction.on_commit(
                lambda file_name=file_name, storage=storage: storage.delete(
                    file_name
                )
            )

    def _delete_repeatable_rows(self):
        # parent_row is PROTECT, so children have to be removed first.
        while True:
            deleted = 0
            rows = list(
                RepeatableRow.objects.filter(child_rows__isnull=True)
                .values_list("pk", flat=True)
                .distinct()
            )
            if not rows:
                break

            deleted += RepeatableRow.objects.filter(pk__in=rows).delete()[0]
            if deleted == 0:
                break

        remaining = RepeatableRow.objects.count()
        if remaining:
            raise CommandError(
                "Could not delete all RepeatableRow records. "
                f"{remaining} row(s) remain; a parent-row dependency or cycle "
                "may exist."
            )

    def _delete_form_configuration(self):
        # History and access rules reference fields/groups with PROTECT.
        HistoryField.objects.all().delete()
        HistoryConfiguration.objects.all().delete()
        FieldAccess.objects.all().delete()
        RepeatableGroupAccess.objects.all().delete()

        self._delete_form_fields()
        self._delete_repeatable_groups()

        FormSection.objects.all().delete()
        FormDefinition.objects.all().delete()

    def _delete_form_fields(self):
        # choice_parent_field is a self-referencing PROTECT FK.
        while True:
            leaf_ids = list(
                FormField.objects.filter(dependent_choice_fields__isnull=True)
                .values_list("pk", flat=True)
                .distinct()
            )
            if not leaf_ids:
                break

            deleted = FormField.objects.filter(pk__in=leaf_ids).delete()[0]
            if deleted == 0:
                break

        remaining = FormField.objects.count()
        if remaining:
            raise CommandError(
                "Could not delete all FormField records. "
                f"{remaining} field(s) remain; a dependency cycle may exist."
            )

    def _delete_repeatable_groups(self):
        # parent_group is a self-referencing PROTECT FK.
        while True:
            leaf_ids = list(
                FormRepeatableGroup.objects.filter(child_groups__isnull=True)
                .values_list("pk", flat=True)
                .distinct()
            )
            if not leaf_ids:
                break

            deleted = FormRepeatableGroup.objects.filter(pk__in=leaf_ids).delete()[0]
            if deleted == 0:
                break

        remaining = FormRepeatableGroup.objects.count()
        if remaining:
            raise CommandError(
                "Could not delete all FormRepeatableGroup records. "
                f"{remaining} group(s) remain; a dependency cycle may exist."
            )
