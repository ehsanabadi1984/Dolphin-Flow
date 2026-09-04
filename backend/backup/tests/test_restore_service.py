import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from backup.models import Backup, Restore
from backup.restore_services import RestoreError, RestoreService
from backup.services import BackupService

from .test_service import _make_fake_pg_dump


def _make_fake_pg_restore(fail=False, stderr=""):
    """Patch pg_restore only (tests that never trigger pg_dump)."""
    return _make_fake_tools(
        fail_restore=fail,
        stderr=stderr,
    )


def _make_fake_tools(
    fail_restore=False,
    stderr="",
    capture_commands=None,
):
    """Patch ``subprocess.run`` with a dispatcher for pg_dump and pg_restore.

    Both backup.services and backup.restore_services import the same stdlib
    ``subprocess`` module, so stacking two ``mock.patch`` calls on its ``run``
    attribute would clobber each other. A single dispatcher is required.
    """
    from .test_service import FAKE_DUMP_BYTES

    def fake_run(
        command,
        env=None,
        capture_output=False,
        text=False,
        check=False,
    ):
        if capture_commands is not None:
            capture_commands.append((list(command), dict(env or {})))

        # pg_dump writes the dump to its --file destination.
        if "--file" in command and "--format=custom" in command:
            dest = Path(command[command.index("--file") + 1])
            dest.write_bytes(FAKE_DUMP_BYTES)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="",
            )

        if "--list" in command:
            # pg_restore --list prints the TOC on stdout (no DB connection).
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=";\n; PostgreSQL database dump\n;\n"
                "2; 145344 TABLE public accounts_user\n",
                stderr="",
            )

        if fail_restore:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr=stderr,
            )

        return subprocess.CompletedProcess(command, 0)

    return mock.patch(
        "subprocess.run",
        side_effect=fake_run,
    )


def _make_inner_media_gz(member_specs):
    """Build media.tar.gz bytes with arbitrary (possibly unsafe) members.

    ``member_specs`` is a list of ``(name, data)`` tuples for regular files or
    ``(name, None, "dir")`` for directories.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for spec in member_specs:
            if len(spec) == 3 and spec[2] == "dir":
                info = tarfile.TarInfo(spec[0])
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
                continue

            name, data = spec[0], spec[1]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _build_dfbak(
    tmp_root,
    filename,
    *,
    manifest,
    dump=b"DUMP-BYTES",
    media_gz=None,
):
    """Write a crafted .dfbak on disk; returns its absolute path.

    ``media_gz`` defaults to ``None`` (member omitted); pass bytes to embed a
    media.tar.gz member regardless of what the manifest claims, which lets
    tests build intentionally inconsistent archives.
    """
    target = Path(tmp_root) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, "w") as archive:
        manifest_bytes = json.dumps(manifest).encode("utf-8")

        for arcname, data in (
            ("manifest.json", manifest_bytes),
            ("database.dump", dump),
        ):
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

        if media_gz is not None:
            info = tarfile.TarInfo("media.tar.gz")
            info.size = len(media_gz)
            archive.addfile(info, io.BytesIO(media_gz))

    return target


VALID_MANIFEST = {
    "format": "dolphin-flow-backup",
    "format_version": 1,
    "product_version": "1.0.0",
    "database_engine": "postgresql",
    "database_backup_format": "custom",
    "includes_media": True,
    "database_size": 10,
    "media_size": 1,
}


class RestoreServiceTestCase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.media_root = self.tmp / "media"
        self.backup_root = self.tmp / "backups"
        self._source_counter = 0
        self.enterContext(
            override_settings(
                BACKUP_ROOT=self.backup_root,
                MEDIA_ROOT=self.media_root,
                PG_DUMP_PATH="pg_dump",
                PG_RESTORE_PATH="pg_restore",
            )
        )

    def make_source_backup(self, *, includes_media=True, media=("photo.jpg",)):
        """Build a real SUCCESS backup (the .dfbak restore source)."""
        for relative in media:
            path = self.media_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"media-content")

        self._source_counter += 1
        backup = Backup.objects.create(
            filename=(
                "DolphinFlow_Backup_2026-09-04_"
                f"{self._source_counter:06d}.dfbak"
            ),
            includes_media=includes_media,
        )

        with _make_fake_pg_dump():
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)
        return backup

    def make_restore(self, backup=None, **kwargs):
        defaults = {
            "archive_filename": (
                backup.filename if backup else "restored.dfbak"
            ),
            "requested_by_username": "root",
            "includes_media": (
                backup.includes_media if backup else True
            ),
        }
        defaults.update(kwargs)
        return Restore.objects.create(backup=backup, **defaults)

    def run_restore(self, restore, archive_path=None):
        return RestoreService(
            restore,
            archive_path=archive_path,
        ).run()

    def run_crafted(self, restore, target):
        """Run a restore from a hand-built archive (mocks both tools).

        Hand-built archives still reach the automatic safety backup, which
        itself runs pg_dump, so both external tools are mocked.
        """
        with _make_fake_tools():
            return self.run_restore(restore, archive_path=target)

    # ----------------------------------------------------------
    # Happy path (end to end through the real save/archive path)
    # ----------------------------------------------------------

    def test_successful_restore_end_to_end_with_media(self):
        backup = self.make_source_backup(
            media=("photo.jpg", "docs/nested/a.txt")
        )
        restore = self.make_restore(backup)

        # The current media is replaced by the archive's copy.
        self.media_root.joinpath("photo.jpg").write_bytes(b"current-state")
        self.media_root.joinpath("docs/nested/a.txt").write_bytes(
            b"current-state"
        )

        with _make_fake_tools():
            result = self.run_restore(restore)

        self.assertEqual(result["status"], Restore.Status.SUCCESS)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)
        self.assertIsNotNone(restore.completed_at)
        self.assertEqual(restore.error_message, "")
        self.assertEqual(
            restore.archive_filename,
            backup.filename,
        )
        self.assertTrue(restore.pre_restore_backup_filename)
        self.assertEqual(
            restore.requested_by_username,
            "root",
        )

        # A traceable pre-restore safety backup exists and is a real file.
        safety = Backup.objects.filter(
            is_pre_restore_backup=True
        ).first()
        self.assertIsNotNone(safety)
        self.assertEqual(safety.status, Backup.Status.SUCCESS)
        self.assertEqual(
            safety.filename,
            restore.pre_restore_backup_filename,
        )
        self.assertTrue(
            (self.backup_root / safety.storage_path).exists()
        )

        # Media restored into MEDIA_ROOT.
        self.assertEqual(
            (self.media_root / "photo.jpg").read_bytes(),
            b"media-content",
        )
        self.assertEqual(
            (self.media_root / "docs/nested/a.txt").read_bytes(),
            b"media-content",
        )

        # Exactly one safety row: no duplicates when the DB is not replaced.
        self.assertEqual(
            Backup.objects.filter(
                is_pre_restore_backup=True
            ).count(),
            1,
        )

    def test_restore_without_media(self):
        backup = self.make_source_backup(includes_media=False)
        restore = self.make_restore(backup)

        media_marker = self.media_root / "keep.txt"
        media_marker.parent.mkdir(parents=True, exist_ok=True)
        media_marker.write_bytes(b"untouched")

        with _make_fake_tools():
            result = self.run_restore(restore)

        self.assertEqual(result["status"], Restore.Status.SUCCESS)
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)
        self.assertFalse(restore.includes_media)
        self.assertEqual(media_marker.read_bytes(), b"untouched")

    def test_pg_restore_command_has_no_credentials_in_argv(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)

        captured = []

        with _make_fake_tools(capture_commands=captured):
            self.run_restore(restore)

        password = settings.DATABASES["default"].get("PASSWORD")
        database = settings.DATABASES["default"]

        restore_commands = [
            (command, env)
            for command, env in captured
            if command and command[0].endswith("pg_restore")
        ]
        # --list (archive scan) plus the real restore command.
        self.assertEqual(len(restore_commands), 2)

        # Keep only the command that actually writes to the database.
        command, env = next(
            (c, e)
            for c, e in restore_commands
            if "--list" not in c
        )

        self.assertIn("--clean", command)
        self.assertIn("--if-exists", command)
        self.assertIn("--no-owner", command)
        self.assertIn("--no-privileges", command)
        self.assertIn("--exit-on-error", command)
        self.assertIn("--dbname", command)
        self.assertIn(database["NAME"], command)

        if password:
            self.assertNotIn(password, " ".join(command))
            self.assertEqual(env.get("PGPASSWORD"), password)

        # The dump path passed to pg_restore is the materialized member file
        # (it is removed again in the pipeline cleanup after the run).
        dump_index = command.index("--dbname") + 1
        dump_path = command[dump_index + 1]
        self.assertTrue(dump_path.endswith("database.dump"))
        self.assertNotIn("..", dump_path)

    # ----------------------------------------------------------
    # Validation
    # ----------------------------------------------------------

    def test_rejects_invalid_archive_extension_content(self):
        # File with the .dfbak name but not a tar archive.
        bad_file = self.backup_root / "broken.dfbak"
        bad_file.parent.mkdir(parents=True, exist_ok=True)
        bad_file.write_bytes(b"this is not a tar archive")

        restore = self.make_restore(
            backup=None,
            archive_filename="broken.dfbak",
        )

        self.run_crafted(restore, bad_file)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn(
            "قابل خواندن نیست",
            restore.error_message,
        )

    def test_rejects_archive_without_manifest(self):
        target = self.backup_root / "no-manifest.dfbak"
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w") as archive:
            data = b"DUMP"
            info = tarfile.TarInfo("database.dump")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

        restore = self.make_restore(
            backup=None,
            archive_filename="no-manifest.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("manifest", restore.error_message)

    def test_rejects_malformed_manifest(self):
        target = self.backup_root / "bad-manifest.dfbak"
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w") as archive:
            data = b"{not valid json"
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

            dump = b"DUMP"
            info = tarfile.TarInfo("database.dump")
            info.size = len(dump)
            archive.addfile(info, io.BytesIO(dump))

        restore = self.make_restore(
            backup=None,
            archive_filename="bad-manifest.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("manifest", restore.error_message)

    def test_rejects_unsupported_format_version(self):
        manifest = dict(VALID_MANIFEST)
        manifest["format_version"] = 999

        target = _build_dfbak(
            self.backup_root,
            "future.dfbak",
            manifest=manifest,
            media_gz=_make_inner_media_gz([("a.txt", b"x")]),
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="future.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("نسخه فرمت", restore.error_message)

    def test_rejects_wrong_database_engine(self):
        manifest = dict(VALID_MANIFEST)
        manifest["database_engine"] = "mysql"

        target = _build_dfbak(
            self.backup_root,
            "wrong-engine.dfbak",
            manifest=manifest,
            media_gz=_make_inner_media_gz([("a.txt", b"x")]),
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="wrong-engine.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("PostgreSQL", restore.error_message)

    def test_rejects_missing_database_dump(self):
        target = self.backup_root / "no-dump.dfbak"
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w") as archive:
            data = json.dumps(VALID_MANIFEST).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

        restore = self.make_restore(
            backup=None,
            archive_filename="no-dump.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("ساختار بایگانی", restore.error_message)

    def test_media_member_required_when_includes_media_true(self):
        manifest = dict(VALID_MANIFEST)

        target = _build_dfbak(
            self.backup_root,
            "no-media.dfbak",
            manifest=manifest,
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="no-media.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("ساختار بایگانی", restore.error_message)

    def test_media_member_not_required_when_includes_media_false(self):
        manifest = dict(VALID_MANIFEST)
        manifest["includes_media"] = False

        target = _build_dfbak(
            self.backup_root,
            "db-only.dfbak",
            manifest=manifest,
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="db-only.dfbak",
            includes_media=False,
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)

    def test_rejects_manifest_media_inconsistency(self):
        # Manifest says no media, but the archive embeds a media member.
        manifest = dict(VALID_MANIFEST)
        manifest["includes_media"] = False

        target = _build_dfbak(
            self.backup_root,
            "inconsistent.dfbak",
            manifest=manifest,
            media_gz=_make_inner_media_gz([("a.txt", b"x")]),
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="inconsistent.dfbak",
            includes_media=False,
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("ساختار بایگانی", restore.error_message)

    def test_rejects_extra_unknown_member(self):
        target = self.backup_root / "extra-member.dfbak"
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w") as archive:
            for arcname, data in (
                ("manifest.json", json.dumps(VALID_MANIFEST).encode()),
                ("database.dump", b"DUMP"),
                ("media.tar.gz", _make_inner_media_gz([("a.txt", b"x")])),
                ("evil.txt", b"surprise"),
            ):
                info = tarfile.TarInfo(arcname)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

        restore = self.make_restore(
            backup=None,
            archive_filename="extra-member.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("ساختار بایگانی", restore.error_message)

    def test_checksum_mismatch_is_rejected(self):
        backup = self.make_source_backup()
        backup.checksum = "0" * 64
        backup.save(update_fields=["checksum", "updated_at"])

        restore = self.make_restore(backup)

        with _make_fake_tools(capture_commands=[]) as _unused:
            self.run_restore(restore)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("checksum", restore.error_message)

    # ----------------------------------------------------------
    # Security: malicious archives
    # ----------------------------------------------------------

    def test_rejects_media_path_traversal(self):
        media_gz = _make_inner_media_gz(
            [("../../evil.txt", b"escaped")]
        )
        target = _build_dfbak(
            self.backup_root,
            "traversal.dfbak",
            manifest=VALID_MANIFEST,
            media_gz=media_gz,
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="traversal.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)

        # Nothing escaped into the parent of the temp dir / media root.
        self.assertFalse((self.tmp / "evil.txt").exists())
        self.assertFalse(
            (self.media_root.parent / "evil.txt").exists()
        )
        self.assertTrue(restore.error_message)

    def test_rejects_media_absolute_path(self):
        media_gz = _make_inner_media_gz(
            [("/tmp/evil.txt", b"escaped")]
        )
        target = _build_dfbak(
            self.backup_root,
            "absolute.dfbak",
            manifest=VALID_MANIFEST,
            media_gz=media_gz,
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="absolute.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertFalse(Path("/tmp/evil.txt").exists())

    def test_rejects_media_symlink_member(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            data = b"payload"
            info = tarfile.TarInfo("link.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../etc/passwd"
            info.size = 0
            archive.addfile(info)

            real = tarfile.TarInfo("ok.txt")
            real.size = len(data)
            archive.addfile(real, io.BytesIO(data))

        target = _build_dfbak(
            self.backup_root,
            "symlink.dfbak",
            manifest=VALID_MANIFEST,
            media_gz=buffer.getvalue(),
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="symlink.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("مجاز نیست", restore.error_message)

    def test_media_restores_safely_into_nested_directories(self):
        media_gz = _make_inner_media_gz(
            [
                ("uploads/2026/photo.jpg", b"media-content"),
                ("uploads/2026/other.png", b"png-data"),
            ]
        )
        target = _build_dfbak(
            self.backup_root,
            "nested-media.dfbak",
            manifest=VALID_MANIFEST,
            media_gz=media_gz,
        )

        restore = self.make_restore(
            backup=None,
            archive_filename="nested-media.dfbak",
        )

        self.run_crafted(restore, target)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)
        self.assertEqual(
            (
                self.media_root / "uploads/2026/photo.jpg"
            ).read_bytes(),
            b"media-content",
        )
        self.assertEqual(
            (
                self.media_root / "uploads/2026/other.png"
            ).read_bytes(),
            b"png-data",
        )

    # ----------------------------------------------------------
    # State handling
    # ----------------------------------------------------------

    def test_running_restore_is_not_rerun(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)
        restore.status = Restore.Status.RESTORING
        restore.save(update_fields=["status", "updated_at"])

        captured = []
        with _make_fake_tools(capture_commands=captured):
            result = self.run_restore(restore)

        self.assertEqual(result["status"], Restore.Status.RESTORING)
        self.assertEqual(captured, [])
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.RESTORING)

    def test_successful_restore_is_not_rerun(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)

        with _make_fake_tools():
            self.run_restore(restore)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)

        captured = []
        with _make_fake_tools(capture_commands=captured):
            result = self.run_restore(restore)

        self.assertEqual(result["status"], Restore.Status.SUCCESS)
        # No external tool may run again for a completed restore.
        self.assertEqual(captured, [])

    def test_stale_queued_invocation_does_not_start_restore(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)
        stale = Restore.objects.get(pk=restore.pk)

        # Another invocation already claimed the slot after `stale` was read.
        Restore.objects.filter(pk=restore.pk).update(
            status=Restore.Status.RESTORING,
        )

        captured = []
        with _make_fake_tools(capture_commands=captured):
            result = self.run_restore(stale)

        self.assertEqual(result["status"], Restore.Status.RESTORING)
        self.assertEqual(captured, [])

    def test_second_restore_rejected_while_another_is_running(self):
        first_backup = self.make_source_backup()
        second_backup = self.make_source_backup(
            media=("second.jpg",)
        )
        first = self.make_restore(first_backup)
        first.status = Restore.Status.RESTORING
        first.save(update_fields=["status", "updated_at"])

        second = self.make_restore(second_backup)

        with _make_fake_tools():
            self.run_restore(second)

        second.refresh_from_db()
        self.assertEqual(second.status, Restore.Status.FAILED)
        self.assertIn(
            "بازیابی دیگری در حال اجراست",
            second.error_message,
        )

    def test_restore_rejected_while_backup_running(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)

        active_backup = Backup.objects.create(
            status=Backup.Status.RUNNING,
            filename="DolphinFlow_Backup_active.dfbak",
        )

        with _make_fake_tools(capture_commands=[]) as _unused:
            self.run_restore(restore)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn(
            "پشتیبان‌گیری در حال اجراست",
            restore.error_message,
        )
        active_backup.refresh_from_db()
        self.assertEqual(active_backup.status, Backup.Status.RUNNING)

    def test_restore_failure_marks_failed_and_keeps_cleanup(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)

        with _make_fake_tools(
            fail_restore=True,
            stderr="restore exploded",
        ):
            result = self.run_restore(restore)

        self.assertEqual(result["status"], Restore.Status.FAILED)
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn(
            "بازیابی پایگاه داده ناموفق بود",
            restore.error_message,
        )

        # Temporary directory cleaned up.
        tmp_root = self.backup_root / "tmp"
        if tmp_root.exists():
            self.assertEqual(list(tmp_root.iterdir()), [])

    def test_post_restore_check_failure_marks_failed(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)

        def broken_check(service):
            raise RestoreError("پایگاه داده پس از بازیابی سالم نیست")

        with _make_fake_tools(), mock.patch.object(
            RestoreService,
            "_post_restore_db_check",
            broken_check,
        ):
            result = self.run_restore(restore)

        self.assertEqual(result["status"], Restore.Status.FAILED)
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("سالم نیست", restore.error_message)

    def test_safety_backup_failure_marks_failed_without_destructive_steps(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)

        def failing_factory(real_backup, storage=None):
            def fake_run():
                real_backup.status = Backup.Status.FAILED
                real_backup.completed_at = timezone.now()
                real_backup.error_message = "safety snapshot exploded"
                real_backup.save(
                    update_fields=[
                        "status",
                        "completed_at",
                        "error_message",
                        "updated_at",
                    ]
                )
                return {
                    "status": Backup.Status.FAILED,
                    "backup_id": real_backup.pk,
                }

            service = BackupService(real_backup, storage=storage)
            service.run = fake_run
            return service

        with _make_fake_pg_restore(), mock.patch(
            "backup.restore_services.BackupService",
            side_effect=failing_factory,
        ) as mocked_factory:
            result = self.run_restore(restore)

        self.assertEqual(result["status"], Restore.Status.FAILED)
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)
        self.assertIn("امنیتی", restore.error_message)

        # pg_restore was never invoked: nothing destructive happened.
        mocked_factory.assert_called_once()

    # ----------------------------------------------------------
    # Audit row behavior when the database row is gone
    # ----------------------------------------------------------

    def test_mark_terminal_creates_fresh_audit_row_when_original_is_gone(self):
        backup = self.make_source_backup()
        restore = self.make_restore(backup)
        original_pk = restore.pk
        restore.pk = None  # simulate the row being wiped by the restore
        restore.id = None

        service = RestoreService(restore)

        service._mark_terminal(Restore.Status.SUCCESS, "")

        fresh = Restore.objects.filter(
            status=Restore.Status.SUCCESS,
            archive_filename=backup.filename,
        ).exclude(pk=original_pk).first()

        self.assertIsNotNone(fresh)
        self.assertEqual(fresh.requested_by_username, "root")

    # ----------------------------------------------------------
    # Backup side-effect: no new backups while a restore is active
    # ----------------------------------------------------------

    def test_new_backup_rejected_while_restore_running(self):
        restore = Restore.objects.create(
            archive_filename="active-restore.dfbak",
            status=Restore.Status.RESTORING,
        )
        restore.started_at = timezone.now()
        restore.save(update_fields=["started_at", "updated_at"])

        queued = Backup.objects.create(
            filename="DolphinFlow_Backup_blocked.dfbak",
        )

        with mock.patch(
            "backup.services.subprocess.run",
            side_effect=AssertionError("must not run"),
        ):
            result = BackupService(queued).run()

        queued.refresh_from_db()
        self.assertEqual(queued.status, Backup.Status.FAILED)
        self.assertIn("بازیابی (Restore) در حال اجراست", queued.error_message)
        self.assertEqual(result["status"], Backup.Status.FAILED)

        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.RESTORING)
