"""Validate and stage external .dfbak archives for restore."""

import hashlib
import logging
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import Backup, generate_backup_filename
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
from .storage import BackupImportError, LocalBackupStorage

logger = logging.getLogger(__name__)


class BackupImportService:
    """Validate an external .dfbak and promote it to a SUCCESS Backup."""

    MAX_IMPORT_SIZE = 1024 * 1024 * 1024
    MAX_ARCHIVE_MEMBERS = 200

    def __init__(self, storage=None):
        self.storage = storage or LocalBackupStorage()

    def import_backup(self, uploaded_file, original_filename, user=None):
        staging_path = None
        try:
            staging_path = self._stage_upload(uploaded_file, original_filename)
            self._validate_archive_structure(staging_path)
            manifest = read_manifest(staging_path)
            self._validate_manifest(manifest)

            dump_tmp_dir = self._extract_member_to_temp(staging_path, DATABASE_FILENAME)
            try:
                self._validate_database_dump(dump_tmp_dir)
                database_size = (dump_tmp_dir / DATABASE_FILENAME).stat().st_size
            finally:
                shutil.rmtree(dump_tmp_dir, ignore_errors=True)

            media_size = 0
            if manifest.get("includes_media"):
                media_tmp_dir = self._extract_member_to_temp(staging_path, MEDIA_FILENAME)
                try:
                    self._validate_media_archive(media_tmp_dir)
                    media_size = (media_tmp_dir / MEDIA_FILENAME).stat().st_size
                finally:
                    shutil.rmtree(media_tmp_dir, ignore_errors=True)
            else:
                with tarfile.open(staging_path, "r") as archive:
                    if any(member.name == MEDIA_FILENAME for member in archive.getmembers()):
                        raise BackupImportError(
                            "بایگانی حاوی فایل رسانه است در حالی که manifest رسانه را شامل نمی‌شود."
                        )

            checksum = self._calculate_checksum(staging_path)
            final_filename = self._determine_filename(manifest, original_filename)

            backup = self._create_imported_backup(
                filename=final_filename,
                manifest=manifest,
                checksum=checksum,
                database_size=database_size,
                media_size=media_size,
                user=user,
            )

            final_path = self.storage.finalize_import(staging_path, final_filename)
            staging_path = None
            self._mark_imported_backup_success(
                backup,
                final_path,
                checksum,
                database_size,
                media_size,
            )

            return {
                "backup": backup,
                "manifest": manifest,
                "checksum": checksum,
                "database_size": database_size,
                "media_size": media_size,
                "filename": backup.filename,
            }
        except BackupImportError:
            raise
        except RestoreError as exc:
            raise BackupImportError(str(exc)) from exc
        except Exception as exc:
            logger.exception("Import of %s failed unexpectedly", original_filename)
            raise BackupImportError(sanitize_message(str(exc))[:500]) from exc
        finally:
            if staging_path and staging_path.exists():
                try:
                    shutil.rmtree(staging_path.parent, ignore_errors=True)
                except Exception:
                    pass

    def _stage_upload(self, uploaded_file, original_filename):
        self.storage.ensure_root()
        staging_dir = Path(self.storage.root) / "tmp" / "import"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_path = staging_dir / self.storage.safe_stage_name(original_filename)
        try:
            with open(staging_path, "wb") as dest:
                for chunk in iter(lambda: uploaded_file.read(1024 * 1024), b""):
                    dest.write(chunk)
        except Exception as exc:
            if staging_path.exists():
                staging_path.unlink()
            raise BackupImportError(
                f"ذخیره فایل ناموفق بود: {sanitize_message(str(exc))}"
            ) from exc

        size = staging_path.stat().st_size
        if size == 0:
            staging_path.unlink()
            raise BackupImportError("فایل آپلود شده خالی است.")
        if size > self.MAX_IMPORT_SIZE:
            staging_path.unlink()
            raise BackupImportError(
                f"فایل بیش از حد بزرگ است ({size} بایت). حد مجاز {self.MAX_IMPORT_SIZE} بایت است."
            )
        return staging_path

    def _validate_archive_structure(self, archive_path):
        try:
            with tarfile.open(archive_path, "r") as archive:
                members = archive.getmembers()
                if not members:
                    raise BackupImportError("بایگانی خالی است.")
                if len(members) > self.MAX_ARCHIVE_MEMBERS:
                    raise BackupImportError(
                        f"بایگانی بیش از حد بزرگ است (تعداد عضو: {len(members)})."
                    )
                for member in members:
                    if member.issym() or member.islnk():
                        raise BackupImportError(f"پیوند در بایگانی مجاز نیست: {member.name!r}")
                    if member.isdev() or member.isfifo() or member.isblk() or member.ischr():
                        raise BackupImportError(f"نوع فایل غیرمجاز در بایگانی: {member.name!r}")
                    _assert_safe_member(member)
                    if not member.isfile():
                        raise BackupImportError(f"نوع عضو بایگانی مجاز نیست: {member.name!r}")
        except tarfile.TarError as exc:
            raise BackupImportError(sanitize_message(str(exc))) from exc

    def _validate_manifest(self, manifest):
        if not isinstance(manifest, dict):
            raise BackupImportError("manifest.json ساختار معتبری ندارد.")
        if manifest.get("format") != BACKUP_FORMAT:
            raise BackupImportError(f"فرمت بایگانی ناشناخته است: {manifest.get('format')!r}")
        if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
            raise BackupImportError(
                f"نسخه فرمت بایگانی پشتیبانی نمی‌شود: {manifest.get('format_version')}."
            )
        if manifest.get("database_engine") != "postgresql":
            raise BackupImportError("بایگانی مربوط به PostgreSQL نیست.")
        if manifest.get("database_backup_format") != "custom":
            raise BackupImportError("فرمت dump پایگاه داده پشتیبانی نمی‌شود.")
        if not isinstance(manifest.get("includes_media"), bool):
            raise BackupImportError("manifest شامل وضعیت رسانه معتبر نیست.")
        product_version = manifest.get("product_version", "")
        if not product_version or not self._is_product_version_compatible(product_version):
            raise BackupImportError(
                f"نسخه محصول بایگانی با نسخه فعلی سازگار نیست: {product_version}."
            )

    def _is_product_version_compatible(self, product_version):
        current_version = "1.0.0"
        try:
            current = [int(p) for p in current_version.split(".")]
            imported = [int(p) for p in str(product_version).split(".")]
        except (ValueError, AttributeError):
            return False
        if current == imported:
            return True
        if len(current) >= 2 and len(imported) >= 2:
            return current[0] == imported[0] and imported <= current
        return bool(current and imported and current[0] == imported[0])

    def _extract_member_to_temp(self, archive_path, member_name):
        tmp_dir = Path(tempfile.mkdtemp(prefix="import_validate_"))
        dest_path = tmp_dir / member_name
        try:
            with tarfile.open(archive_path, "r") as archive:
                member = archive.getmember(member_name)
                if not member.isfile():
                    raise BackupImportError(f"عضو مورد انتظار فایل نیست: {member_name}")
                source = archive.extractfile(member)
                if source is None:
                    raise BackupImportError(f"خواندن عضو بایگانی ممکن نیست: {member_name}")
                with source, open(dest_path, "wb") as dest:
                    shutil.copyfileobj(source, dest)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        return tmp_dir

    def _validate_database_dump(self, tmp_dir):
        dump_path = tmp_dir / DATABASE_FILENAME
        if not dump_path.exists() or dump_path.stat().st_size == 0:
            raise BackupImportError("database.dump خالی یا یافت نشد.")
        try:
            result = subprocess.run(
                [self._pg_restore_binary(), "--list", str(dump_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise BackupImportError("pg_restore قابل اجرا نیست: " + sanitize_message(str(exc))) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise BackupImportError(
                "dump پایگاه داده معتبر نیست؛ pg_restore قادر به خواندن آن نیست."
                + (" " + sanitize_message(detail) if detail else "")
            )
        if not (result.stdout or "").strip():
            raise BackupImportError("dump پایگاه داده خالی است.")

    def _pg_restore_binary(self):
        configured = getattr(settings, "PG_RESTORE_PATH", "pg_restore")
        if configured != "pg_restore":
            return configured
        return shutil.which("pg_restore") or "pg_restore"

    def _validate_media_archive(self, tmp_dir):
        media_path = tmp_dir / MEDIA_FILENAME
        if not media_path.exists() or media_path.stat().st_size == 0:
            raise BackupImportError("media.tar.gz خالی یا یافت نشد.")
        try:
            with tarfile.open(media_path, "r:gz") as archive:
                for member in archive.getmembers():
                    _assert_safe_member(member)
        except tarfile.TarError as exc:
            raise BackupImportError("بایگانی رسانه قابل خواندن نیست.") from exc

    def _calculate_checksum(self, path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _determine_filename(self, manifest, original_filename):
        manifest_filename = manifest.get("filename")
        if manifest_filename and manifest_filename.endswith(".dfbak"):
            if Path(manifest_filename).name == manifest_filename:
                return manifest_filename
        name = Path(original_filename).name
        return name if name.endswith(".dfbak") else generate_backup_filename()

    def _create_imported_backup(self, filename, manifest, checksum, database_size, media_size, user):
        return Backup.objects.create(
            filename=filename,
            status=Backup.Status.QUEUED,
            source_type=Backup.SourceType.IMPORTED,
            includes_media=bool(manifest.get("includes_media")),
            database_size=database_size,
            media_size=media_size,
            checksum=checksum,
            created_by=user if user and user.is_authenticated else None,
            storage_path="",
        )

    def _mark_imported_backup_success(self, backup, final_path, checksum, database_size, media_size):
        backup.status = Backup.Status.SUCCESS
        backup.completed_at = timezone.now()
        backup.storage_path = Path(final_path).name
        backup.size = Path(final_path).stat().st_size
        backup.checksum = checksum
        backup.database_size = database_size
        backup.media_size = media_size
        backup.error_message = ""
        backup.save(update_fields=[
            "status", "completed_at", "storage_path", "size", "checksum",
            "database_size", "media_size", "error_message", "updated_at",
        ])
        logger.info("Imported backup %s (%s) validated and marked SUCCESS", backup.pk, backup.filename)
