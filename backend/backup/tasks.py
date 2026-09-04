import logging

from celery import shared_task

from .models import Backup
from .services import BackupService

logger = logging.getLogger(__name__)


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