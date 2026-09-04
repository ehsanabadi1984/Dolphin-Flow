"""
Backup storage abstraction.

The backup service depends only on the ``BackupStorage`` interface so that
future phases can add network (SMB/NFS/SFTP) or cloud backends without
touching the service. Only the local backend is implemented in this phase.
"""

from pathlib import Path

from django.conf import settings


class BackupStorageError(Exception):
    """Raised for unsafe or invalid storage operations."""


class BackupStorage:
    """Interface for the storage backend that holds final backup archives."""

    #: Absolute path of the storage root (for local backends).
    root = None

    def path_for(self, relpath):
        """Return a guarded absolute path for a relative key.

        Raises ``BackupStorageError`` when the key is absolute, empty, or
        resolves outside the storage root (path traversal protection).
        """
        raise NotImplementedError

    def exists(self, path):
        raise NotImplementedError

    def open(self, relpath, mode="rb"):
        raise NotImplementedError

    def delete(self, relpath):
        raise NotImplementedError

    def finalize(self, tmp_absolute_path, filename):
        """Atomically move a completed temporary archive to its final name.

        ``tmp_absolute_path`` must live on the same filesystem as the root.
        Returns the final absolute path.
        """
        raise NotImplementedError


class LocalBackupStorage(BackupStorage):
    """Filesystem-backed storage rooted at ``settings.BACKUP_ROOT``."""

    def __init__(self, root=None):
        self.root = Path(root or settings.BACKUP_ROOT).resolve()

    def ensure_root(self):
        self.root.mkdir(parents=True, exist_ok=True)

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
        path = Path(path)
        return path.is_file()

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
            raise BackupStorageError(
                f"temporary archive does not exist: {tmp_path}"
            )

        # Atomic rename on the same filesystem; replace a stale file with the
        # same name if one exists.
        if final_path.exists():
            final_path.unlink()

        tmp_path.replace(final_path)

        return final_path