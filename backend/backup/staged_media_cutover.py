"""Atomic same-filesystem media directory swap for staged restores.

The previous MEDIA_ROOT is retained under a unique sibling name. This module
never deletes either the previous media tree or the staged tree.
"""

import secrets
import shutil
from pathlib import Path

from django.conf import settings

from .restore_services import RestoreError


class StagedMediaCutover:
    def __init__(self, staging_path, journal, media_root=None):
        self.live_path = Path(media_root or settings.MEDIA_ROOT).absolute()
        self.stage_path = Path(staging_path).absolute()
        self.journal = journal
        self.previous_path = self.live_path.parent / (
            f".{self.live_path.name}.previous-{secrets.token_hex(8)}"
        )
        self._live_moved = False
        self._stage_moved = False
        self._validate_paths()

    def _validate_paths(self):
        parent = self.live_path.parent
        if self.live_path.is_symlink() or self.stage_path.is_symlink():
            raise RestoreError("مسیرهای رسانه نباید پیوند نمادین باشند.")
        if self.live_path.parent != self.stage_path.parent:
            raise RestoreError("پوشه staging رسانه باید کنار MEDIA_ROOT باشد.")
        if not self.stage_path.name.startswith(f".{self.live_path.name}.restore-"):
            raise RestoreError("مسیر staging رسانه متعلق به این Restore نیست.")
        if not self.live_path.exists() or not self.live_path.is_dir():
            raise RestoreError("پوشه رسانه فعلی برای تعویض در دسترس نیست.")
        if not self.stage_path.exists() or not self.stage_path.is_dir():
            raise RestoreError("پوشه staging رسانه آماده نیست.")
        if self.previous_path.exists() or self.previous_path.is_symlink():
            raise RestoreError("مسیر نگهداری رسانه قبلی از قبل وجود دارد.")
        parent_device = parent.stat().st_dev
        if (
            self.live_path.stat().st_dev != parent_device
            or self.stage_path.stat().st_dev != parent_device
        ):
            raise RestoreError("مسیرهای رسانه برای جابه‌جایی اتمیک روی یک فایل‌سیستم نیستند.")

    @staticmethod
    def _fsync_directory(path):
        descriptor = None
        try:
            descriptor = __import__("os").open(path, __import__("os").O_RDONLY)
            __import__("os").fsync(descriptor)
        finally:
            if descriptor is not None:
                __import__("os").close(descriptor)

    def swap(self):
        """Move live aside, then promote staged media; preserve previous tree."""
        self._validate_paths()
        self.journal.update(
            media={
                "live_path": str(self.live_path),
                "staging_path": str(self.stage_path),
                "previous_path": str(self.previous_path),
                "live_moved": False,
                "staging_moved": False,
            }
        )
        try:
            self.live_path.rename(self.previous_path)
            self._live_moved = True
            self.journal.update(media={"live_moved": True})

            self.stage_path.rename(self.live_path)
            self._stage_moved = True
            self.journal.update(media={"staging_moved": True})
            self.journal.update(phase="MEDIA_SWAPPED")
            self._fsync_directory(self.live_path.parent)
        except Exception as exc:
            try:
                self._rollback_paths()
            except Exception as rollback_exc:
                try:
                    self.journal.update(
                        phase="ROLLBACK_REQUIRED",
                        error=f"{exc}; media rollback failed: {rollback_exc}",
                    )
                except Exception:
                    pass
                raise RestoreError(
                    "تعویض رسانه شکست خورد و بازگشت خودکار کامل نشد؛ بازیابی دستی لازم است."
                ) from rollback_exc
            if isinstance(exc, RestoreError):
                raise
            raise RestoreError("تعویض پوشه رسانه ناموفق بود: " + str(exc)) from exc

        return {
            "live_path": str(self.live_path),
            "previous_path": str(self.previous_path),
            "staging_path": str(self.stage_path),
        }

    def _rollback_paths(self):
        if self._stage_moved:
            if self.live_path.exists():
                self.live_path.rename(self.stage_path)
            self._stage_moved = False
        if self._live_moved:
            if self.previous_path.exists():
                if self.live_path.exists():
                    raise RestoreError("مسیر MEDIA_ROOT اشغال است؛ بازگشت ایمن نیست.")
                self.previous_path.rename(self.live_path)
            self._live_moved = False
        self._fsync_directory(self.live_path.parent)

    def rollback(self):
        """Restore previous media tree; never delete the staged/new tree."""
        try:
            self._rollback_paths()
            self.journal.update(
                phase="ROLLBACK_REQUIRED",
                media={"live_moved": False, "staging_moved": False},
            )
        except Exception as exc:
            try:
                self.journal.update(phase="ROLLBACK_REQUIRED", error=str(exc))
            except Exception:
                pass
            if isinstance(exc, RestoreError):
                raise
            raise RestoreError("بازگشت پوشه رسانه ناموفق بود: " + str(exc)) from exc
