"""Perform the destructive staged restore cutover after explicit quiescence checks."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from backup.models import Backup, Restore
from backup.restore_journal import RestoreJournal
from backup.restore_lock import RestoreOperationLock
from backup.restore_maintenance import RestoreMaintenanceError, read_maintenance_state
from backup.restore_quiescence import (
    assert_database_quiescent,
    assert_systemd_services_stopped,
    close_restore_worker_connection,
)
from backup.restore_services import RestoreError
from backup.staged_restore_cutover import StagedRestoreCutover


def _finalize_restore_audit(journal):
    """Recreate durable safety-backup and restore audit rows after DB promotion."""
    payload = journal.read()
    restore_data = payload.get("restore") or {}
    safety = payload.get("database", {}).get("safety_backup") or {}

    if safety.get("filename") and safety.get("storage_path"):
        exists = Backup.objects.filter(
            filename=safety["filename"],
            storage_path=safety["storage_path"],
        ).exists()
        if not exists:
            snapshot = dict(safety)
            for field in ("started_at", "completed_at"):
                value = snapshot.get(field)
                if isinstance(value, str) and value:
                    snapshot[field] = parse_datetime(value)
            Backup.objects.create(**snapshot)

    archive_filename = restore_data.get("archive_filename", "")
    started_at_raw = restore_data.get("started_at", "")
    started_at = parse_datetime(started_at_raw) if started_at_raw else None
    requested_by_username = restore_data.get("requested_by_username", "")

    existing = Restore.objects.filter(
        archive_filename=archive_filename,
        started_at=started_at,
        requested_by_username=requested_by_username,
        status=Restore.Status.SUCCESS,
    ).exists()
    if not existing:
        Restore.objects.create(
            archive_filename=archive_filename,
            product_version=restore_data.get("product_version", ""),
            database_engine=restore_data.get("database_engine", ""),
            database_backup_format=restore_data.get("database_backup_format", ""),
            includes_media=restore_data.get("includes_media", False),
            started_at=started_at,
            completed_at=timezone.now(),
            requested_by_username=requested_by_username,
            pre_restore_backup_filename=restore_data.get(
                "pre_restore_backup_filename", ""
            ),
            status=Restore.Status.SUCCESS,
        )


class Command(BaseCommand):
    help = (
        "اجرای Cutover دیتابیس و رسانه برای Restore آماده‌شده؛ "
        "نیازمند Maintenance متناظر و توقف تأییدشده همه سرویس‌ها."
    )

    def add_arguments(self, parser):
        parser.add_argument("--operation-id", required=True)
        parser.add_argument(
            "--service-unit",
            action="append",
            dest="service_units",
            required=True,
            help="نام هر واحد systemd؛ برای هر سرویس یک بار تکرار شود.",
        )

    def handle(self, *args, **options):
        operation_id = options["operation_id"]
        service_units = options["service_units"]
        journal_root = getattr(
            settings,
            "RESTORE_JOURNAL_ROOT",
            Path(settings.BACKUP_ROOT) / ".restore-journal",
        )

        try:
            journal = RestoreJournal(operation_id, root=journal_root)
            state = read_maintenance_state()
            if state is None:
                raise RestoreError("Maintenance فعال نیست؛ Cutover مجاز نیست.")
            if state.get("operation_id") != operation_id:
                raise RestoreError(
                    "شناسه عملیات با نشانگر Maintenance مطابقت ندارد."
                )

            with RestoreOperationLock(
                root=journal_root,
                operation_id=operation_id,
            ):
                payload = journal.read()
                if payload["phase"] not in {"PREPARED", "COMPLETED"}:
                    raise RestoreError(
                        "Journal در وضعیت قابل Cutover یا نهایی‌سازی نیست: "
                        + payload["phase"]
                    )

                services = assert_systemd_services_stopped(service_units)
                close_restore_worker_connection()
                database = assert_database_quiescent()

                if payload["phase"] == "PREPARED":
                    result = StagedRestoreCutover(journal).run()
                    if result.get("status") != "COMPLETED":
                        raise RestoreError("Cutover به وضعیت COMPLETED نرسید.")
                else:
                    result = {
                        "status": "COMPLETED",
                        "operation_id": operation_id,
                        "already_cut_over": True,
                    }

                # If the process crashed after journal completion but before
                # audit recreation, rerunning this command safely retries it.
                close_restore_worker_connection()
                _finalize_restore_audit(journal)

        except (RestoreError, RestoreMaintenanceError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Cutover complete: {operation_id} | Journal: COMPLETED"
        ))
        self.stdout.write(
            f"Verified services: {len(services)} | "
            f"Database sessions: {database['active_sessions']}"
        )
        self.stdout.write(
            "Maintenance همچنان فعال است؛ پس از بررسی سلامت سیستم و راه‌اندازی "
            "کنترل‌شده سرویس‌ها، آن را جداگانه غیرفعال کنید."
        )
