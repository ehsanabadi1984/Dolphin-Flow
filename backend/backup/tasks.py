import hashlib
import logging
import shutil
from datetime import timedelta
from pathlib import Path

from celery import Task, shared_task
from django.core.management import call_command
from django.db import connection, transaction
from django.utils import timezone

from .models import (
    Backup,
    BackupRetentionPolicy,
    BackupSchedule,
    Restore,
    generate_backup_filename,
)
from .restore_services import RestoreError, RestoreService
from .staged_restore_preparation import StagedRestorePreparationService
from .restore_journal import RestoreJournal
from .restore_maintenance import read_maintenance_state
from .restore_recovery import inspect_restore_journals
from .services import BackupService, sanitize_message
from .storage import BackupStorageError, LocalBackupStorage, NetworkBackupStorage

logger = logging.getLogger(__name__)


class RestoreCutoverTask(Task):
    """Dedicated recovery task must remain runnable while maintenance is active.

    Normal application tasks use RestoreMaintenanceAwareTask and are rejected
    during maintenance. The isolated restore queue is the sole intentional
    exception so it can resume the journal after a worker restart.
    """

    abstract = True


class MigratingRestoreService(RestoreService):
    """Backward-compatible entry point for older callers.

    Historical restores used RestoreService._run_pg_restore(), which invoked
    pg_restore against the live database with --clean/--if-exists. That can
    fail when dependent foreign keys reference a primary-key index being
    dropped (and is unsafe for a live application database).

    All restore entry points must now use isolated staging preparation. Keep
    this class as a compatibility shim so any older internal caller is routed
    through the same safe pipeline instead of silently reviving the legacy
    in-place restore implementation.
    """

    def run(self):
        return StagedRestorePreparationService(self.restore).run()


@shared_task
def process_backup_schedules():
    """Create due Backup rows and dispatch their asynchronous execution."""
    now = timezone.now()
    queued = []

    with transaction.atomic():
        schedules = list(
            BackupSchedule.objects.select_for_update()
            .filter(
                enabled=True,
                next_run_at__isnull=False,
                next_run_at__lte=now,
            )
            .order_by("next_run_at", "pk")[:1]
        )

        for schedule in schedules:
            backup = Backup.objects.create(
                filename=generate_backup_filename(),
                includes_media=schedule.include_media,
                schedule=schedule,
                destination=schedule.destination,
                network_storage=schedule.network_storage if schedule.destination in (
                    Backup.Destination.NETWORK,
                    Backup.Destination.BOTH,
                ) else None,
                network_status=(
                    Backup.NetworkStatus.PENDING
                    if schedule.destination in (
                        Backup.Destination.NETWORK,
                        Backup.Destination.BOTH,
                    )
                    else Backup.NetworkStatus.NOT_REQUESTED
                ),
            )

            schedule.last_run_at = now
            schedule.last_status = Backup.Status.QUEUED
            schedule.last_error = ""

            if schedule.frequency == BackupSchedule.Frequency.ONCE:
                schedule.enabled = False
                schedule.next_run_at = None
            else:
                schedule.next_run_at = schedule.calculate_next_run(now)

            schedule.save(
                update_fields=[
                    "enabled",
                    "last_run_at",
                    "last_status",
                    "last_error",
                    "next_run_at",
                    "updated_at",
                ]
            )
            queued.append(backup.pk)

    for backup_id in queued:
        run_backup.delay(backup_id)

    return {"status": "ok", "queued_backup_ids": queued}


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@shared_task
def replicate_backup_to_network(backup_id):
    """Copy a completed local archive to the mounted network destination.

    Network replication is independent from the local backup result:
    a local backup remains SUCCESS even if the network copy fails.
    """
    try:
        backup = Backup.objects.get(pk=backup_id)
    except Backup.DoesNotExist:
        logger.warning(
            "replicate_backup_to_network called for missing backup #%s",
            backup_id,
        )
        return {"status": "missing", "backup_id": backup_id}

    if backup.destination not in (
        Backup.Destination.NETWORK,
        Backup.Destination.BOTH,
    ):
        return {"status": "not_requested", "backup_id": backup_id}

    if backup.status != Backup.Status.SUCCESS:
        return {"status": "not_ready", "backup_id": backup_id}

    local_storage = LocalBackupStorage()
    try:
        source = local_storage.path_for(backup.storage_path)
        if not source.is_file():
            raise BackupStorageError("فایل پشتیبان محلی برای انتقال شبکه یافت نشد.")

        if not backup.network_storage_id:
            raise BackupStorageError("برای این پشتیبان مقصد شبکه‌ای ثبت نشده است.")

        network_storage = NetworkBackupStorage(backup.network_storage)
        source_checksum = backup.checksum or _sha256(source)
        remote_path, remote_size = network_storage.copy_from_local(
            source,
            backup.filename,
        )

        backup.network_status = Backup.NetworkStatus.SUCCESS
        backup.network_storage_path = remote_path
        backup.network_size = remote_size
        backup.network_checksum = source_checksum
        backup.network_copied_at = timezone.now()
        backup.network_error = ""
        backup.save(
            update_fields=[
                "network_status",
                "network_storage_path",
                "network_size",
                "network_checksum",
                "network_copied_at",
                "network_error",
                "updated_at",
            ]
        )

        return {"status": "success", "backup_id": backup_id}

    except Exception as exc:
        logger.exception("Network replication failed for backup #%s", backup_id)
        backup.network_status = Backup.NetworkStatus.FAILED
        backup.network_error = sanitize_message(str(exc))[:1000]
        backup.save(
            update_fields=[
                "network_status",
                "network_error",
                "updated_at",
            ]
        )
        return {"status": "failed", "backup_id": backup_id}


@shared_task
def run_backup(backup_id):
    """Execute the backup pipeline for the given Backup record."""
    try:
        backup = Backup.objects.get(pk=backup_id)
    except Backup.DoesNotExist:
        logger.warning("run_backup called for missing backup #%s", backup_id)
        return {"status": "missing", "backup_id": backup_id}

    result = BackupService(backup).run()

    backup.refresh_from_db()
    if backup.schedule_id:
        schedule = backup.schedule
        schedule.last_status = backup.status
        schedule.last_error = backup.error_message
        schedule.save(
            update_fields=["last_status", "last_error", "updated_at"]
        )

    if (
        backup.status == Backup.Status.SUCCESS
        and backup.destination == Backup.Destination.BOTH
    ):
        replicate_backup_to_network.delay(backup.pk)

    return result



@shared_task
def run_backup_retention():
    """Apply the global retention policy to eligible successful backups."""
    policy = BackupRetentionPolicy.get_solo()

    if not policy.enabled:
        return {"status": "disabled", "deleted_backup_ids": []}

    successful = Backup.objects.filter(
        status=Backup.Status.SUCCESS,
        is_pre_restore_backup=False,
    ).order_by("-completed_at", "-created_at", "-pk")

    keep_ids = set()
    if policy.keep_last:
        keep_ids.update(
            successful.values_list("pk", flat=True)[:policy.keep_last]
        )

    cutoff = None
    if policy.keep_days:
        cutoff = timezone.now() - timedelta(days=policy.keep_days)

    deleted = []
    skipped = []

    for backup in successful.iterator():
        if backup.pk in keep_ids:
            continue
        if cutoff is not None and (
            (backup.completed_at or backup.created_at) >= cutoff
        ):
            continue

        # BOTH backups are not eligible until the network copy is complete.
        # Otherwise retention could delete the local copy while the network
        # destination is still pending or failed.
        if backup.destination == Backup.Destination.BOTH and (
            backup.network_status != Backup.NetworkStatus.SUCCESS
            or not backup.network_storage_path
        ):
            skipped.append(backup.pk)
            continue

        try:
            if backup.storage_path:
                LocalBackupStorage().delete(backup.storage_path)

            if backup.network_storage_path and backup.network_storage_id:
                NetworkBackupStorage(
                    backup.network_storage
                ).delete(backup.network_storage_path)

            backup_id = backup.pk
            backup.delete()
            deleted.append(backup_id)
        except Exception as exc:
            logger.exception(
                "Retention failed for backup #%s",
                backup.pk,
            )
            skipped.append(backup.pk)

    return {
        "status": "ok",
        "deleted_backup_ids": deleted,
        "skipped_backup_ids": skipped,
    }


def _prepared_journal_for_restore(restore_id):
    matches = [
        item for item in inspect_restore_journals()
        if item.get("restore_id") == restore_id
        and item.get("phase") == "PREPARED"
        and item.get("status") == "PREPARED"
    ]
    if len(matches) != 1:
        raise RestoreError(
            "برای درخواست بازیابی دقیقاً یک Journal آماده و معتبر پیدا نشد."
        )
    return matches[0]


@shared_task(
    bind=True,
    base=RestoreCutoverTask,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=None,
)
def run_restore_cutover(self, restore_id, operation_id):
    """Run destructive cutover on the dedicated restore-only Celery worker.

    This worker is intentionally not among RESTORE_SERVICE_UNITS, so stopping
    the normal web and Celery services cannot terminate the restore itself.
    If the worker is killed, late acknowledgement allows the durable journal
    to drive recovery when the dedicated worker is restarted.
    """
    root = getattr(
        settings,
        "RESTORE_JOURNAL_ROOT",
        Path(settings.BACKUP_ROOT) / ".restore-journal",
    )
    journal = RestoreJournal(operation_id, root=root)
    payload = journal.read()
    if payload["restore_id"] != int(restore_id):
        raise RestoreError("شناسه Restore با Journal عملیات مطابقت ندارد.")

    phase = payload["phase"]
    if phase in {"COMPLETED", "ROLLED_BACK"}:
        return {"status": phase, "restore_id": restore_id, "operation_id": operation_id}

    try:
        # If the worker died after the maintenance gate was raised, recover the
        # interrupted attempt first. PREPARED is then safe to orchestrate again;
        # any phase after cutover began is rolled back by the recovery command.
        if read_maintenance_state() is not None:
            call_command(
                "recover_orchestrated_restore",
                operation_id=operation_id,
                verbosity=0,
            )
            payload = journal.read()
            phase = payload["phase"]
            if phase in {"COMPLETED", "ROLLED_BACK"}:
                return {"status": phase, "restore_id": restore_id, "operation_id": operation_id}

        if phase != "PREPARED":
            raise RestoreError(
                "عملیات Restore در وضعیت قابل شروع مجدد نیست؛ "
                f"مرحله Journal: {phase}."
            )

        service_units = list(getattr(settings, "RESTORE_SERVICE_UNITS", []) or [])
        if not service_units:
            raise RestoreError(
                "سرویس‌های برنامه برای Cutover پیکربندی نشده‌اند؛ "
                "داده اصلی تغییر نکرد."
            )

        Restore.objects.filter(
            pk=restore_id,
            status__in=(Restore.Status.PREPARED, Restore.Status.RESTORING),
        ).update(
            status=Restore.Status.RESTORING,
            error_message="در حال توقف امن سرویس‌ها و آماده‌سازی انتقال نهایی.",
            updated_at=timezone.now(),
        )
        command_options = ["--operation-id", operation_id]
        for unit in service_units:
            command_options.extend(["--service-unit", unit])
        call_command("orchestrate_staged_restore", *command_options, verbosity=1)

        final_phase = journal.read()["phase"]
        return {
            "status": final_phase,
            "restore_id": restore_id,
            "operation_id": operation_id,
        }
    except Exception as exc:
        # A surviving maintenance marker means the live system is deliberately
        # gated. Retry recovery in this dedicated worker instead of leaving the
        # operation stranded. If maintenance was safely removed and no cutover
        # began, report a terminal preflight failure to the admin history.
        if read_maintenance_state() is not None:
            raise self.retry(exc=exc, countdown=30)

        current_phase = journal.read()["phase"]
        if current_phase == "PREPARED":
            Restore.objects.filter(
                pk=restore_id,
                status__in=(Restore.Status.PREPARED, Restore.Status.RESTORING),
            ).update(
                status=Restore.Status.FAILED,
                error_message=("اجرای خودکار Restore ناموفق بود: " + str(exc))[:4000],
                completed_at=timezone.now(),
                updated_at=timezone.now(),
            )
        raise


def run_restore(restore_id):
    """Prepare the archive, then hand cutover to the dedicated worker queue."""
    try:
        restore = Restore.objects.get(pk=restore_id)
    except Restore.DoesNotExist:
        logger.warning(
            "run_restore called for missing restore #%s",
            restore_id,
        )
        return {"status": "missing", "restore_id": restore_id}

    if restore.status == Restore.Status.PREPARED:
        prepared = {
            "status": "PREPARED",
            "restore_id": restore.pk,
            "operation_id": _prepared_journal_for_restore(restore.pk)["operation_id"],
        }
    elif restore.status == Restore.Status.QUEUED:
        prepared = StagedRestorePreparationService(restore).run()
    else:
        return {"status": restore.status, "restore_id": restore_id}

    if prepared.get("status") != "PREPARED" or not prepared.get("operation_id"):
        return prepared

    # Stable task ID makes dispatch idempotent across a worker crash between
    # preparation and publishing the cutover message.
    operation_id = prepared["operation_id"]
    run_restore_cutover.apply_async(
        args=(restore.pk, operation_id),
        queue="restore_cutover",
        task_id=f"restore-cutover-{operation_id}",
    )
    return {
        "status": "CUTOVER_QUEUED",
        "restore_id": restore.pk,
        "operation_id": operation_id,
    }
