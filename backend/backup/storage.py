"""
Backup storage abstraction.
"""

from pathlib import Path
import uuid

from django.conf import settings


class BackupStorageError(Exception):
    """Raised for unsafe or invalid storage operations."""


class BackupImportError(Exception):
    """Raised when an imported backup file fails validation or staging."""


class BackupStorage:
    """Interface for the storage backend that holds final backup archives."""

    IMPORT_STAGING_SUFFIX = ".importing"
    root = None

    def safe_stage_name(self, original_filename):
        raise NotImplementedError

    def finalize_import(self, staging_path, target_name):
        raise NotImplementedError

    def path_for(self, relpath):
        raise NotImplementedError

    def exists(self, path):
        raise NotImplementedError

    def open(self, relpath, mode="rb"):
        raise NotImplementedError

    def delete(self, relpath):
        raise NotImplementedError

    def finalize(self, tmp_absolute_path, filename):
        raise NotImplementedError


class LocalBackupStorage(BackupStorage):
    """Filesystem-backed storage rooted at ``settings.BACKUP_ROOT``."""

    def __init__(self, root=None):
        self.root = Path(root or settings.BACKUP_ROOT).resolve()

    def ensure_root(self):
        self.root.mkdir(parents=True, exist_ok=True)

    def safe_stage_name(self, original_filename):
        if not original_filename:
            raise BackupStorageError("uploaded filename is empty")
        name = Path(original_filename).name
        if not name or name.startswith("."):
            raise BackupStorageError("unsafe uploaded filename")
        return f".{name}{self.IMPORT_STAGING_SUFFIX}"

    def finalize_import(self, staging_path, target_name):
        if not target_name or Path(target_name).is_absolute() or ".." in Path(target_name).parts:
            raise BackupStorageError(f"unsafe import target name: {target_name!r}")
        self.ensure_root()
        staging = Path(staging_path)
        if not staging.exists():
            raise BackupStorageError(f"staging file does not exist: {staging}")

        final_path = self.root / target_name
        if final_path.exists():
            suffix = Path(target_name).suffix
            base_name = Path(target_name).stem
            final_path = self.root / f"{base_name}_{uuid.uuid4().hex[:8]}{suffix}"
        staging.replace(final_path)
        return final_path

    def path_for(self, relpath):
        if not relpath:
            raise BackupStorageError("storage path is empty")
        candidate = Path(relpath)
        if candidate.is_absolute():
            raise BackupStorageError("absolute storage paths are not allowed")
        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise BackupStorageError(
                f"storage path resolves outside the backup root: {relpath!r}"
            )
        return resolved

    def exists(self, path):
        return Path(path).is_file()

    def open(self, relpath, mode="rb"):
        return open(self.path_for(relpath), mode)

    def delete(self, relpath):
        path = self.path_for(relpath)
        if path.exists():
            path.unlink()

    def finalize(self, tmp_absolute_path, filename):
        if not filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
            raise BackupStorageError(f"unsafe backup filename: {filename!r}")
        self.ensure_root()
        final_path = self.root / filename
        tmp_path = Path(tmp_absolute_path)
        if not tmp_path.exists():
            raise BackupStorageError(f"temporary archive does not exist: {tmp_path}")
        if final_path.exists():
            raise BackupStorageError(f"a backup file already exists: {filename!r}")
        tmp_path.replace(final_path)
        return final_path

class NetworkBackupStorage:
    """Filesystem-backed network storage rooted at BACKUP_NETWORK_ROOT.

    The root is expected to be an SMB/NFS share mounted by the operating
    system. Dolphin-Flow deliberately does not handle SMB/NFS credentials
    itself; the operating system owns that connection.
    """

    def __init__(self, root=None):
        configured = root if root is not None else getattr(settings, "BACKUP_NETWORK_ROOT", "")
        if not configured:
            raise BackupStorageError(
                "مسیر ذخیره‌سازی شبکه در BACKUP_NETWORK_ROOT تنظیم نشده است."
            )
        self.root = Path(configured).resolve()

    def ensure_root(self):
        if not self.root.exists():
            raise BackupStorageError(
                f"مسیر ذخیره‌سازی شبکه وجود ندارد: {self.root}"
            )
        if not self.root.is_dir():
            raise BackupStorageError(
                f"مسیر ذخیره‌سازی شبکه پوشه نیست: {self.root}"
            )

    def target_path(self, filename):
        if not filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
            raise BackupStorageError(f"نام فایل شبکه ناامن است: {filename!r}")
        self.ensure_root()
        return self.root / filename
