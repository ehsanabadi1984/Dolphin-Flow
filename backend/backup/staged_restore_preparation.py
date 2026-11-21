"""Prepare a restore in isolated staging resources; never perform cutover here."""

import logging
from pathlib import Path

from django.conf import settings

from .restore_journal import RestoreJournal
from .restore_lock import RestoreOperationLock
from .restore_recovery import inspect_restore_journals
from .restore_services import RestoreError, RestoreService
from .staged_media_restore import StagedMediaRestore
from .staged_restore import StagedDatabaseRestore

logger = logging.getLogger(__name__)


class StagedRestorePreparationService(RestoreService):
    """Validate and prepare a restore without changing the live DB or MEDIA_ROOT.

    A successful run leaves a validated staging database, an optional staged
    media directory, and a PREPARED journal for a later, separately controlled
    cutover. This class intentionally has no database/media swap operation.
    """

    def __init__(self, restore, storage=None, archive_path=None):
        super().__init__(restore, storage=storage, archive_path=archive_path)
        self.database_stage = None
        self.media_stage = None
        self.journal = None
        self._prepared = False

    def run(self):
        if self.restore.status != self.restore.Status.QUEUED:
            return {"status": self.restore.status, "restore_id": self.restore.pk}

        lock = RestoreOperationLock(restore_id=self.restore.pk)
        try:
            lock.acquire()
        except RestoreError as exc:
            # A concurrent restore owns the lock. Leave this request queued.
            logger.info("Restore #%s preparation deferred: %s", self.restore.pk, exc)
            return {"status": "busy", "restore_id": self.restore.pk}

        try:
            inventory = inspect_restore_journals()
            if any(item.get("recovery_required") for item in inventory):
                raise RestoreError(
                    "یک عملیات Restore قبلی نیازمند بررسی/بازیابی است؛ "
                    "تا تعیین تکلیف آن عملیات جدید آغاز نمی‌شود."
                )

            if not self._claim_slot():
                self.restore.refresh_from_db()
                return {
                    "status": self.restore.status,
                    "restore_id": self.restore.pk,
                }

            archive = self._resolve_archive_path()
            self._verify_checksum(archive)
            self._manifest = self._validate_archive(archive)

            safety_backup = self._create_safety_backup(self._manifest)
            self._safety_backup_pk = safety_backup.pk
            self._safety_snapshot = self._capture_backup_state(safety_backup)
            self.restore.pre_restore_backup = safety_backup
            self.restore.pre_restore_backup_filename = safety_backup.filename
            self.restore.save(
                update_fields=[
                    "pre_restore_backup",
                    "pre_restore_backup_filename",
                    "updated_at",
                ]
            )

            dump_path, media_path = self._materialize(archive)
            self._validate_dump_file(dump_path)

            database_config = settings.DATABASES["default"]
            self.database_stage = StagedDatabaseRestore(self.restore.pk)

            journal_safety_snapshot = dict(self._safety_snapshot)
            for field in ("started_at", "completed_at"):
                value = journal_safety_snapshot.get(field)
                if value is not None:
                    journal_safety_snapshot[field] = value.isoformat()

            media_info = {
                "included": bool(self._manifest["includes_media"]),
                "media_root": str(Path(settings.MEDIA_ROOT).absolute()),
            }
            # Persist the intended staging database before creating it. If the
            # worker exits mid-prepare, recovery inspection can still identify
            # the resource that may have been left behind.
            self.journal = RestoreJournal.new(
                restore_id=self.restore.pk,
                database={
                    "original_name": database_config["NAME"],
                    "staging_name": self.database_stage.database_name,
                    "prepared": False,
                    "safety_backup": journal_safety_snapshot,
                },
                media=media_info,
                restore={
                    "archive_filename": self.restore.archive_filename or "",
                    "product_version": self.restore.product_version or "",
                    "database_engine": self.restore.database_engine or "",
                    "database_backup_format": self.restore.database_backup_format or "",
                    "includes_media": bool(self.restore.includes_media),
                    "started_at": (
                        self.restore.started_at.isoformat()
                        if self.restore.started_at else ""
                    ),
                    "requested_by_username": self.restore.requested_by_username or "",
                    "pre_restore_backup_filename": (
                        self.restore.pre_restore_backup_filename or ""
                    ),
                },
            )

            self.database_stage.prepare(dump_path)

            if self._manifest["includes_media"]:
                def record_media_stage_path(stage_path):
                    media_info.update(
                        {
                            "staging_path": str(stage_path),
                            "stage_created": True,
                        }
                    )
                    # This callback runs before the directory is created and
                    # before archive extraction begins.
                    self.journal.update(media=media_info)

                self.media_stage = StagedMediaRestore(
                    self.restore.pk,
                    on_stage_created=record_media_stage_path,
                )
                self.media_stage.prepare(media_path)
                media_info.update(
                    {
                        "staging_path": str(self.media_stage.stage_dir),
                        "file_count": self.media_stage.file_count,
                        "total_bytes": self.media_stage.total_bytes,
                        "prepared": True,
                    }
                )

            self.journal.update(
                database={"prepared": True},
                media=media_info,
            )
            self._prepared = True
            logger.info(
                "Restore #%s prepared in staging database %s; no cutover performed",
                self.restore.pk,
                self.database_stage.database_name,
            )
            return {
                "status": "PREPARED",
                "restore_id": self.restore.pk,
                "operation_id": self.journal.operation_id,
                "staging_database": self.database_stage.database_name,
            }

        except Exception as exc:
            message = str(exc) if isinstance(exc, RestoreError) else (
                "آماده‌سازی Restore ناموفق بود: " + str(exc)
            )
            logger.exception("Restore #%s staging preparation failed", self.restore.pk)
            self._cleanup_staging_after_failure(message)
            self._mark_terminal(self.restore.Status.FAILED, message)
            return {"status": self.restore.status, "restore_id": self.restore.pk}

        finally:
            if self.database_stage is not None:
                self.database_stage.close()
            self._cleanup_temp_dir()
            lock.release()

    def _cleanup_staging_after_failure(self, message):
        cleanup_errors = []

        if self.media_stage is not None:
            try:
                self.media_stage.cleanup()
            except Exception as exc:
                cleanup_errors.append(str(exc))

        if self.database_stage is not None:
            try:
                self.database_stage.close()
                self.database_stage.drop_database()
            except Exception as exc:
                cleanup_errors.append(str(exc))

        if self.journal is not None:
            try:
                self.journal.update(
                    phase="ROLLBACK_REQUIRED",
                    error=message + ("; " + "; ".join(cleanup_errors) if cleanup_errors else ""),
                )
                if not cleanup_errors:
                    self.journal.update(phase="ROLLED_BACK", error=message)
            except Exception:
                logger.exception(
                    "Restore #%s: could not finalize preparation journal",
                    self.restore.pk,
                )

        if cleanup_errors:
            logger.error(
                "Restore #%s staging cleanup needs recovery: %s",
                self.restore.pk,
                "; ".join(cleanup_errors),
            )
