"""Cross-process shared/exclusive lock for draining application work before restore."""
import fcntl
import os
import stat
import time
from pathlib import Path

from django.conf import settings

from .restore_maintenance import RestoreMaintenanceError, maintenance_is_active


LOCK_NAME = ".restore-drain.lock"


class RestoreDrainLock:
    """An OS-released flock lease; process death cannot leave a stale lock."""

    def __init__(self, fd, exclusive):
        self.fd = fd
        self.exclusive = exclusive
        self.released = False

    @classmethod
    def acquire(cls, *, exclusive=False, timeout=0):
        root = Path(settings.BACKUP_ROOT).expanduser().resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = root / LOCK_NAME
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise RestoreMaintenanceError("فایل قفل Drain باید یک فایل معمولی باشد.")
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            deadline = time.monotonic() + max(0, timeout)
            while True:
                try:
                    fcntl.flock(fd, operation | fcntl.LOCK_NB)
                    return cls(fd, exclusive)
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RestoreMaintenanceError(
                            "قفل Drain در مهلت تعیین‌شده آزاد نشد؛ عملیات ادامه نمی‌یابد."
                        )
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        except Exception:
            os.close(fd)
            raise

    def release(self):
        if self.released:
            return
        self.released = True
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()


def acquire_application_work_lease(*, timeout=0):
    """Acquire shared work ownership, then recheck the gate to close the race."""
    lease = RestoreDrainLock.acquire(exclusive=False, timeout=timeout)
    try:
        if maintenance_is_active():
            raise RestoreMaintenanceError("سامانه در وضعیت Maintenance است.")
        return lease
    except Exception:
        lease.release()
        raise
