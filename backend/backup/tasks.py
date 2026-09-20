import hashlib
import logging
import shutil
from datetime import timedelta

from celery import shared_task
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
from .services import BackupService, sanitize_message
from .storage import BackupStorageError, LocalBackupStorage, NetworkBackupStorage

logger = logging.getLogger(__name__)


class MigratingRestoreService(RestoreService):
    """Run pending Django migrations after replacing the database dump.

    The dump may have been created before the current application schema.
    pg_restore restores that historical schema, so migrations must run
    before post-restore model operations such as recreating the safety-backup
    row.
    """

    def _run_pg_restore(self, dump_path):
        super()._run_pg_restore(dump_path)
        connection.close()
        try:
            call_command("migrate", interactive=False, verbosity=0)
        except Exception as exc:
            raise RestoreError(
                "اجرای migrationهای Django پس از بازیابی پایگاه داده ناموفق بود: "
                + str(exc)
            ) from exc

        self._normalize_restored_backup_states()

    def _normalize_restored_backup_states(self):
        """Mark RUNNING backups restored from another system as failed."""
        now = timezone.now()

        updated = Backup.objects.filter(
            status=Backup.Status.RUNNING,
        ).update(
            status=Backup.Status.FAILED,
            completed_at=now,
            error_message=(
                "این پشتیبان‌گیری در سیستم مبدأ در وضعیت RUNNING بوده و "
                "پس از بازیابی، Worker مربوط به آن وجود ندارد."
            ),
            updated_at=now,
        )

        if updated:
            logger.info(
                "Restore #%s: normalized %s stale RUNNING backup(s)",
                self.restore.pk,
                updated,
            )

    def _recreate_safety_backup_row(self):
        super()._recreate_safety_backup_row()
        if not self._safety_snapshot:
            return
        if not Backup.objects.filter(
            filename=self._safety_snapshot["filename"],
            storage_path=self._safety_snapshot["storage_path"],
        ).exists():
            raise RestoreError(
                "رکورد پشتیبان امنیتی پس از بازیابی قابل بازسازی نبود."
            )


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


@shared_task
def run_restore(restore_id):
    """Execute the restore pipeline for the given Restore record."""
    try:
        restore = Restore.objects.get(pk=restore_id)
    except Restore.DoesNotExist:
        logger.warning(
            "run_restore called for missing restore #%s",
            restore_id,
        )
        return {"status": "missing", "restore_id": restore_id}

    return MigratingRestoreService(restore).run()
