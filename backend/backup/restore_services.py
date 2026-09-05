"""
Restore execution service (Phase 2).

Pipeline (asynchronous, inside a Celery task):

    duplicate-delivery guard
        -> claim the single restore slot (concurrency guard)
        -> status RESTORING
        -> automatic pre-restore safety backup (a normal ``.dfbak`` created
           through BackupService and flagged ``is_pre_restore_backup``)
        -> validate the archive (structure + manifest) again
        -> validate database.dump via ``pg_restore --list``
        -> ``pg_restore`` into the configured database (credentials only via env)
        -> post-restore database validation
        -> media restore (guarded extraction into MEDIA_ROOT)
        -> terminal status SUCCESS / FAILED

Restoring the database replaces the current database contents, including the
rows of the Backup/Restore models themselves. Terminal status is therefore
recorded either on the original Restore row (when it still exists) or on a
freshly created audit row inside the restored database; nothing is logged that
contains credentials.

A complete atomic rollback of both the database and the media filesystem is
not possible (they are not part of one transaction); on failure the worker
reports exactly which stage failed so a partial result is never presented as a
full success.
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
from django.db import connection, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from .models import Backup, Restore, generate_backup_filename
from .services import (
    BACKUP_FORMAT,
    BACKUP_FORMAT_VERSION,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MEDIA_FILENAME,
    BackupError,
    BackupService,
    sanitize_message,
)
from .storage import BackupStorageError, LocalBackupStorage
from .version_detection import (
    detect_pg_restore_version,
    extract_major_version,
    pg_restore_supports_version_flag,
)

logger = logging.getLogger(__name__)

#: pg_restore flags. ``--clean --if-exists`` recreate objects inside the
#: configured database (no DROP DATABASE, so the running application database
#: is reused). ``--no-owner``/``--no-privileges`` keep the archive portable
#: across machines whose database role differs from the origin machine.
#: ``--exit-on-error`` stops at the first failure instead of skipping objects.
PG_RESTORE_OPTIONS = [
    "--clean",
    "--if-exists",
    "--no-owner",
    "--no-privileges",
    "--exit-on-error",
]

#: Tables that must be readable after a restore for it to count as validated.
POST_RESTORE_REQUIRED_TABLES = (
    "django_migrations",
    "accounts_user",
)


class RestoreError(Exception):
    """A failure in the restore pipeline with a user-safe message."""


def _assert_safe_member(member):
    """Reject archive members that could escape the extraction directory."""
    name = member.name
    if not name:
        raise RestoreError("عضو بایگانی بدون نام یافت شد.")

    path = Path(name)
    if path.is_absolute():
        raise RestoreError(
            f"مسیر مطلق در بایگانی مجاز نیست: {name!r}"
        )
    if ".." in path.parts:
        raise RestoreError(
            f"مسیر ناامن در بایگانی مجاز نیست: {name!r}"
        )

    # Only regular files and directories are accepted; symlinks, hard links
    # and special files are rejected outright so extraction can never follow
    # or create links that point outside the extraction root.
    if not (member.isfile() or member.isdir()):
        raise RestoreError(
            f"نوع عضو بایگانی مجاز نیست: {name!r}"
        )


def read_manifest(archive_path):
    """Lightweight manifest reader used by the admin preview page.

    Non-destructive: only reads ``manifest.json`` from the archive.
    """
    archive_path = Path(archive_path)
    if not archive_path.exists() or archive_path.stat().st_size == 0:
        raise RestoreError("فایل بایگانی یافت نشد یا خالی است.")

    try:
        with tarfile.open(archive_path, "r") as archive:
            names = archive.getnames()
            if MANIFEST_FILENAME not in names:
                raise RestoreError(
                    "بایگانی فاقد manifest.json است."
                )
            raw = archive.extractfile(MANIFEST_FILENAME).read()
    except tarfile.TarError as exc:
        raise RestoreError(
            "بایگانی قابل خواندن نیست."
        ) from exc

    try:
        manifest = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise RestoreError(
            "manifest.json در بایگانی معتبر نیست."
        ) from exc

    if not isinstance(manifest, dict):
        raise RestoreError("manifest.json ساختار معتبری ندارد.")

    return manifest


class RestoreService:
    """Execute the restore pipeline for a ``Restore`` record.

    ``archive_path`` may be passed explicitly (used by tests and suitable for
    future network/cloud sources that hand the service a local archive path);
    when omitted it is resolved from ``restore.backup`` through the active
    storage backend.
    """

    def __init__(self, restore, storage=None, archive_path=None):
        self.restore = restore
        self.storage = storage or LocalBackupStorage()
        self.archive_path = archive_path
        self._tmp_dir = None
        self._manifest = None
        self._safety_backup_pk = None
        self._safety_snapshot = None

    # ----------------------------------------------------------
    # Entry point
    # ----------------------------------------------------------

    def run(self):
        """Execute the full restore pipeline for ``self.restore``."""
        # Only a QUEUED restore is claimable; RESTORING/SUCCESS/FAILED must
        # never start (or restart) the destructive pipeline.
        if self.restore.status != Restore.Status.QUEUED:
            return {
                "status": self.restore.status,
                "restore_id": self.restore.pk,
            }

        try:
            claimed = self._claim_slot()
        except RestoreError as exc:
            self._mark_terminal(
                Restore.Status.FAILED,
                str(exc),
            )
            return {
                "status": self.restore.status,
                "restore_id": self.restore.pk,
            }

        if not claimed:
            # Another invocation claimed this restore (already RESTORING in
            # the database); never run a second destructive pipeline.
            self.restore.refresh_from_db()
            return {
                "status": self.restore.status,
                "restore_id": self.restore.pk,
            }

        try:
            archive = self._resolve_archive_path()
            self._verify_checksum(archive)
            self._manifest = self._validate_archive(archive)

            # Check pg_restore and archive client compatibility BEFORE any
            # destructive operation (including safety backup).
            self._check_version_compatibility()

            safety_backup = self._create_safety_backup(self._manifest)
            self._safety_backup_pk = safety_backup.pk
            self._safety_snapshot = self._capture_backup_state(safety_backup)
            self.restore.pre_restore_backup = safety_backup
            self.restore.pre_restore_backup_filename = safety_backup.filename
            self.restore.save(
                update_fields=[
                    "pre_restore_backup",
                    "pre_restore_backup_filename",
                    "updated_at",
                ]
            )

            dump_path, media_path = self._materialize(archive)
            self._validate_dump_file(dump_path)

            if self._manifest["includes_media"]:
                # Reject malicious media members before the destructive DB
                # restore starts, so a bad nested archive cannot trigger a
                # needless database replacement.
                self._prevalidate_media(media_path)

            self._run_pg_restore(dump_path)
            self._post_restore_db_check()

            if self._manifest["includes_media"]:
                self._restore_media(media_path)

            self._recreate_safety_backup_row()
            self._mark_terminal(Restore.Status.SUCCESS, "")

        except RestoreError as exc:
            logger.warning(
                "Restore #%s failed: %s",
                self.restore.pk,
                exc,
            )
            self._mark_terminal(Restore.Status.FAILED, str(exc))

        except Exception as exc:  # report any unexpected failure
            logger.exception(
                "Restore #%s failed unexpectedly",
                self.restore.pk,
            )
            self._mark_terminal(
                Restore.Status.FAILED,
                sanitize_message(str(exc)),
            )

        finally:
            self._cleanup_temp_dir()

        return {
            "status": self.restore.status,
            "restore_id": self.restore.pk,
        }

    # ----------------------------------------------------------
    # Concurrency guard
    # ----------------------------------------------------------

    def _claim_slot(self):
        """Claim the single restore slot.

        Returns ``True`` when this invocation claimed the slot (QUEUED ->
        RESTORING), or ``False`` when the restore is already RESTORING
        (duplicate task delivery). Raises ``RestoreError`` when another
        restore or a backup currently holds the system busy.

        Locks Restore rows and then Backup rows (in that order). The backup
        slot locks Backup rows and only *reads* Restore rows without locking,
        so there is no lock cycle between the two guards.
        """
        with transaction.atomic():
            active = list(
                Restore.objects.select_for_update()
                .filter(
                    status__in=(
                        Restore.Status.QUEUED,
                        Restore.Status.RESTORING,
                    )
                )
                .order_by("pk")
            )

            self_row = next(
                (
                    row
                    for row in active
                    if row.pk == self.restore.pk
                ),
                None,
            )

            if self_row is None or self_row.status == Restore.Status.RESTORING:
                return False

            others = [
                row for row in active if row.pk != self.restore.pk
            ]

            if others:
                raise RestoreError(
                    "بازیابی دیگری در حال اجراست یا در صف است؛ "
                    "پس از اتمام آن دوباره تلاش کنید."
                )

            active_backups = list(
                Backup.objects.select_for_update()
                .filter(
                    status__in=(
                        Backup.Status.QUEUED,
                        Backup.Status.RUNNING,
                    )
                )
                .order_by("pk")
            )

            if active_backups:
                raise RestoreError(
                    "هم‌اکنون یک پشتیبان‌گیری در حال اجراست یا در صف است؛ "
                    "ابتدا آن را متوقف کنید و سپس بازیابی را آغاز کنید."
                )

            self.restore.status = Restore.Status.RESTORING
            self.restore.started_at = timezone.now()
            self.restore.save(
                update_fields=[
                    "status",
                    "started_at",
                    "updated_at",
                ]
            )

            return True

    # ----------------------------------------------------------
    # Archive source / validation
    # ----------------------------------------------------------

    def _resolve_archive_path(self):
        if self.archive_path:
            path = Path(self.archive_path)
        else:
            backup = self.restore.backup

            if not backup or not backup.storage_path:
                raise RestoreError(
                    "منبع بایگانی بازیابی مشخص نیست."
                )

            try:
                path = self.storage.path_for(backup.storage_path)
            except BackupStorageError as exc:
                raise RestoreError(str(exc)) from exc

        if not path.exists() or not path.is_file():
            raise RestoreError(
                "فایل بایگانی بازیابی یافت نشد."
            )

        return path

    def _verify_checksum(self, archive_path):
        """Verify the archive against the recorded SHA-256 when one exists."""
        backup = self.restore.backup

        if not backup or not backup.checksum:
            return

        digest = hashlib.sha256()
        with open(archive_path, "rb") as handle:
            for chunk in iter(
                lambda: handle.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        if digest.hexdigest() != backup.checksum:
            raise RestoreError(
                "checksum بایگانی با مقدار ثبت‌شده در سامانه "
                "ناسازگار است؛ فایل تغییر کرده یا خراب است."
            )

    def _validate_archive(self, archive_path):
        """Validate the ``.dfbak`` structure and manifest before restoring."""
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            raise RestoreError(
                "فایل بایگانی بازیابی یافت نشد یا خالی است."
            )

        try:
            with tarfile.open(archive_path, "r") as archive:
                members = archive.getmembers()

                if not members:
                    raise RestoreError(
                        "بایگانی بازیابی خالی است."
                    )

                member_names = set()

                for member in members:
                    _assert_safe_member(member)
                    if not member.isfile():
                        raise RestoreError(
                            "بایگانی بازیابی باید فقط شامل فایل‌های "
                            "عادی باشد."
                        )
                    member_names.add(member.name)

                manifest = read_manifest(archive_path)

                if manifest.get("format") != BACKUP_FORMAT:
                    raise RestoreError(
                        "فرمت بایگانی بازیابی ناشناخته است."
                    )

                if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
                    raise RestoreError(
                        "نسخه فرمت بایگانی بازیابی پشتیبانی نمی‌شود."
                    )

                if manifest.get("database_engine") != "postgresql":
                    raise RestoreError(
                        "بایگانی بازیابی مربوط به PostgreSQL نیست."
                    )

                if manifest.get("database_backup_format") != "custom":
                    raise RestoreError(
                        "فرمت dump پایگاه داده در بایگانی پشتیبانی نمی‌شود."
                    )

                if not isinstance(
                    manifest.get("includes_media"),
                    bool,
                ):
                    raise RestoreError(
                        "manifest شامل وضعیت رسانه معتبر نیست."
                    )

                expected = {MANIFEST_FILENAME, DATABASE_FILENAME}
                if manifest["includes_media"]:
                    expected.add(MEDIA_FILENAME)

                if member_names != expected:
                    missing = sorted(expected - member_names)
                    extra = sorted(member_names - expected)
                    raise RestoreError(
                        "ساختار بایگانی بازیابی معتبر نیست"
                        + (
                            f"؛ فاقد {', '.join(missing)} است"
                            if missing
                            else ""
                        )
                        + (
                            f"؛ شامل عضو ناشناخته {', '.join(extra)} است"
                            if extra
                            else ""
                        )
                        + "."
                    )

                if archive.getmember(DATABASE_FILENAME).size <= 0:
                    raise RestoreError(
                        "database.dump در بایگانی خالی است."
                    )

                if (
                    manifest["includes_media"]
                    and archive.getmember(MEDIA_FILENAME).size <= 0
                ):
                    raise RestoreError(
                        "media.tar.gz در بایگانی خالی است."
                    )

        except tarfile.TarError as exc:
            raise RestoreError(
                "بایگانی بازیابی قابل خواندن نیست."
            ) from exc

        return manifest

    def _make_temp_dir(self):
        self.storage.ensure_root()
        root = Path(self.storage.root)
        tmp_root = root / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)

        token = hashlib.sha1(
            f"{self.restore.pk}-{timezone.now().timestamp()}".encode()
        ).hexdigest()[:12]

        tmp_dir = tmp_root / f"restore-{self.restore.pk}-{token}"
        tmp_dir.mkdir(parents=True)
        return tmp_dir

    def _materialize(self, archive_path):
        """Copy database.dump (and media.tar.gz) out of the archive."""
        if self._tmp_dir is None:
            self._tmp_dir = self._make_temp_dir()

        dump_path = self._tmp_dir / DATABASE_FILENAME
        media_path = self._tmp_dir / MEDIA_FILENAME

        with tarfile.open(archive_path, "r") as archive:
            with archive.extractfile(
                DATABASE_FILENAME
            ) as source, open(dump_path, "wb") as dest:
                shutil.copyfileobj(source, dest)

            if self._manifest["includes_media"]:
                with archive.extractfile(
                    MEDIA_FILENAME
                ) as source, open(media_path, "wb") as dest:
                    shutil.copyfileobj(source, dest)
            else:
                media_path = None

        return dump_path, media_path

    # ----------------------------------------------------------
    # PostgreSQL tooling
    # ----------------------------------------------------------

    def _pg_restore_binary(self):
        configured = getattr(
            settings,
            "PG_RESTORE_PATH",
            "pg_restore",
        )

        if configured != "pg_restore":
            return configured

        return shutil.which("pg_restore") or "pg_restore"

    def _check_version_compatibility(self):
        """Check pg_restore/ archive client compatibility before any destructive operation.

        This must run before the safety backup so we reject incompatible
        archives early.
        """
        pg_restore_binary = self._pg_restore_binary()
        pg_restore_version = detect_pg_restore_version(pg_restore_binary)
        pg_restore_major = extract_major_version(pg_restore_version)

        # Check pg_restore and archive client compatibility.
        manifest = self._manifest
        archive_pg_dump_major = manifest.get("pg_dump_major_version")

        if pg_restore_major is not None and archive_pg_dump_major is not None:
            if archive_pg_dump_major > pg_restore_major:
                raise RestoreError(
                    "این بایگانی با pg_dump نسخه بالاتر از pg_restore فعلی شما "
                    "ساخته شده است. برای بازیابی، نیاز به نصب نسخه جدیدتر "
                    "PostgreSQL دارید."
                )

    def _validate_dump_file(self, dump_path):
        """Validate the custom-format dump using ``pg_restore --list``.

        ``--list`` only reads the archive; it does not connect to a database.
        """
        pg_restore_binary = self._pg_restore_binary()

        command = [
            pg_restore_binary,
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
            raise RestoreError(
                "pg_restore قابل اجرا نیست: "
                + sanitize_message(str(exc))
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()

            # Translate specific pg_restore version errors to clear Persian messages.
            if "unsupported version" in detail.lower() and "in file header" in detail.lower():
                raise RestoreError(
                    "نسخه بایگانی پایگاه داده با pg_restore فعلی شما سازگار نیست. "
                    "بایگانی با نسخه جدیدتر PostgreSQL ساخته شده و با ابزار فعلی شما خوانده نمی‌شود. "
                    "لطفاً pg_restore جدیدتر نصب کنید."
                )

            raise RestoreError(
                "بایگانی پایگاه داده معتبر نیست؛ "
                "pg_restore قادر به خواندن آن نیست. "
                + sanitize_message(detail)
            )

        if not (result.stdout or "").strip():
            raise RestoreError(
                "بایگانی پایگاه داده خالی است."
            )

    def _run_pg_restore(self, dump_path):
        database = settings.DATABASES["default"]

        command = [
            self._pg_restore_binary(),
            *PG_RESTORE_OPTIONS,
        ]

        if database.get("HOST"):
            command += ["--host", database["HOST"]]
        if database.get("PORT"):
            command += ["--port", str(database["PORT"])]
        if database.get("USER"):
            command += ["--username", database["USER"]]

        command += ["--dbname", database["NAME"], str(dump_path)]

        env = os.environ.copy()

        # Credentials travel only through the environment, never argv.
        if database.get("PASSWORD"):
            env["PGPASSWORD"] = database["PASSWORD"]

        # Any failure from this point on may have left the database partially
        # restored; terminal status recording must tolerate that.
        try:
            result = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise RestoreError(
                "pg_restore قابل اجرا نیست: "
                + sanitize_message(str(exc))
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RestoreError(
                "بازیابی پایگاه داده ناموفق بود. "
                + sanitize_message(detail)
            )

    def _prevalidate_media(self, media_gz_path):
        """Scan media.tar.gz members for safety before the DB restore.

        Mirrors the checks applied again during actual extraction so a
        malicious media archive is rejected before any destructive step.
        """
        try:
            with tarfile.open(media_gz_path, "r:gz") as archive:
                for member in archive.getmembers():
                    _assert_safe_member(member)
        except tarfile.TarError as exc:
            raise RestoreError(
                "بایگانی رسانه قابل خواندن نیست."
            ) from exc

    # ----------------------------------------------------------
    # Post-restore checks
    # ----------------------------------------------------------

    def _post_restore_db_check(self):
        """Lightweight validation that the restored database is usable."""
        try:
            with connection.cursor() as cursor:
                for table in POST_RESTORE_REQUIRED_TABLES:
                    cursor.execute(
                        "SELECT to_regclass(%s) IS NOT NULL",
                        [table],
                    )
                    if not cursor.fetchone()[0]:
                        raise RestoreError(
                            "پس از بازیابی، جدول "
                            f"«{table}» در پایگاه داده یافت نشد."
                        )

                cursor.execute(
                    "SELECT count(*) FROM django_migrations"
                )
                if not cursor.fetchone()[0]:
                    raise RestoreError(
                        "پس از بازیابی، سوابق مهاجرت‌ها (migrations) "
                        "در پایگاه داده خالی است."
                    )
        except RestoreError:
            raise
        except (OperationalError, ProgrammingError) as exc:
            raise RestoreError(
                "پس از بازیابی، پایگاه داده قابل دسترسی نیست: "
                + sanitize_message(str(exc))
            ) from exc

    # ----------------------------------------------------------
    # Media restore (guarded extraction)
    # ----------------------------------------------------------

    def _safe_media_destination(self, relative):
        """Resolve a media path that is guaranteed to stay under MEDIA_ROOT."""
        relative = Path(relative)

        if relative.is_absolute() or ".." in relative.parts:
            raise RestoreError(
                "مسیر ناامن در بایگانی رسانه یافت شد."
            )

        media_root = Path(settings.MEDIA_ROOT).resolve()
        target = media_root

        for part in relative.parts[:-1]:
            target = target / part
            if target.is_symlink():
                raise RestoreError(
                    "مسیر رسانه شامل پیوند نمادین است؛ بازیابی متوقف شد."
                )
            if target.exists() and not target.is_dir():
                raise RestoreError(
                    "مسیر رسانه با یک فایل تداخل دارد."
                )
            target.mkdir(parents=True, exist_ok=True)

        return media_root / relative

    def _restore_media(self, media_gz_path):
        """Restore media.tar.gz into MEDIA_ROOT with traversal protection.

        Members are extracted into a temporary staging directory first and are
        then moved into MEDIA_ROOT one by one through validated parent paths,
        so a symlinked directory under MEDIA_ROOT can never redirect writes.
        """
        media_root = Path(settings.MEDIA_ROOT)
        media_root.mkdir(parents=True, exist_ok=True)

        if self._tmp_dir is None:
            self._tmp_dir = self._make_temp_dir()

        stage_dir = self._tmp_dir / "media_stage"
        stage_dir.mkdir(parents=True, exist_ok=True)

        member_count = 0

        try:
            with tarfile.open(media_gz_path, "r:gz") as archive:
                for member in archive.getmembers():
                    _assert_safe_member(member)

                    target = stage_dir / member.name

                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue

                    if member.isfile():
                        target.parent.mkdir(
                            parents=True,
                            exist_ok=True,
                        )
                        with archive.extractfile(
                            member
                        ) as source, open(target, "wb") as dest:
                            shutil.copyfileobj(source, dest)
                        member_count += 1

            if member_count == 0:
                logger.info(
                    "Restore #%s: media archive contained no files",
                    self.restore.pk,
                )

            moved = 0

            for root_dir, _, files in os.walk(stage_dir):
                for file_name in files:
                    source = Path(root_dir) / file_name
                    relative = source.relative_to(stage_dir)
                    destination = self._safe_media_destination(relative)
                    shutil.move(str(source), str(destination))
                    moved += 1

            if moved != member_count:
                raise RestoreError(
                    "بازیابی فایل‌های رسانه ناقص است؛ "
                    "برخی فایل‌ها منتقل نشدند."
                )

            logger.info(
                "Restore #%s: restored %s media file(s)",
                self.restore.pk,
                moved,
            )

        except tarfile.TarError as exc:
            raise RestoreError(
                "بایگانی رسانه قابل خواندن نیست."
            ) from exc

        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

    # ----------------------------------------------------------
    # Safety backup
    # ----------------------------------------------------------

    def _create_safety_backup(self, manifest):
        """Take an automatic pre-restore snapshot of the current state."""
        backup = Backup.objects.create(
            filename=generate_backup_filename(),
            includes_media=manifest["includes_media"],
            is_pre_restore_backup=True,
            created_by=None,
        )

        try:
            BackupService(backup, storage=self.storage).run()
        except BackupError as exc:
            raise RestoreError(
                "تهیه پشتیبان امنیتی پیش از بازیابی ناموفق بود: "
                + str(exc)
            ) from exc

        backup.refresh_from_db()

        if backup.status != Backup.Status.SUCCESS:
            raise RestoreError(
                "تهیه پشتیبان امنیتی پیش از بازیابی ناموفق بود: "
                + (backup.error_message or "وضعیت نامشخص")
            )

        logger.info(
            "Restore #%s: safety backup %s created",
            self.restore.pk,
            backup.filename,
        )

        return backup

    def _capture_backup_state(self, backup):
        """Snapshot a safety backup's metadata for post-restore recreation."""
        return {
            "filename": backup.filename,
            "storage_path": backup.storage_path,
            "size": backup.size,
            "database_size": backup.database_size,
            "media_size": backup.media_size,
            "includes_media": backup.includes_media,
            "checksum": backup.checksum,
            "started_at": backup.started_at,
            "completed_at": backup.completed_at,
            "status": backup.status,
            "is_pre_restore_backup": True,
            "error_message": "",
        }

    def _recreate_safety_backup_row(self):
        """Recreate the safety-backup row inside the restored database.

        A successful database restore wipes the original safety-backup row
        (its file remains on disk). Recreate the row so the snapshot stays
        discoverable and traceable in the restored database.
        """
        if not self._safety_snapshot:
            return

        try:
            still_present = Backup.objects.filter(
                pk=self._safety_backup_pk,
                filename=self._safety_snapshot["filename"],
            ).exists()
        except (OperationalError, ProgrammingError):
            logger.exception(
                "Restore #%s: could not inspect backup table after restore",
                self.restore.pk,
            )
            return

        if still_present:
            # Database was not replaced (e.g. tests or a no-op scenario).
            return

        try:
            Backup.objects.create(**self._safety_snapshot)
        except Exception:
            logger.exception(
                "Restore #%s: could not recreate safety backup row %s",
                self.restore.pk,
                self._safety_snapshot["filename"],
            )

    # ----------------------------------------------------------
    # Terminal status recording
    # ----------------------------------------------------------

    def _mark_terminal(self, status, message):
        """Record the terminal restore status safely.

        Before the database is replaced this updates the original row. Once a
        restore has rewritten the database the original row no longer exists
        (its primary key now belongs to the restored data), so a fresh audit
        row is created instead. Never writes to a row it cannot positively
        identify as the original restore.
        """
        now = timezone.now()
        cleaned = sanitize_message(message)[:1000] if message else ""

        try:
            updated = Restore.objects.filter(
                pk=self.restore.pk,
                archive_filename=self.restore.archive_filename,
                started_at=self.restore.started_at,
            ).update(
                status=status,
                completed_at=now,
                error_message=cleaned,
                updated_at=now,
            )
        except (OperationalError, ProgrammingError):
            logger.exception(
                "Restore #%s: restore table unavailable while recording "
                "terminal status; database was replaced mid-restore.",
                self.restore.pk,
            )
            self.restore.status = status
            self.restore.completed_at = now
            return

        if updated:
            try:
                self.restore.refresh_from_db()
            except Restore.DoesNotExist:
                self.restore.status = status
                self.restore.completed_at = now
            return

        # Original row is gone (database replaced by the restored data) or the
        # archive filename differs; record a fresh audit row in the restored
        # database.
        try:
            Restore.objects.create(
                status=status,
                completed_at=now,
                error_message=cleaned,
                archive_filename=(
                    self.restore.archive_filename or ""
                ),
                requested_by_username=(
                    self.restore.requested_by_username or ""
                ),
                product_version=(
                    self.restore.product_version or ""
                ),
                database_engine=(
                    self.restore.database_engine or ""
                ),
                database_backup_format=(
                    self.restore.database_backup_format or ""
                ),
                includes_media=self.restore.includes_media,
                started_at=self.restore.started_at,
                pre_restore_backup_filename=(
                    self.restore.pre_restore_backup_filename or ""
                ),
            )
            logger.info(
                "Restore #%s: audit row %s recorded in restored database",
                self.restore.pk,
                status,
            )
        except Exception:
            logger.exception(
                "Restore #%s: could not record %s audit row after "
                "database replacement.",
                self.restore.pk,
                status,
            )

        self.restore.status = status
        self.restore.completed_at = now

    # ----------------------------------------------------------
    # Cleanup
    # ----------------------------------------------------------

    def _cleanup_temp_dir(self):
        if not self._tmp_dir:
            return
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
