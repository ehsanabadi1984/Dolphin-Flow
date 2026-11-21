"""Guarded PostgreSQL database rename cutover for staged restores.

The caller must hold RestoreOperationLock and stop/prevent application services
from reconnecting. The previous live database is retained under a unique name;
this module never drops it.
"""

import re
import secrets
from copy import deepcopy

from django.conf import settings
from django.db.backends.postgresql.base import DatabaseWrapper

from .restore_quiescence import (
    MAINTENANCE_DATABASE,
    assert_database_quiescent,
    close_restore_worker_connection,
)
from .restore_services import RestoreError
from .staged_restore import STAGING_DATABASE_PREFIX


_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_]{1,63}$")


class StagedDatabaseCutover:
    """Swap a validated staging DB into place while preserving the old DB."""

    def __init__(self, staging_name, journal, database_settings=None):
        self.config = deepcopy(database_settings or settings.DATABASES["default"])
        self.live_name = self.config.get("NAME")
        self.staging_name = staging_name
        self.journal = journal
        self.previous_name = None
        self._old_renamed = False
        self._stage_renamed = False

        if not isinstance(self.live_name, str) or not _SAFE_NAME.fullmatch(self.live_name):
            raise RestoreError("نام دیتابیس اصلی برای تعویض معتبر نیست.")
        if self.live_name == MAINTENANCE_DATABASE:
            raise RestoreError("دیتابیس مدیریتی PostgreSQL قابل تعویض نیست.")
        if (
            not isinstance(staging_name, str)
            or not staging_name.startswith(STAGING_DATABASE_PREFIX)
            or not _SAFE_NAME.fullmatch(staging_name)
            or staging_name == self.live_name
        ):
            raise RestoreError("نام دیتابیس موقت برای تعویض معتبر نیست.")

        suffix = secrets.token_hex(6)
        self.previous_name = f"{self.live_name[:45]}_previous_{suffix}"
        if not _SAFE_NAME.fullmatch(self.previous_name):
            raise RestoreError("نام دیتابیس قبلی برای نگهداری معتبر نیست.")

    def _admin(self):
        config = deepcopy(self.config)
        config["NAME"] = MAINTENANCE_DATABASE
        config["OPTIONS"] = config.get("OPTIONS") or {}
        admin = DatabaseWrapper(config, alias=f"restore_cutover_{secrets.token_hex(6)}")
        admin.ensure_connection()
        admin.set_autocommit(True)
        return admin

    @staticmethod
    def _exists(cursor, name):
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name])
        return cursor.fetchone() is not None

    @staticmethod
    def _rename(cursor, old_name, new_name, ops):
        cursor.execute(
            f"ALTER DATABASE {ops.quote_name(old_name)} RENAME TO {ops.quote_name(new_name)}"
        )

    def swap(self, database_stage=None):
        """Rename live aside, then staging into place; rollback on any error."""
        if database_stage is not None:
            database_stage.close()

        close_restore_worker_connection()
        assert_database_quiescent(self.config)
        self.journal.update(phase="QUIESCING")
        admin = self._admin()
        try:
            with admin.cursor() as cursor:
                if not self._exists(cursor, self.live_name):
                    raise RestoreError("دیتابیس اصلی برای تعویض پیدا نشد.")
                if not self._exists(cursor, self.staging_name):
                    raise RestoreError("دیتابیس موقت آماده برای تعویض پیدا نشد.")
                if self._exists(cursor, self.previous_name):
                    raise RestoreError("نام دیتابیس قبلی از قبل وجود دارد.")

                self.journal.update(
                    database={
                        "live_name": self.live_name,
                        "staging_name": self.staging_name,
                        "previous_name": self.previous_name,
                        "old_renamed": False,
                        "staging_renamed": False,
                    }
                )
                self._rename(cursor, self.live_name, self.previous_name, admin.ops)
                self._old_renamed = True
                self.journal.update(database={"old_renamed": True})

                self._rename(cursor, self.staging_name, self.live_name, admin.ops)
                self._stage_renamed = True
                self.journal.update(database={"staging_renamed": True})
                self.journal.update(phase="DATABASE_SWAPPED")
        except Exception as exc:
            try:
                self._rollback_with_admin(admin)
            except Exception as rollback_exc:
                try:
                    self.journal.update(
                        phase="ROLLBACK_REQUIRED",
                        error=f"{exc}; rollback failed: {rollback_exc}",
                    )
                except Exception:
                    pass
                raise RestoreError(
                    "تعویض دیتابیس شکست خورد و بازگشت خودکار کامل نشد؛ بازیابی دستی لازم است."
                ) from rollback_exc
            if isinstance(exc, RestoreError):
                raise
            raise RestoreError("تعویض دیتابیس ناموفق بود: " + str(exc)) from exc
        finally:
            admin.close()

        return {
            "live_database": self.live_name,
            "previous_database": self.previous_name,
            "staging_database": self.staging_name,
        }

    def _rollback_with_admin(self, admin):
        if not self._old_renamed and not self._stage_renamed:
            return
        with admin.cursor() as cursor:
            if self._stage_renamed:
                if self._exists(cursor, self.live_name):
                    self._rename(cursor, self.live_name, self.staging_name, admin.ops)
                self._stage_renamed = False
            if self._old_renamed:
                if self._exists(cursor, self.previous_name):
                    if self._exists(cursor, self.live_name):
                        raise RestoreError(
                            "نام دیتابیس اصلی اشغال است؛ بازگرداندن نسخه قبلی ایمن نیست."
                        )
                    self._rename(cursor, self.previous_name, self.live_name, admin.ops)
                self._old_renamed = False
        self.journal.update(
            phase="ROLLBACK_REQUIRED",
            database={"old_renamed": False, "staging_renamed": False},
        )
        self.journal.update(phase="ROLLED_BACK")

    def rollback(self):
        """Explicitly restore the preserved database after a later cutover failure."""
        admin = self._admin()
        try:
            with admin.cursor() as cursor:
                live_is_new = self._exists(cursor, self.live_name)
                previous_exists = self._exists(cursor, self.previous_name)
                if not previous_exists:
                    raise RestoreError("نسخه قبلی دیتابیس برای بازگشت پیدا نشد.")
                if live_is_new:
                    if self._exists(cursor, self.staging_name):
                        raise RestoreError("نام دیتابیس موقت اشغال است؛ بازگشت ایمن نیست.")
                    self._rename(cursor, self.live_name, self.staging_name, admin.ops)
                self._rename(cursor, self.previous_name, self.live_name, admin.ops)
            self.journal.update(
                phase="ROLLBACK_REQUIRED",
                database={"staging_renamed": False, "old_renamed": False},
            )
            self.journal.update(phase="ROLLED_BACK")
        except RestoreError:
            raise
        except Exception as exc:
            try:
                self.journal.update(phase="ROLLBACK_REQUIRED", error=str(exc))
            except Exception:
                pass
            raise RestoreError("بازگشت دیتابیس ناموفق بود: " + str(exc)) from exc
        finally:
            admin.close()
