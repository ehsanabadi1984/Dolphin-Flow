"""Durable, filesystem-backed journal for staged restore cutover.

The journal is deliberately stored outside the live media tree and database.
It records recovery intent only; it never performs a database or media swap.
"""

import json
import os
import re
import secrets
import stat
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from .restore_services import RestoreError

JOURNAL_SCHEMA_VERSION = 1
OPERATION_ID_RE = re.compile(r"^[a-f0-9]{32}$")

PHASES = {
    "PREPARED",
    "QUIESCING",
    "DATABASE_SWAPPED",
    "MEDIA_SWAPPED",
    "COMPLETED",
    "ROLLBACK_REQUIRED",
    "ROLLED_BACK",
}

_ALLOWED_TRANSITIONS = {
    "PREPARED": {"QUIESCING", "ROLLBACK_REQUIRED"},
    "QUIESCING": {"DATABASE_SWAPPED", "ROLLBACK_REQUIRED"},
    "DATABASE_SWAPPED": {"MEDIA_SWAPPED", "ROLLBACK_REQUIRED"},
    "MEDIA_SWAPPED": {"COMPLETED", "ROLLBACK_REQUIRED"},
    "ROLLBACK_REQUIRED": {"ROLLED_BACK"},
    "COMPLETED": set(),
    "ROLLED_BACK": set(),
}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class RestoreJournal:
    """Persist and reload one restore operation using atomic file replacement."""

    def __init__(self, operation_id, root=None):
        if not isinstance(operation_id, str) or not OPERATION_ID_RE.fullmatch(operation_id):
            raise RestoreError("شناسه عملیات بازیابی معتبر نیست.")
        configured_root = root or getattr(
            settings,
            "RESTORE_JOURNAL_ROOT",
            Path(settings.BACKUP_ROOT) / ".restore-journal",
        )
        self.root = Path(configured_root).expanduser().resolve()
        self.operation_id = operation_id
        self.path = self.root / f"{operation_id}.json"

        media_root = Path(settings.MEDIA_ROOT).expanduser().resolve()
        if self.root == media_root or media_root in self.root.parents:
            raise RestoreError("محل Journal نباید داخل MEDIA_ROOT باشد.")

    @classmethod
    def new(cls, restore_id, root=None, database=None, media=None):
        operation_id = secrets.token_hex(16)
        journal = cls(operation_id, root=root)
        now = _utc_now()
        payload = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "operation_id": operation_id,
            "restore_id": int(restore_id),
            "phase": "PREPARED",
            "created_at": now,
            "updated_at": now,
            "database": deepcopy(database or {}),
            "media": deepcopy(media or {}),
            "error": "",
        }
        journal._validate(payload)
        journal._write(payload, exclusive=True)
        return journal

    def _validate(self, payload):
        if not isinstance(payload, dict):
            raise RestoreError("ساختار Journal بازیابی معتبر نیست.")
        if payload.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            raise RestoreError("نسخه Journal بازیابی پشتیبانی نمی‌شود.")
        if payload.get("operation_id") != self.operation_id:
            raise RestoreError("شناسه Journal با فایل آن مطابقت ندارد.")
        if not isinstance(payload.get("restore_id"), int):
            raise RestoreError("شناسه Restore در Journal معتبر نیست.")
        if payload.get("phase") not in PHASES:
            raise RestoreError("مرحله ثبت‌شده در Journal معتبر نیست.")
        for key in ("database", "media"):
            if not isinstance(payload.get(key), dict):
                raise RestoreError(f"بخش {key} در Journal معتبر نیست.")
        if not isinstance(payload.get("error", ""), str):
            raise RestoreError("شرح خطای Journal معتبر نیست.")
        return payload

    def _write(self, payload, exclusive=False):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

        if exclusive and self.path.exists():
            raise RestoreError("Journal این عملیات از قبل وجود دارد.")

        temp_path = None
        try:
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self.operation_id}.",
                suffix=".tmp",
                dir=self.root,
            )
            temp_path = Path(temp_name)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())

            if exclusive and self.path.exists():
                raise RestoreError("Journal این عملیات از قبل وجود دارد.")
            os.replace(temp_path, self.path)

            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except RestoreError:
            raise
        except OSError as exc:
            raise RestoreError("ثبت پایدار Journal ناموفق بود: " + str(exc)) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def read(self):
        """Read only a regular journal file; never follow a symbolic link."""
        descriptor = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.path, flags)
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise RestoreError("فایل Journal باید یک فایل معمولی باشد.")
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = None
                payload = json.load(handle)
        except RestoreError:
            raise
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RestoreError("خواندن Journal بازیابی ناموفق بود: " + str(exc)) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return deepcopy(self._validate(payload))

    def update(self, phase=None, error=None, database=None, media=None):
        payload = self.read()
        current = payload["phase"]

        if phase is not None:
            if phase not in PHASES:
                raise RestoreError("مرحله جدید Journal معتبر نیست.")
            if phase != current and phase not in _ALLOWED_TRANSITIONS[current]:
                raise RestoreError(
                    f"انتقال Journal از {current} به {phase} مجاز نیست."
                )
            payload["phase"] = phase

        if database is not None:
            if not isinstance(database, dict):
                raise RestoreError("اطلاعات دیتابیس Journal باید یک شیء باشد.")
            payload["database"].update(deepcopy(database))

        if media is not None:
            if not isinstance(media, dict):
                raise RestoreError("اطلاعات رسانه Journal باید یک شیء باشد.")
            payload["media"].update(deepcopy(media))

        if error is not None:
            payload["error"] = str(error)[:2000]

        payload["updated_at"] = _utc_now()
        self._validate(payload)
        self._write(payload)
        return deepcopy(payload)

    def delete(self):
        """Delete only this operation's journal; caller owns retention policy."""
        try:
            self.path.unlink(missing_ok=True)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise RestoreError("حذف Journal بازیابی ناموفق بود: " + str(exc)) from exc
