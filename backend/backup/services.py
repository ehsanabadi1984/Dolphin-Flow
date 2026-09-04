"""
Backup execution service.

Flow (all asynchronous, inside a Celery task):

    acquire execution slot (concurrency guard)
        -> status RUNNING
        -> pg_dump (PostgreSQL custom format)        -> database.dump
        -> media archive                              -> media.tar.gz
        -> manifest.json
        -> build .dfbak (tar containing the three files)
        -> SHA-256 checksum
        -> structural validation
        -> atomic rename into BACKUP_ROOT
        -> status SUCCESS
    on error
        -> status FAILED with a sanitized error message
        -> temporary files cleaned up

The service never exposes database credentials in messages or the manifest.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Backup, Restore
from .storage import BackupStorageError, LocalBackupStorage

logger = logging.getLogger(__name__)

#: Version of the backup archive format (bump on breaking format changes).
BACKUP_FORMAT = "dolphin-flow-backup"
BACKUP_FORMAT_VERSION = 1
BACKUP_PRODUCT_VERSION = "1.0.0"

MANIFEST_FILENAME = "manifest.json"
DATABASE_FILENAME = "database.dump"
MEDIA_FILENAME = "media.tar.gz"


class BackupError(Exception):
    """A failure in the backup pipeline with a user-safe message."""


def sanitize_message(message):
    """Remove known database connection details from any surfaced text."""
    if not message:
        return message

    database = settings.DATABASES["default"]
    secrets = [
        database.get("PASSWORD"),
        database.get("USER"),
        database.get("NAME"),
        database.get("HOST"),
    ]

    sanitized = str(message)

    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(str(secret), "***")

    return sanitized


class BackupService:
    def __init__(self, backup, storage=None):
        self.backup = backup
        self.storage = storage or LocalBackupStorage()

    # ----------------------------------------------------------
    # Entry point
    # ----------------------------------------------------------

    def run(self):
        """Execute the full backup pipeline for ``self.backup``."""
        # Only a QUEUED backup is claimable below; RUNNING/SUCCESS/FAILED
        # must never restart the pipeline.
        if self.backup.status != Backup.Status.QUEUED:
            return {
                "status": self.backup.status,
                "backup_id": self.backup.pk,
            }

        try:
            claimed = self._acquire_execution_slot()
        except BackupError as exc:
            self._mark_failed(str(exc))
            return {"status": self.backup.status, "backup_id": self.backup.pk}

        if not claimed:
            # Another invocation claimed this backup (it is already RUNNING
            # in the database); do not start a second pipeline.
            self.backup.refresh_from_db()
            return {"status": self.backup.status, "backup_id": self.backup.pk}

        tmp_dir = None

        try:
            tmp_dir = self._make_temp_dir()

            database_path = tmp_dir / DATABASE_FILENAME
            self._dump_database(database_path)

            include_media = self.backup.includes_media
            media_path = tmp_dir / MEDIA_FILENAME

            if include_media:
                self._create_media_archive(media_path)
                media_size = media_path.stat().st_size
            else:
                media_size = 0

            manifest_path = tmp_dir / MANIFEST_FILENAME
            self._write_manifest(
                manifest_path,
                database_size=database_path.stat().st_size,
                media_size=media_size,
            )

            members = [
                (manifest_path, MANIFEST_FILENAME),
                (database_path, DATABASE_FILENAME),
            ]

            if include_media:
                members.append((media_path, MEDIA_FILENAME))

            archive_path = tmp_dir / "backup.dfbak"
            self._build_archive(archive_path, *members)

            checksum = self._calculate_checksum(archive_path)
            self._validate_archive(archive_path)

            final_path = self.storage.finalize(
                archive_path,
                self.backup.filename,
            )

            self._mark_success(
                final_path=final_path,
                checksum=checksum,
                database_size=database_path.stat().st_size,
                media_size=media_size,
            )

        except BackupError as exc:
            logger.warning(
                "Backup #%s failed: %s",
                self.backup.pk,
                exc,
            )
            self._mark_failed(str(exc))

        except BackupStorageError as exc:
            logger.warning(
                "Backup #%s storage failure: %s",
                self.backup.pk,
                exc,
            )
            self._mark_failed(str(exc))

        except Exception as exc:  # report any unexpected failure
            logger.exception("Backup #%s failed unexpectedly", self.backup.pk)
            self._mark_failed(self._sanitize_message(str(exc)))

        finally:
            self._cleanup_temp_dir(tmp_dir)

        return {"status": self.backup.status, "backup_id": self.backup.pk}

    # ----------------------------------------------------------
    # Concurrency guard
    # ----------------------------------------------------------

    def _acquire_execution_slot(self):
        """Claim the single execution slot.

        Returns ``True`` when this invocation claimed the slot (transitioned
        the backup QUEUED -> RUNNING), or ``False`` when the backup is already
        RUNNING (duplicate task delivery or a concurrent worker claimed it) and
        must not be restarted. Raises ``BackupError`` when a different backup
        currently holds the slot.

        Uses a ``SELECT ... FOR UPDATE`` over queued/running backups so that
        concurrent workers serialize on the database row.
        """
        with transaction.atomic():
            active = list(
                Backup.objects.select_for_update()
                .filter(
                    status__in=(
                        Backup.Status.QUEUED,
                        Backup.Status.RUNNING,
                    )
                )
                .order_by("pk")
            )

            self_row = next(
                (
                    row
                    for row in active
                    if row.pk == self.backup.pk
                ),
                None,
            )

            if self_row is None or self_row.status == Backup.Status.RUNNING:
                # Already claimed by this or another invocation (or moved to a
                # terminal state) while we waited for the lock. Never restart.
                return False

            others = [row for row in active if row.pk != self.backup.pk]

            if others:
                # Only the oldest queued/running backup may claim the slot.
                # Any other queued backups are rejected so a burst of clicks
                # cannot start several expensive pg_dump/media runs.
                if active[0].pk != self.backup.pk:
                    raise BackupError(
                        "پشتیبان‌گیری دیگری در حال اجراست؛ "
                        "پس از اتمام آن دوباره تلاش کنید."
                    )

                now = timezone.now()
                Backup.objects.filter(
                    pk__in=[row.pk for row in others]
                ).update(
                    status=Backup.Status.FAILED,
                    completed_at=now,
                    error_message=(
                        "پشتیبان‌گیری دیگری در حال اجراست؛ "
                        "این پشتیبان لغو شد."
                    ),
                    updated_at=now,
                )

            # Never snapshot the database while a Restore is rewriting it.
            # The only backup allowed to run during a Restore is that
            # Restore's own automatic pre-restore safety snapshot. Plain
            # (non-locking) read on purpose: the Restore slot locks Restore
            # rows and then Backup rows, so locking Restore rows here could
            # deadlock.
            if (
                not self.backup.is_pre_restore_backup
                and Restore.objects.filter(
                    status=Restore.Status.RESTORING
                ).exists()
            ):
                raise BackupError(
                    "بازیابی (Restore) در حال اجراست؛ "
                    "ایجاد پشتیبان هم‌زمان ممکن نیست."
                )

            self.backup.status = Backup.Status.RUNNING
            self.backup.started_at = timezone.now()
            self.backup.save(
                update_fields=[
                    "status",
                    "started_at",
                    "updated_at",
                ]
            )

            return True

    # ----------------------------------------------------------
    # Pipeline steps
    # ----------------------------------------------------------

    def _make_temp_dir(self):
        self.storage.ensure_root()
        root = Path(self.storage.root)
        tmp_root = root / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)

        token = hashlib.sha1(
            f"{self.backup.pk}-{timezone.now().timestamp()}".encode()
        ).hexdigest()[:12]

        tmp_dir = tmp_root / f"backup-{self.backup.pk}-{token}"
        tmp_dir.mkdir(parents=True)
        return tmp_dir

    def _pg_dump_binary(self):
        configured = getattr(settings, "PG_DUMP_PATH", "pg_dump")

        if configured != "pg_dump":
            return configured

        return shutil.which("pg_dump") or "pg_dump"

    def _dump_database(self, dest_path):
        database = settings.DATABASES["default"]

        command = [
            self._pg_dump_binary(),
            "--format=custom",
            "--file",
            str(dest_path),
        ]

        if database.get("HOST"):
            command += ["--host", database["HOST"]]
        if database.get("PORT"):
            command += ["--port", str(database["PORT"])]
        if database.get("USER"):
            command += ["--username", database["USER"]]

        command += ["--dbname", database["NAME"]]

        env = os.environ.copy()

        # Credentials travel only through the environment, never argv.
        if database.get("PASSWORD"):
            env["PGPASSWORD"] = database["PASSWORD"]

        try:
            result = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise BackupError(
                f"pg_dump قابل اجرا نیست: {self._sanitize_message(str(exc))}"
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise BackupError(
                "ایجاد dump پایگاه داده ناموفق بود. "
                + self._sanitize_message(detail)
            )

        if not dest_path.exists() or dest_path.stat().st_size == 0:
            raise BackupError(
                "dump پایگاه داده ایجاد نشد یا خالی است."
            )

    def _create_media_archive(self, dest_path):
        """Archive ``MEDIA_ROOT`` into ``media.tar.gz``.

        An empty or missing media directory still produces a valid (empty)
        archive so the backup succeeds. Anything located under ``BACKUP_ROOT``
        is excluded so backups never contain themselves.
        """
        media_root = Path(settings.MEDIA_ROOT).resolve()
        backup_root = Path(settings.BACKUP_ROOT).resolve()

        with tarfile.open(dest_path, "w:gz") as archive:
            if not media_root.exists() or not media_root.is_dir():
                return

            entries = sorted(
                entry
                for entry in media_root.rglob("*")
                if entry.is_file()
            )

            for entry in entries:
                resolved = entry.resolve()

                if resolved == backup_root or backup_root in resolved.parents:
                    continue

                arcname = resolved.relative_to(media_root).as_posix()
                archive.add(
                    resolved,
                    arcname=arcname,
                    recursive=False,
                )

    def _write_manifest(self, path, *, database_size, media_size):
        manifest = {
            "format": BACKUP_FORMAT,
            "format_version": BACKUP_FORMAT_VERSION,
            "product_version": BACKUP_PRODUCT_VERSION,
            "backup_id": self.backup.pk,
            "filename": self.backup.filename,
            "created_at": self.backup.started_at.isoformat()
            if self.backup.started_at
            else timezone.now().isoformat(),
            "created_by": (
                self.backup.created_by.get_username()
                if self.backup.created_by_id
                else None
            ),
            "database_engine": "postgresql",
            "database_backup_format": "custom",
            "includes_media": self.backup.includes_media,
            "database_size": database_size,
            "media_size": media_size,
        }

        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_archive(self, dest_path, *members):
        """Assemble ``.dfbak``: an uncompressed tar of manifest/dump/media.

        Members are written in a fixed order with a fixed mtime so the
        archive layout is deterministic for a given backup.
        """
        mtime = (
            int(self.backup.started_at.timestamp())
            if self.backup.started_at
            else int(timezone.now().timestamp())
        )

        with tarfile.open(dest_path, "w") as archive:
            for source_path, arcname in members:
                info = archive.gettarinfo(
                    str(source_path),
                    arcname=arcname,
                )
                info.mtime = mtime
                with open(source_path, "rb") as source:
                    archive.addfile(info, fileobj=source)

    def _calculate_checksum(self, path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _validate_archive(self, archive_path):
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            raise BackupError(
                "فایل بایگانی نهایی ایجاد نشد یا خالی است."
            )

        try:
            with tarfile.open(archive_path, "r") as archive:
                names = set(archive.getnames())

                required = [
                    MANIFEST_FILENAME,
                    DATABASE_FILENAME,
                ]

                if self.backup.includes_media:
                    required.append(MEDIA_FILENAME)

                for required_name in required:
                    if required_name not in names:
                        raise BackupError(
                            f"بایگانی نهایی فاقد {required_name} است."
                        )

                try:
                    manifest_raw = archive.extractfile(
                        MANIFEST_FILENAME
                    ).read()
                    manifest = json.loads(manifest_raw)
                except (ValueError, TypeError, KeyError) as exc:
                    raise BackupError(
                        "manifest.json در بایگانی نهایی معتبر نیست."
                    ) from exc

                if manifest.get("format") != BACKUP_FORMAT:
                    raise BackupError(
                        "فرمت بایگانی نهایی ناشناخته است."
                    )

                if (
                    manifest.get("includes_media")
                    != self.backup.includes_media
                ):
                    raise BackupError(
                        "manifest شامل وضعیت ناسازگار رسانه است."
                    )

                members_to_check = [DATABASE_FILENAME]

                if self.backup.includes_media:
                    members_to_check.append(MEDIA_FILENAME)

                for member_name in members_to_check:
                    member = archive.getmember(member_name)
                    if member.size <= 0:
                        raise BackupError(
                            f"{member_name} در بایگانی نهایی خالی است."
                        )

        except tarfile.TarError as exc:
            raise BackupError(
                "بایگانی نهایی قابل خواندن نیست."
            ) from exc

    # ----------------------------------------------------------
    # Completion
    # ----------------------------------------------------------

    def _mark_success(
        self,
        *,
        final_path,
        checksum,
        database_size,
        media_size,
    ):
        self.backup.status = Backup.Status.SUCCESS
        self.backup.completed_at = timezone.now()
        self.backup.storage_path = Path(final_path).name
        self.backup.size = Path(final_path).stat().st_size
        self.backup.database_size = database_size
        self.backup.media_size = media_size
        self.backup.checksum = checksum
        self.backup.error_message = ""
        self.backup.save(
            update_fields=[
                "status",
                "completed_at",
                "storage_path",
                "size",
                "database_size",
                "media_size",
                "checksum",
                "error_message",
                "updated_at",
            ]
        )

    def _mark_failed(self, message):
        self.backup.status = Backup.Status.FAILED
        self.backup.completed_at = timezone.now()
        self.backup.error_message = self._sanitize_message(message)[:1000]
        self.backup.save(
            update_fields=[
                "status",
                "completed_at",
                "error_message",
                "updated_at",
            ]
        )

    def _cleanup_temp_dir(self, tmp_dir):
        if not tmp_dir:
            return

        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ----------------------------------------------------------
    # Safety helpers
    # ----------------------------------------------------------

    def _sanitize_message(self, message):
        return sanitize_message(message)