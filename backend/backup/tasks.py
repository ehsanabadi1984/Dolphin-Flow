import logging

from celery import shared_task
from django.core.management import call_command
from django.db import connection

from .models import Backup, Restore
from .restore_services import RestoreError, RestoreService
from .services import BackupService

logger = logging.getLogger(__name__)


class MigratingRestoreService(RestoreService):
    """Run pending Django migrations after replacing the database dump.

    The dump may have been created before the current application schema.
    ``pg_restore`` restores that historical schema, so migrations must run
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

    def _recreate_safety_backup_row(self):
        super()._recreate_safety_backup_row()
        if not self._safety_snapshot:
            return
        if not Backup.objects.filter(
            pk=self._safety_backup_pk,
            filename=self._safety_snapshot["filename"],
        ).exists():
            raise RestoreError(
                "رکورد پشتیبان امنیتی پس از بازیابی قابل بازسازی نبود."
            )


@shared_task
def run_backup(backup_id):
    """Execute the backup pipeline for the given ``Backup`` record.

    Returns a small status dict for observability. All heavy work (pg_dump,
    media archiving, validation) happens here, never in the HTTP request.
    """
    try:
        backup = Backup.objects.get(pk=backup_id)
    except Backup.DoesNotExist:
        logger.warning("run_backup called for missing backup #%s", backup_id)
        return {"status": "missing", "backup_id": backup_id}

    return BackupService(backup).run()


@shared_task
def run_restore(restore_id):
    """Execute the restore pipeline for the given ``Restore`` record.

    Returns a small status dict for observability. The destructive steps
    (pg_restore, migrations, media extraction) happen here, never in the HTTP request.
    """
    try:
        restore = Restore.objects.get(pk=restore_id)
    except Restore.DoesNotExist:
        logger.warning(
            "run_restore called for missing restore #%s",
            restore_id,
        )
        return {"status": "missing", "restore_id": restore_id}

    return MigratingRestoreService(restore).run()
