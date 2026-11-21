"""Crash recovery for interrupted staged restore cutovers.

Recovery is deliberately conservative: it only rolls resources back when the
recorded names/paths form an unambiguous state produced by the staged rename
protocol. It never drops a database or deletes a media tree.
"""
from pathlib import Path

from django.conf import settings
from django.db.backends.postgresql.base import DatabaseWrapper

from .restore_drain import RestoreDrainLock
from .restore_journal import RestoreJournal
from .restore_lock import RestoreOperationLock
from .restore_maintenance import (
    RestoreMaintenanceError,
    read_maintenance_state,
)
from .restore_quiescence import (
    MAINTENANCE_DATABASE,
    assert_database_quiescent,
    assert_systemd_services_stopped,
    close_restore_worker_connection,
)
from .restore_services import RestoreError


class StagedRestoreRecovery:
    """Reconcile actual DB/media names and safely roll an interrupted swap back."""

    def __init__(self, journal, database_settings=None, media_root=None):
        self.journal = journal
        self.config = dict(database_settings or settings.DATABASES["default"])
        self.media_root = Path(media_root or settings.MEDIA_ROOT).absolute()

    def _admin(self):
        config = dict(self.config)
        config["NAME"] = MAINTENANCE_DATABASE
        config["OPTIONS"] = config.get("OPTIONS") or {}
        admin = DatabaseWrapper(config, alias="restore_recovery_admin")
        admin.ensure_connection()
        admin.set_autocommit(True)
        return admin

    @staticmethod
    def _database_exists(cursor, name):
        if not name:
            return False
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name])
        return cursor.fetchone() is not None

    def inspect_actual_state(self):
        payload = self.journal.read()
        database = payload["database"]
        media = payload["media"]
        live_name = database.get("live_name") or self.config.get("NAME")
        previous_name = database.get("previous_name")
        staging_name = database.get("staging_name")

        if not live_name or not staging_name:
            raise RestoreError("اطلاعات نام دیتابیس برای Recovery کافی نیست.")

        admin = self._admin()
        try:
            with admin.cursor() as cursor:
                db_state = {
                    "live": self._database_exists(cursor, live_name),
                    "previous": self._database_exists(cursor, previous_name),
                    "staging": self._database_exists(cursor, staging_name),
                }
        finally:
            admin.close()

        media_state = None
        if media.get("included"):
            live_path = Path(media.get("live_path") or media.get("media_root") or self.media_root)
            stage_value = media.get("staging_path")
            previous_value = media.get("previous_path")
            if not stage_value or not previous_value:
                raise RestoreError("اطلاعات مسیر رسانه برای Recovery کافی نیست.")
            stage_path = Path(stage_value)
            previous_path = Path(previous_value)
            if live_path != self.media_root or live_path.parent != stage_path.parent or live_path.parent != previous_path.parent:
                raise RestoreError("مسیرهای رسانه ثبت‌شده با MEDIA_ROOT هم‌خوانی ندارند.")
            if not stage_path.name.startswith(f".{live_path.name}.restore-"):
                raise RestoreError("مسیر staging رسانه متعلق به Restore نیست.")
            if not previous_path.name.startswith(f".{live_path.name}.previous-"):
                raise RestoreError("مسیر رسانه قبلی معتبر نیست.")
            if any(path.is_symlink() for path in (live_path, stage_path, previous_path)):
                raise RestoreError("Recovery مسیرهای Symlink را نمی‌پذیرد.")
            media_state = {
                "live": live_path.exists() and live_path.is_dir(),
                "previous": previous_path.exists() and previous_path.is_dir(),
                "staging": stage_path.exists() and stage_path.is_dir(),
            }

        return {
            "phase": payload["phase"],
            "database": db_state,
            "media": media_state,
            "names": {
                "live_database": live_name,
                "previous_database": previous_name,
                "staging_database": staging_name,
            },
            "paths": {
                "live_media": str(self.media_root),
                "previous_media": str(previous_path) if media_state else None,
                "staging_media": str(stage_path) if media_state else None,
            },
        }

    @staticmethod
    def _classify_resource(state, label):
        live, previous, staging = state["live"], state["previous"], state["staging"]
        if live and not previous and staging:
            return "NOT_SWAPPED"
        if not live and previous and staging:
            return "OLD_MOVED"
        if live and previous and not staging:
            return "NEW_PROMOTED"
        raise RestoreError(
            f"وضعیت {label} مبهم یا ناقص است؛ Recovery خودکار برای جلوگیری از آسیب متوقف شد."
        )

    def rollback(self, *, service_units):
        payload = self.journal.read()
        if payload["phase"] in {"COMPLETED", "ROLLED_BACK"}:
            raise RestoreError("عملیات نهایی‌شده نیاز به Recovery ندارد.")
        state = read_maintenance_state()
        if state is None or state.get("operation_id") != self.journal.operation_id:
            raise RestoreError("Maintenance فعال و متعلق به همین Journal نیست.")

        operation_lock = RestoreOperationLock(
            operation_id=self.journal.operation_id,
            restore_id=payload["restore_id"],
        )
        with operation_lock:
            assert_systemd_services_stopped(service_units)
            close_restore_worker_connection()
            assert_database_quiescent(self.config)
            with RestoreDrainLock.acquire(
                exclusive=True,
                timeout=getattr(settings, "RESTORE_DRAIN_TIMEOUT_SECONDS", 30),
            ):
                actual = self.inspect_actual_state()
                db_class = self._classify_resource(actual["database"], "دیتابیس")
                media_class = (
                    self._classify_resource(actual["media"], "رسانه")
                    if actual["media"] is not None
                    else None
                )

                self.journal.update(
                    phase="ROLLBACK_REQUIRED",
                    error="Crash recovery: conservative rollback initiated.",
                )

                admin = self._admin()
                try:
                    names = actual["names"]
                    with admin.cursor() as cursor:
                        if db_class == "NEW_PROMOTED":
                            cursor.execute(
                                f"ALTER DATABASE {admin.ops.quote_name(names['live_database'])} "
                                f"RENAME TO {admin.ops.quote_name(names['staging_database'])}"
                            )
                        if db_class in {"OLD_MOVED", "NEW_PROMOTED"}:
                            cursor.execute(
                                f"ALTER DATABASE {admin.ops.quote_name(names['previous_database'])} "
                                f"RENAME TO {admin.ops.quote_name(names['live_database'])}"
                            )
                finally:
                    admin.close()

                if media_class is not None:
                    live = Path(actual["paths"]["live_media"])
                    previous = Path(actual["paths"]["previous_media"])
                    staging = Path(actual["paths"]["staging_media"])
                    if media_class == "NEW_PROMOTED":
                        live.rename(staging)
                    if media_class in {"OLD_MOVED", "NEW_PROMOTED"}:
                        previous.rename(live)
                    descriptor = __import__("os").open(live.parent, __import__("os").O_RDONLY)
                    try:
                        __import__("os").fsync(descriptor)
                    finally:
                        __import__("os").close(descriptor)

                verified = self.inspect_actual_state()
                self._classify_resource(verified["database"], "دیتابیس پس از بازگشت")
                if verified["database"]["previous"]:
                    raise RestoreError("نسخه قبلی دیتابیس هنوز در مسیر اصلی بازنگشته است.")
                if verified["media"] is not None:
                    self._classify_resource(verified["media"], "رسانه پس از بازگشت")
                    if verified["media"]["previous"]:
                        raise RestoreError("نسخه قبلی رسانه هنوز در مسیر اصلی بازنگشته است.")

                self.journal.update(
                    phase="ROLLED_BACK",
                    error="Crash recovery rollback verified.",
                    database={"old_renamed": False, "staging_renamed": False},
                    media={"live_moved": False, "staging_moved": False},
                )
                return {"status": "ROLLED_BACK", "state": verified}
