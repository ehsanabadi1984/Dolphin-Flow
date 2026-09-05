"""
Backup import / validation service.

Validates an external ``.dfbak`` archive (untrusted input) and, when all
checks pass, promotes it to a restorable ``Backup(status=SUCCESS)`` record.

Pipeline (synchronous, in the HTTP request — never destructive):

    receive uploaded file into staging location
        -> enforce safe filename (no trust in original name)
        -> validate TAR structure (reject traversal, symlinks, special files)
        -> validate manifest.json
        -> validate database.dump (exists, non-empty, pg_restore --list)
        -> validate media.tar.gz when manifest says media is included
        -> calculate SHA-256
        -> mark Backup as IMPORTED (not yet SUCCESS)
        -> when all validation passes: finalize import and mark SUCCESS

An imported file is never treated as a restorable SUCCESS backup until
validation has completed successfully.
"""

import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

# Import subprocess at module level so tests can patch it.
# The import_service module uses subprocess.run directly for pg_restore.
# Tests should patch "backup.import_service.subprocess.run" to mock it.

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Backup, Restore, generate_backup_filename
from .restore_services import (
    BACKUP_FORMAT,
    BACKUP_FORMAT_VERSION,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MEDIA_FILENAME,
    RestoreError,
    _assert_safe_member,
    read_manifest,
)
from .services import sanitize_message
from .storage import BackupImportError, BackupStorageError, LocalBackupStorage

logger = logging.getLogger(__name__)


class BackupImportService:
    """Validate and import an external .dfbak file into a restorable Backup."""

    #: Maximum allowed size for an uploaded .dfbak (1 GB default).
    MAX_IMPORT_SIZE = 1024 * 1024 * 1024

    #: Maximum number of members allowed in an archive (200 default).
    MAX_ARCHIVE_MEMBERS = 200

    def __init__(self, storage=None):
        self.storage = storage or LocalBackupStorage()

    # ----------------------------------------------------------
    # Entry point
    # ----------------------------------------------------------

    def import_backup(self, uploaded_file, original_filename, user=None):
        """Validate an uploaded .dfbak and create an imported Backup record.

        ``uploaded_file`` is a Django UploadedFile-like object (or any file-like
        with ``read()`` and ``name``). ``original_filename`` is the client-supplied
        filename (not trusted for path purposes).

        Returns a dict with the created Backup and validation details, or raises
        ``BackupImportError`` / ``RestoreError`` on validation failure.
        """
        staging_path = None

        try:
            # Stage the upload into a safe temporary location.
            staging_path = self._stage_upload(uploaded_file, original_filename)

            # Validate the archive structure.
            self._validate_archive_structure(staging_path)

            # Read and validate manifest.
            manifest = read_manifest(staging_path)
            self._validate_manifest(manifest)

            # Validate database.dump.
            dump_tmp_dir = self._extract_member_to_temp(staging_path, DATABASE_FILENAME)
            self._validate_database_dump(dump_tmp_dir)
            dump_file = dump_tmp_dir / DATABASE_FILENAME
            database_size = dump_file.stat().st_size
            shutil.rmtree(dump_tmp_dir, ignore_errors=True)

            # Validate media if expected.
            media_size = 0
            media_valid = True

            if manifest.get("includes_media"):
                media_tmp_dir = self._extract_member_to_temp(staging_path, MEDIA_FILENAME)
                self._validate_media_archive(media_tmp_dir)
                media_file = media_tmp_dir / MEDIA_FILENAME
                media_size = media_file.stat().st_size
                shutil.rmtree(media_tmp_dir, ignore_errors=True)
            else:
                # Ensure media member is NOT present when manifest says it's excluded.
                with tarfile.open(staging_path, "r") as archive:
                    if MEDIA_FILENAME in archive.getnames():
                        raise BackupImportError(
                            "بایگانی حاوی فایل رسانه است در حالی که manifest "
                            "ضمناً رسانه را شامل نمی‌شود."
                        )

            # Calculate SHA-256 of the complete archive.
            checksum = self._calculate_checksum(staging_path)

            # Determine the final filename from the archive itself.
            final_filename = self._determine_filename(manifest, original_filename)

            # Create the Backup record in IMPORTED state (not yet SUCCESS).
            backup = self._create_imported_backup(
                filename=final_filename,
                manifest=manifest,
                checksum=checksum,
                database_size=database_size,
                media_size=media_size,
                user=user,
                staging_path=staging_path,
            )

            # Finalize: move validated file to its final location and mark SUCCESS.
            final_path = self.storage.finalize_import(
                staging_path,
                final_filename,
            )

            self._mark_imported_backup_success(
                backup,
                final_path=final_path,
                checksum=checksum,
                database_size=database_size,
                media_size=media_size,
            )

            return {
                "backup": backup,
                "manifest": manifest,
                "checksum": checksum,
                "database_size": database_size,
                "media_size": media_size,
                "filename": final_filename,
            }

        except BackupImportError:
            raise
        except RestoreError as exc:
            raise BackupImportError(str(exc)) from exc
        except Exception as exc:
            logger.exception(
                "Import of %s failed unexpectedly", original_filename
            )
            raise BackupImportError(
                sanitize_message(str(exc))[:500]
            ) from exc
        finally:
            # Clean up staging directory on failure (but not the finalized file).
            # The staging file has .importing suffix; finalized files don't.
            if staging_path and staging_path.exists():
                if staging_path.name.endswith(self.storage.IMPORT_STAGING_SUFFIX):
                    # Still a staging file - cleanup the entire staging directory.
                    try:
                        staging_dir = staging_path.parent
                        if staging_dir.name == "import" and staging_dir.parent.name == "tmp":
                            shutil.rmtree(staging_dir, ignore_errors=True)
                    except Exception:
                        pass  # Best effort cleanup.

    # ----------------------------------------------------------
    # Staging
    # ----------------------------------------------------------

    def _stage_upload(self, uploaded_file, original_filename):
        """Write the uploaded file to a safe staging location.

        The staging directory is inside BACKUP_ROOT under ``tmp/import/``.
        The filename is sanitized to prevent path traversal.
        """
        self.storage.ensure_root()
        root = Path(self.storage.root)

        staging_dir = root / "tmp" / "import"
        staging_dir.mkdir(parents=True, exist_ok=True)

        # Generate a safe staging name — never trust the original filename.
        safe_name = self.storage.safe_stage_name(original_filename)
        staging_path = staging_dir / safe_name

        # Write in chunks to handle large files without loading entirely into memory.
        try:
            with open(staging_path, "wb") as dest:
                for chunk in iter(lambda: uploaded_file.read(1024 * 1024), b""):
                    dest.write(chunk)
        except Exception as exc:
            # Clean up partial write.
            if staging_path.exists():
                staging_path.unlink()
            raise BackupImportError(
                f"قرارداد فایل ناموفق بود: {sanitize_message(str(exc))}"
            ) from exc

        # Check size limit.
        size = staging_path.stat().st_size
        if size > self.MAX_IMPORT_SIZE:
            staging_path.unlink()
            raise BackupImportError(
                f"فایل بیش از حد بزرگ است ({size} بایت). "
                f"حد مجاز {self.MAX_IMPORT_SIZE} بایت است."
            )

        if size == 0:
            staging_path.unlink()
            raise BackupImportError("فایل آپلود شده خالی است.")

        return staging_path

    def _is_finalized(self, staging_path):
        """Check whether a staging path was already finalized (no longer exists)."""
        return not staging_path.exists()

    # ----------------------------------------------------------
    # Archive structure validation
    # ----------------------------------------------------------

    def _validate_archive_structure(self, archive_path):
        """Strictly validate the .dfbak TAR structure.

        Rejects:
        - Absolute paths
        - Path traversal (../)
        - Symlinks
        - Hard links
        - Device files
        - FIFOs
        - Sockets
        - Unexpected member count
        """
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            raise BackupImportError("فایل بایگانی خالی یا یافت نشد.")

        try:
            with tarfile.open(archive_path, "r") as archive:
                members = archive.getmembers()

                if not members:
                    raise BackupImportError("بایگانی خالی است.")

                if len(members) > self.MAX_ARCHIVE_MEMBERS:
                    raise BackupImportError(
                        f"بایگانی بیش از حد بزرگ است "
                        f"(تعداد عضوی: {len(members)})."
                    )

                for member in members:
                    # Reject non-regular files and directories.
                    if member.issym() or member.islnk():
                        raise BackupImportError(
                            f"پیوند در بایگانی مجاز نیست: {member.name!r}"
                        )

                    if member.isdev():
                        raise BackupImportError(
                            f"فایل دستگاه در بایگانی مجاز نیست: {member.name!r}"
                        )

                    if member.isfifo():
                        raise BackupImportError(
                            f"پایپ در بایگانی مجاز نیست: {member.name!r}"
                        )

                    if member.isblk():
                        raise BackupImportError(
                            f"فایل بلوک در بایگانی مجاز نیست: {member.name!r}"
                        )

                    if member.ischr():
                        raise BackupImportError(
                            f"فایل شخصیت در بایگانی مجاز نیست: {member.name!r}"
                        )

                    # Apply the existing _assert_safe_member checks.
                    _assert_safe_member(member)

                    # Only regular files allowed (directories rejected by _assert_safe_member).
                    if not member.isfile():
                        raise BackupImportError(
                            f"نوع عضو بایگانی مجاز نیست: {member.name!r}"
                        )

        except tarfile.TarError as exc:
            raise BackupImportError(
                sanitize_message(str(exc))
            ) from exc

    # ----------------------------------------------------------
    # Manifest validation
    # ----------------------------------------------------------

    def _validate_manifest(self, manifest):
        """Validate the manifest.json content.

        Uses the same validation rules as RestoreService._validate_archive().
        """
        if not isinstance(manifest, dict):
            raise BackupImportError("manifest.json ساختار معتبری ندارد.")

        if manifest.get("format") != BACKUP_FORMAT:
            raise BackupImportError(
                f"فرمت بایگانی ناشناخته است: {manifest.get('format')!r}"
            )

        if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
            raise BackupImportError(
                f"نسخه فرمت بایگانی پشتیبانی نمی‌شود: "
                f"{manifest.get('format_version')}."
            )

        if manifest.get("database_engine") != "postgresql":
            raise BackupImportError(
                "بایگانی مربوط به PostgreSQL نیست."
            )

        if manifest.get("database_backup_format") != "custom":
            raise BackupImportError(
                "فرمت dump پایگاه داده پشتیبانی نمی‌شود."
            )

        if not isinstance(manifest.get("includes_media"), bool):
            raise BackupImportError(
                "manifest شامل وضعیت رسانه معتبر نیست."
            )

        # Check product version compatibility.
        product_version = manifest.get("product_version", "")
        if not product_version:
            raise BackupImportError(
                "manifest فیلد product_version را ندارد."
            )

        # Define minimal compatibility check.
        # Same version or older compatible version is acceptable.
        # Newer format versions are rejected in format_version above.
        if not self._is_product_version_compatible(product_version):
            raise BackupImportError(
                f"نسخه محصول بایگانی با نسخه فعلی سازگار نیست: "
                f"{product_version}."
            )

    def _is_product_version_compatible(self, product_version):
        """Check if a product version is compatible with the current system.

        Current policy:
        - Same product version: compatible
        - Older semantic version (same major): compatible
        - Newer major version: incompatible (may have breaking changes)

        This is a minimal implementation. A proper migration framework would
        be needed for more complex scenarios.
        """
        current_version = "1.0.0"  # BACKUP_PRODUCT_VERSION from services.py

        try:
            current_parts = [int(p) for p in current_version.split(".")]
            imported_parts = [int(p) for p in product_version.split(".")]
        except (ValueError, AttributeError):
            # If we can't parse, be conservative and reject.
            return False

        # Same version is always compatible.
        if current_parts == imported_parts:
            return True

        # If we have at least major.minor, check major compatibility.
        if len(current_parts) >= 2 and len(imported_parts) >= 2:
            if current_parts[0] == imported_parts[0]:
                # Same major version — older minor/patch is compatible.
                return imported_parts <= current_parts
            else:
                # Different major version — reject.
                return False

        # Fallback: if we have only major version and it matches, compatible.
        if len(current_parts) >= 1 and len(imported_parts) >= 1:
            return current_parts[0] == imported_parts[0]

        return False

    # ----------------------------------------------------------
    # Database dump validation
    # ----------------------------------------------------------

    def _extract_member_to_temp(self, archive_path, member_name):
        """Extract a single member from the archive to a temporary location.

        Returns the path to the extracted file.
        """
        tmp_dir = Path(tempfile.mkdtemp(prefix="import_validate_"))
        dest_path = tmp_dir / member_name

        with tarfile.open(archive_path, "r") as archive:
            with archive.extractfile(member_name) as source, open(dest_path, "wb") as dest:
                shutil.copyfileobj(source, dest)

        return tmp_dir

    def _validate_database_dump(self, tmp_dir):
        """Validate database.dump using pg_restore --list."""
        dump_path = tmp_dir / DATABASE_FILENAME

        if not dump_path.exists():
            raise BackupImportError(
                "database.dump در بایگانی یافت نشد."
            )

        if dump_path.stat().st_size == 0:
            raise BackupImportError(
                "database.dump خالی است."
            )

        # Use pg_restore --list to validate the dump format.
        command = [
            self._pg_restore_binary(),
            "--list",
            str(dump_path),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise BackupImportError(
                "pg_restore قابل اجرا نیست: "
                + sanitize_message(str(exc))
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise BackupImportError(
                "دump پایگاه داده معتبر نیست؛ "
                "pg_restore قادر به خواندن آن نیست."
                + (" " + sanitize_message(detail) if detail else "")
            )

        if not (result.stdout or "").strip():
            raise BackupImportError(
                "دump پایگاه داده خالی است."
            )

    def _pg_restore_binary(self):
        configured = getattr(settings, "PG_RESTORE_PATH", "pg_restore")

        if configured != "pg_restore":
            return configured

        return shutil.which("pg_restore") or "pg_restore"

    # Use the same subprocess.run as the rest of the system so tests can mock it.
    # This is imported from the module level for testability.

    # ----------------------------------------------------------
    # Media archive validation
    # ----------------------------------------------------------

    def _validate_media_archive(self, tmp_dir):
        """Validate media.tar.gz structure without extracting to MEDIA_ROOT."""
        media_path = tmp_dir / MEDIA_FILENAME

        if not media_path.exists():
            raise BackupImportError(
                "media.tar.gz در بایگانی یافت نشد."
            )

        if media_path.stat().st_size == 0:
            raise BackupImportError(
                "media.tar.gz خالی است."
            )

        try:
            with tarfile.open(media_path, "r:gz") as archive:
                for member in archive.getmembers():
                    # Apply the same strict checks as restore.
                    _assert_safe_member(member)

        except tarfile.TarError as exc:
            raise BackupImportError(
                "بایگانی رسانه قابل خواندن نیست."
            ) from exc

    # ----------------------------------------------------------
    # Checksum calculation
    # ----------------------------------------------------------

    def _calculate_checksum(self, path):
        """Calculate SHA-256 of a file."""
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # ----------------------------------------------------------
    # Filename determination
    # ----------------------------------------------------------

    def _determine_filename(self, manifest, original_filename):
        """Determine the final backup filename.

        Prefers the filename from the manifest (created by the original system).
        Falls back to extracting from the original uploaded filename.
        """
        manifest_filename = manifest.get("filename")

        if manifest_filename and manifest_filename.endswith(".dfbak"):
            # Sanity-check the manifest filename.
            if Path(manifest_filename).name == manifest_filename:
                return manifest_filename

        # Fall back to parsing the original filename.
        # Expected format: DolphinFlow_Backup_YYYY-MM-DD_HHMMSS.dfbak
        name = Path(original_filename).name
        if name.endswith(".dfbak"):
            return name

        # Last resort: generate a new filename.
        return generate_backup_filename()

    # ----------------------------------------------------------
    # Backup record creation
    # ----------------------------------------------------------

    def _create_imported_backup(self, filename, manifest, checksum,
                                 database_size, media_size, user, staging_path):
        """Create a Backup record in IMPORTED state (not yet SUCCESS)."""
        backup = Backup.objects.create(
            filename=filename,
            status=Backup.Status.QUEUED,  # Temporary state before validation completes.
            source_type=Backup.SourceType.IMPORTED,
            includes_media=manifest.get("includes_media", False),
            database_size=database_size,
            media_size=media_size,
            checksum=checksum,
            created_by=user if user and user.is_authenticated else None,
            storage_path="",  # Not yet finalized.
        )

        return backup

    def _mark_imported_backup_success(self, backup, final_path, checksum,
                                       database_size, media_size):
        """Mark the imported backup as SUCCESS after validation and finalization."""
        backup.status = Backup.Status.SUCCESS
        backup.completed_at = timezone.now()
        backup.storage_path = Path(final_path).name
        backup.size = Path(final_path).stat().st_size
        backup.checksum = checksum
        backup.database_size = database_size
        backup.media_size = media_size
        backup.error_message = ""
        backup.save(
            update_fields=[
                "status",
                "completed_at",
                "storage_path",
                "size",
                "checksum",
                "database_size",
                "media_size",
                "error_message",
                "updated_at",
            ]
        )

        logger.info(
            "Imported backup %s (%s) validated and marked SUCCESS",
            backup.pk,
            backup.filename,
        )
