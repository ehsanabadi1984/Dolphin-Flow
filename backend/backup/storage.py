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


class BackupImportError(Exception):
    """Raised when an imported backup file fails validation or staging."""


class BackupStorage:
    """Interface for the storage backend that holds final backup archives."""

    #: Suffix for temporary staging files during import.
    IMPORT_STAGING_SUFFIX = ".importing"

    def safe_stage_name(self, original_filename):
        """Return a safe, normalized staging name for an uploaded file.

        The original filename is sanitized so path traversal and special
        characters cannot escape the staging directory.
        """
        raise NotImplementedError

    def finalize_import(self, staging_path, target_name):
        """Atomically move a validated import staging file to its final name.

        ``staging_path`` must live on the same filesystem as the root.
        Returns the final absolute path.
        """
        raise NotImplementedError

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

    def safe_stage_name(self, original_filename):
        """Return a safe staging name from an uploaded filename.

        The original filename is not trusted. Only a normalized name derived
        from the base filename is used, with a staging suffix so partially
        uploaded imports cannot be mistaken for valid backups.
        """
        if not original_filename:
            raise BackupStorageError("uploaded filename is empty")

        name = Path(original_filename).name

        if not name:
            raise BackupStorageError("uploaded filename has no name")

        # Reject names that would escape even after basenaming.
        if name.startswith("."):
            raise BackupStorageError("unsafe uploaded filename")

        return f".{name}{self.IMPORT_STAGING_SUFFIX}"

    def finalize_import(self, staging_path, target_name):
        """Atomically move a validated import to its final name.

        Mirrors ``finalize`` semantics: refuses to overwrite, enforces safe
        target name. For imported backups, handles filename collisions by
        appending a unique suffix to the storage filename while preserving
        the original filename as metadata.
        """
        if not target_name or Path(target_name).is_absolute() or ".." in Path(target_name).parts:
            raise BackupStorageError(f"unsafe import target name: {target_name!r}")

        self.ensure_root()

        staging = Path(staging_path)

        if not staging.exists():
            raise BackupStorageError(
                f"staging file does not exist: {staging}"
            )

        # Try the original target name first.
        final_path = self.root / target_name
        
        if not final_path.exists():
            # No collision - use the original name.
            staging.replace(final_path)
            return final_path
        
        # Collision detected - create a unique storage filename.
        # Preserve the original filename as metadata (stored in Backup record),
        # but use a unique storage filename.
        import uuid
        unique_suffix = uuid.uuid4().hex[:8]
        base_name = Path(target_name).stem
        suffix = Path(target_name).suffix
        unique_filename = f"{base_name}_{unique_suffix}{suffix}"
        
        final_path = self.root / unique_filename
        
        # Safety check - ensure the unique name doesn't exist (shouldn't happen with UUID).
        if final_path.exists():
            # Extremely unlikely, but try once more with a different suffix.
            unique_suffix = uuid.uuid4().hex[:8]
            unique_filename = f"{base_name}_{unique_suffix}{suffix}"
            final_path = self.root / unique_filename
        
        staging.replace(final_path)
        return final_path

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

        # Never destroy an existing backup: filenames are timestamp-based and a
        # collision would otherwise silently overwrite a successful archive.
        # Refuse instead; the new backup fails visibly and the old one survives.
        if final_path.exists():
            raise BackupStorageError(
                f"a backup file already exists: {filename!r}"
            )

        # Atomic rename on the same filesystem.
        tmp_path.replace(final_path)

        return final_path