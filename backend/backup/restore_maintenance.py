"""Persistent filesystem gate used to stop new application work during restore.

The marker intentionally survives process restarts. It is not a substitute for
draining in-flight requests/tasks or stopping service processes before cutover.
"""
import json
import os
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from .restore_services import RestoreError


MARKER_NAME = ".restore-maintenance"


def maintenance_marker_path():
    return Path(settings.BACKUP_ROOT).expanduser().resolve() / MARKER_NAME


def read_maintenance_state():
    path = maintenance_marker_path()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RestoreError("خواندن وضعیت Maintenance ناموفق بود: " + str(exc)) from exc

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RestoreError("نشانگر Maintenance باید یک فایل معمولی باشد.")
        raw = b""
        while len(raw) <= 16384:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            raw += chunk
        if len(raw) > 16384:
            raise RestoreError("محتوای نشانگر Maintenance بیش از حد مجاز است.")
    finally:
        os.close(fd)

    try:
        state = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RestoreError("نشانگر Maintenance معتبر نیست.") from exc
    if not isinstance(state, dict) or not isinstance(state.get("operation_id"), str):
        raise RestoreError("ساختار نشانگر Maintenance معتبر نیست.")
    return state


def maintenance_is_active():
    return read_maintenance_state() is not None


def activate_maintenance(operation_id=None):
    """Atomically create the persistent gate; never overwrite an existing one."""
    operation_id = operation_id or secrets.token_hex(16)
    if (
        not isinstance(operation_id, str)
        or len(operation_id) != 32
        or any(char not in "0123456789abcdef" for char in operation_id)
    ):
        raise RestoreError("شناسه عملیات Maintenance معتبر نیست.")

    path = maintenance_marker_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "operation_id": operation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise RestoreError("Maintenance از قبل فعال است؛ نشانگر موجود بازنویسی نشد.") from exc
    try:
        os.write(fd, payload)
        os.fsync(fd)
    except OSError:
        os.close(fd)
        try:
            path.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(fd)

    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return operation_id


def deactivate_maintenance(operation_id):
    """Remove only the marker owned by the supplied operation."""
    state = read_maintenance_state()
    if state is None:
        return False
    if state.get("operation_id") != operation_id:
        raise RestoreError("شناسه عملیات با نشانگر Maintenance مطابقت ندارد.")
    path = maintenance_marker_path()
    path.unlink()
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return True


class RestoreMaintenanceASGIMiddleware:
    """Reject new WebSocket connections while restore maintenance is active."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket" and maintenance_is_active():
            await send({"type": "websocket.close", "code": 1013})
            return
        await self.app(scope, receive, send)
