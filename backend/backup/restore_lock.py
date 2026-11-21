"""Process-wide exclusive lock for restore cutover operations.

The lock is advisory and held by an open file descriptor. The OS releases it
automatically if a worker or server process exits unexpectedly.
"""

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from .restore_services import RestoreError


class RestoreOperationLock:
    """Allow only one restore operation to own the cutover lock at a time."""

    def __init__(self, root=None, operation_id=None, restore_id=None):
        configured_root = root or getattr(
            settings,
            "RESTORE_JOURNAL_ROOT",
            Path(settings.BACKUP_ROOT) / ".restore-journal",
        )
        self.root = Path(configured_root).expanduser().resolve()
        media_root = Path(settings.MEDIA_ROOT).expanduser().resolve()
        if self.root == media_root or media_root in self.root.parents:
            raise RestoreError("محل قفل Restore نباید داخل MEDIA_ROOT باشد.")

        self.path = self.root / ".restore-operation.lock"
        self.operation_id = operation_id
        self.restore_id = restore_id
        self._fd = None

    @property
    def acquired(self):
        return self._fd is not None

    def acquire(self):
        if self.acquired:
            raise RestoreError("این نمونه از قبل قفل Restore را در اختیار دارد.")

        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = None
        lock_acquired = False
        try:
            fd = os.open(self.path, flags, 0o600)
            if not os.path.isfile(self.path):
                raise RestoreError("فایل قفل Restore معتبر نیست.")
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
            except BlockingIOError as exc:
                raise RestoreError(
                    "یک عملیات Restore دیگر در حال اجراست؛ عملیات جدید آغاز نشد."
                ) from exc

            metadata = {
                "operation_id": self.operation_id,
                "restore_id": self.restore_id,
                "pid": os.getpid(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }
            encoded = json.dumps(
                metadata, ensure_ascii=False, sort_keys=True
            ).encode("utf-8")
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, encoded)
            os.fsync(fd)
            self._fd = fd
            return self
        except RestoreError:
            if fd is not None:
                if lock_acquired:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            raise
        except OSError as exc:
            if fd is not None:
                if lock_acquired:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            raise RestoreError("دریافت قفل Restore ناموفق بود: " + str(exc)) from exc

    def release(self):
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
        return False
