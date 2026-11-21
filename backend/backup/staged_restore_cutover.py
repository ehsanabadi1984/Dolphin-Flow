"""Coordinate the staged database and media cutover as one recoverable unit.

This is an orchestration primitive, not the runtime task integration. The
caller must hold RestoreOperationLock and externally quiesce every web/worker
process before invoking run().
"""

from pathlib import Path

from django.conf import settings

from .restore_services import RestoreError
from .staged_database_cutover import StagedDatabaseCutover
from .staged_media_cutover import StagedMediaCutover


class StagedRestoreCutover:
    """Promote prepared resources and roll both back if either promotion fails."""

    def __init__(self, journal, database_settings=None, media_root=None):
        self.journal = journal
        self.database_settings = database_settings
        self.media_root = Path(media_root or settings.MEDIA_ROOT).absolute()

    def _prepared_resources(self):
        payload = self.journal.read()
        if payload["phase"] != "PREPARED":
            raise RestoreError("فقط عملیات آماده‌شده و بدون Cutover قابل اجرا است.")
        database = payload["database"]
        if not database.get("prepared") or not database.get("staging_name"):
            raise RestoreError("دیتابیس staging در Journal آماده اعلام نشده است.")
        media = payload["media"]
        if media.get("included"):
            if not media.get("prepared") or not media.get("staging_path"):
                raise RestoreError("رسانه staging در Journal آماده اعلام نشده است.")
            if Path(media["media_root"]).absolute() != self.media_root:
                raise RestoreError("مسیر MEDIA_ROOT با Journal مطابقت ندارد.")
        return database, media

    def run(self):
        database, media = self._prepared_resources()
        database_cutover = StagedDatabaseCutover(
            database["staging_name"], self.journal, self.database_settings
        )
        media_cutover = None
        if media.get("included"):
            media_cutover = StagedMediaCutover(
                media["staging_path"], self.journal, media_root=self.media_root
            )

        database_swapped = False
        media_attempted = False
        try:
            database_result = database_cutover.swap()
            database_swapped = True

            media_result = None
            if media_cutover is not None:
                media_attempted = True
                media_result = media_cutover.swap()

            self.journal.update(phase="COMPLETED")
            return {
                "status": "COMPLETED",
                "operation_id": self.journal.operation_id,
                "database": database_result,
                "media": media_result,
            }
        except Exception as exc:
            if not database_swapped:
                # DatabaseCutover owns rollback for failures during its own swap.
                raise

            errors = []
            try:
                self.journal.update(
                    phase="ROLLBACK_REQUIRED",
                    error=f"Cutover failed: {exc}",
                )
            except Exception as journal_exc:
                errors.append(f"journal: {journal_exc}")

            if media_attempted:
                try:
                    media_cutover.rollback(update_journal=False)
                except Exception as rollback_exc:
                    errors.append(f"media: {rollback_exc}")

            try:
                database_cutover.rollback(finalize_journal=False)
            except Exception as rollback_exc:
                errors.append(f"database: {rollback_exc}")

            if not errors:
                try:
                    self.journal.update(phase="ROLLED_BACK")
                except Exception as journal_exc:
                    errors.append(f"journal finalization: {journal_exc}")

            if errors:
                try:
                    self.journal.update(
                        phase="ROLLBACK_REQUIRED",
                        error=f"Cutover failed: {exc}; rollback errors: {'; '.join(errors)}",
                    )
                except Exception:
                    pass
                raise RestoreError(
                    "Cutover شکست خورد و بازگشت همه منابع کامل نشد؛ بازیابی دستی لازم است."
                ) from exc
            raise RestoreError(
                "Cutover شکست خورد؛ دیتابیس و رسانه قبلی با موفقیت بازگردانده شدند."
            ) from exc
