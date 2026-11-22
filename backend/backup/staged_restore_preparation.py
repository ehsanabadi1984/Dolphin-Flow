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


def recover_interrupted_restore_preparation(restore):
    """Reconcile a worker crash during staging without touching live resources.

    Fully prepared journals are handed to the cutover worker. Incomplete
    preparation journals are cleaned only when their generated DB/media paths
    can be proven to belong to this Restore; ambiguous resources are preserved.
    """
    root = getattr(
        settings,
        "RESTORE_JOURNAL_ROOT",
        Path(settings.BACKUP_ROOT) / ".restore-journal",
    )
    matches = [
        item for item in inspect_restore_journals(root=root)
        if item.get("restore_id") == restore.pk
    ]
    if not matches:
        restore.__class__.objects.filter(
            pk=restore.pk,
            status=restore.Status.RESTORING,
        ).update(
            status=restore.Status.QUEUED,
            started_at=None,
            error_message="آماده‌سازی قبلی پیش از ایجاد Journal متوقف شد؛ تلاش مجدد آغاز می‌شود.",
        )
        return {"status": "RETRY_PREPARATION", "restore_id": restore.pk}

    if len(matches) != 1 or matches[0].get("status") == "INVALID":
        raise RestoreError(
            "وضعیت Journal آماده‌سازی مبهم است؛ منابع موقت برای جلوگیری از حذف اشتباه حفظ شدند."
        )

    item = matches[0]
    journal = RestoreJournal(item["operation_id"], root=root)
    payload = journal.read()
    phase = payload["phase"]
    database = payload["database"]
    media = payload["media"]
    fully_prepared = (
        phase == "PREPARED"
        and database.get("prepared") is True
        and (not media.get("included") or media.get("prepared") is True)
    )
    orchestrator = payload.get("restore", {}).get("orchestrator")

    if fully_prepared:
        restore.__class__.objects.filter(
            pk=restore.pk,
            status=restore.Status.RESTORING,
        ).update(status=restore.Status.PREPARED, error_message="")
        return {
            "status": "PREPARED",
            "restore_id": restore.pk,
            "operation_id": journal.operation_id,
        }

    if orchestrator:
        return {
            "status": "CUTOVER_PENDING",
            "restore_id": restore.pk,
            "operation_id": journal.operation_id,
        }

    if phase == "ROLLED_BACK":
        restore.__class__.objects.filter(
            pk=restore.pk,
            status=restore.Status.RESTORING,
        ).update(
            status=restore.Status.QUEUED,
            started_at=None,
            error_message="آماده‌سازی نیمه‌تمام پاک‌سازی شد؛ تلاش مجدد آغاز می‌شود.",
        )
        return {"status": "RETRY_PREPARATION", "restore_id": restore.pk}

    if phase not in {"PREPARED", "ROLLBACK_REQUIRED"}:
        raise RestoreError(
            f"مرحله Journal برای بازیابی آماده‌سازی معتبر نیست: {phase}."
        )

    journal.update(
        phase="ROLLBACK_REQUIRED",
        error="Interrupted staging preparation cleanup.",
    )

    staging_name = database.get("staging_name")
    expected_prefix = f"dolphinflow_restore_{restore.pk}_"
    if (
        not isinstance(staging_name, str)
        or not staging_name.startswith(expected_prefix)
        or len(staging_name) != len(expected_prefix) + 12
        or any(char not in "0123456789abcdef" for char in staging_name[len(expected_prefix):])
        or staging_name == settings.DATABASES["default"]["NAME"]
    ):
        raise RestoreError("نام دیتابیس staging برای پاک‌سازی امن معتبر نیست.")

    staged_database = StagedDatabaseRestore(restore.pk)
    staged_database.database_name = staging_name
    staged_database._created = True
    staged_database.drop_database()

    if media.get("included") and media.get("staging_path"):
        media_root = Path(media.get("media_root") or settings.MEDIA_ROOT).absolute()
        stage_path = Path(media["staging_path"]).absolute()
        expected_media_prefix = f".{media_root.name}.restore-{restore.pk}-"
        if (
            media_root.resolve() != Path(settings.MEDIA_ROOT).absolute().resolve()
            or stage_path.parent.resolve() != media_root.parent.resolve()
            or not stage_path.name.startswith(expected_media_prefix)
            or len(stage_path.name) != len(expected_media_prefix) + 16
            or any(char not in "0123456789abcdef" for char in stage_path.name[len(expected_media_prefix):])
            or stage_path.is_symlink()
        ):
            raise RestoreError("مسیر staging رسانه برای پاک‌سازی امن معتبر نیست.")
        staged_media = StagedMediaRestore(restore.pk, media_root=media_root)
        staged_media.stage_dir = stage_path
        staged_media._stage_created = True
        staged_media.cleanup()

    journal.update(phase="ROLLED_BACK", error="Interrupted staging resources cleaned safely.")
    restore.__class__.objects.filter(
        pk=restore.pk,
        status=restore.Status.RESTORING,
    ).update(
        status=restore.Status.QUEUED,
        started_at=None,
        error_message="آماده‌سازی نیمه‌تمام پاک‌سازی شد؛ تلاش مجدد آغاز می‌شود.",
    )
    return {"status": "RETRY_PREPARATION", "restore_id": restore.pk}


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
            if any(item.get("blocks_new_restore", True) for item in inventory):
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
            self.restore.status = self.restore.Status.PREPARED
            self.restore.save(update_fields=["status", "updated_at"])
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
