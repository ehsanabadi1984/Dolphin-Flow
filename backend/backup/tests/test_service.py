import hashlib
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

from backup.models import Backup
from backup.services import BackupError, BackupService
from backup.storage import BackupStorageError, LocalBackupStorage

FAKE_DUMP_BYTES = b"FAKE-PG-DUMP-CUSTOM-FORMAT" * 20


def _make_fake_pg_dump(fail=False, stderr=""):
    def fake_run(command, env=None, capture_output=False, text=False, check=False):
        if fail:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr=stderr,
            )
        file_index = command.index("--file")
        dest = Path(command[file_index + 1])
        dest.write_bytes(FAKE_DUMP_BYTES)
        return subprocess.CompletedProcess(command, 0)

    return mock.patch(
        "backup.services.subprocess.run",
        side_effect=fake_run,
    )


class BackupServiceTestCase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.media_root = self.tmp / "media"
        self.backup_root = self.tmp / "backups"
        self.enterContext(
            override_settings(
                BACKUP_ROOT=self.backup_root,
                MEDIA_ROOT=self.media_root,
                PG_DUMP_PATH="pg_dump",
            )
        )

    def make_backup(self, **kwargs):
        defaults = {
            "filename": (
                "DolphinFlow_Backup_2026-09-04_020000.dfbak"
            ),
        }
        defaults.update(kwargs)
        return Backup.objects.create(**defaults)

    def write_media(self, *relative_paths):
        for relative in relative_paths:
            path = self.media_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"media-content")

    def open_archive(self, backup):
        archive_path = Path(settings.BACKUP_ROOT) / backup.storage_path
        return tarfile.open(archive_path, "r")

    def test_successful_run_builds_valid_archive(self):
        self.write_media("photo.jpg", "docs/a.txt")
        backup = self.make_backup()

        with _make_fake_pg_dump():
            result = BackupService(backup).run()

        self.assertEqual(result["status"], Backup.Status.SUCCESS)

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)
        self.assertIsNotNone(backup.started_at)
        self.assertIsNotNone(backup.completed_at)
        self.assertEqual(backup.storage_path, backup.filename)
        self.assertEqual(backup.database_size, len(FAKE_DUMP_BYTES))
        self.assertGreater(backup.media_size, 0)
        self.assertGreater(backup.size, 0)
        self.assertEqual(len(backup.checksum), 64)
        self.assertEqual(backup.error_message, "")

        final_path = self.backup_root / backup.filename
        self.assertTrue(final_path.exists())
        self.assertEqual(final_path.stat().st_size, backup.size)

        with self.open_archive(backup) as archive:
            names = set(archive.getnames())
            self.assertEqual(
                names,
                {
                    "manifest.json",
                    "database.dump",
                    "media.tar.gz",
                },
            )
            self.assertGreater(
                archive.getmember("database.dump").size,
                0,
            )
            self.assertGreater(
                archive.getmember("media.tar.gz").size,
                0,
            )

            manifest = json.loads(
                archive.extractfile("manifest.json").read()
            )
            self.assertEqual(
                manifest["format"],
                "dolphin-flow-backup",
            )
            self.assertEqual(manifest["format_version"], 1)
            self.assertEqual(
                manifest["database_engine"],
                "postgresql",
            )
            self.assertEqual(
                manifest["database_backup_format"],
                "custom",
            )
            self.assertTrue(manifest["includes_media"])
            self.assertEqual(
                manifest["filename"],
                backup.filename,
            )
            self.assertEqual(
                manifest["database_size"],
                len(FAKE_DUMP_BYTES),
            )

    def test_media_archive_contains_media_files(self):
        self.write_media("photo.jpg", "docs/a.txt")
        backup = self.make_backup()

        with _make_fake_pg_dump():
            BackupService(backup).run()

        with self.open_archive(backup) as archive:
            media_member = archive.extractfile("media.tar.gz")
            with tempfile.NamedTemporaryFile(suffix=".gz") as tmp:
                tmp.write(media_member.read())
                tmp.flush()
                with tarfile.open(tmp.name, "r:gz") as media:
                    self.assertEqual(
                        set(media.getnames()),
                        {"photo.jpg", "docs/a.txt"},
                    )

    def test_manifest_contains_no_credentials(self):
        backup = self.make_backup()
        password = settings.DATABASES["default"].get("PASSWORD")

        with _make_fake_pg_dump():
            BackupService(backup).run()

        with self.open_archive(backup) as archive:
            manifest_raw = archive.extractfile(
                "manifest.json"
            ).read()

        if password:
            self.assertNotIn(password, manifest_raw.decode())

        for key in (
            "PASSWORD",
            "DJANGO_SECRET_KEY",
        ):
            self.assertNotIn(key, manifest_raw.decode())

    def test_checksum_is_sha256_of_final_file(self):
        self.write_media("a.txt")
        backup = self.make_backup()

        with _make_fake_pg_dump():
            BackupService(backup).run()

        final_path = self.backup_root / backup.storage_path
        expected = hashlib.sha256(
            final_path.read_bytes()
        ).hexdigest()
        self.assertEqual(backup.checksum, expected)

    def test_failed_pg_dump_marks_failed_and_cleans_up(self):
        backup = self.make_backup()

        with _make_fake_pg_dump(
            fail=True,
            stderr=(
                "pg_dump: error: connection to server failed: "
                "password authentication failed for user "
                f"\"{settings.DATABASES['default'].get('USER')}\""
            ),
        ):
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.FAILED)
        self.assertIsNotNone(backup.completed_at)
        self.assertIn(
            "ایجاد dump پایگاه داده ناموفق بود",
            backup.error_message,
        )

        self.assertFalse(
            (self.backup_root / backup.filename).exists()
        )

        # Temporary directory is gone.
        tmp_root = self.backup_root / "tmp"
        if tmp_root.exists():
            self.assertEqual(
                list(tmp_root.iterdir()),
                [],
            )

    def test_failure_after_archive_built_leaves_no_final_file(self):
        backup = self.make_backup()

        def broken_validate(service, archive_path):
            raise BackupError("validation exploded")

        with _make_fake_pg_dump(), mock.patch.object(
            BackupService,
            "_validate_archive",
            broken_validate,
        ):
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.FAILED)
        self.assertIn(
            "validation exploded",
            backup.error_message,
        )
        self.assertFalse(
            (self.backup_root / backup.filename).exists()
        )
        tmp_root = self.backup_root / "tmp"
        if tmp_root.exists():
            self.assertEqual(list(tmp_root.iterdir()), [])

    def test_validation_rejects_archive_missing_media_member(self):
        backup = self.make_backup()

        def broken_build(service, dest_path, *members):
            mtime = int(timezone.now().timestamp())
            with tarfile.open(dest_path, "w") as archive:
                for source_path, arcname in members:
                    if arcname == "media.tar.gz":
                        continue
                    info = archive.gettarinfo(
                        str(source_path),
                        arcname=arcname,
                    )
                    info.mtime = mtime
                    with open(source_path, "rb") as source:
                        archive.addfile(info, fileobj=source)

        with _make_fake_pg_dump(), mock.patch.object(
            BackupService,
            "_build_archive",
            broken_build,
        ):
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.FAILED)
        self.assertIn("media.tar.gz", backup.error_message)

    def test_empty_media_root_still_succeeds(self):
        self.media_root.mkdir(parents=True)
        backup = self.make_backup()

        with _make_fake_pg_dump():
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)

        with self.open_archive(backup) as archive:
            self.assertIn("media.tar.gz", archive.getnames())

    def test_missing_media_root_still_succeeds(self):
        backup = self.make_backup()

        with _make_fake_pg_dump():
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)

    def test_backup_root_inside_media_root_is_excluded(self):
        nested_backup_root = self.media_root / "backups"
        self.enterContext(
            override_settings(BACKUP_ROOT=nested_backup_root)
        )

        self.write_media("real.txt")
        secret = nested_backup_root / "secret.txt"
        secret.parent.mkdir(parents=True)
        secret.write_bytes(b"nested-backup-content")

        backup = self.make_backup()

        with _make_fake_pg_dump():
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)

        with self.open_archive(backup) as archive:
            media_member = archive.extractfile("media.tar.gz")
            with tempfile.NamedTemporaryFile(suffix=".gz") as tmp:
                tmp.write(media_member.read())
                tmp.flush()
                with tarfile.open(tmp.name, "r:gz") as media:
                    names = set(media.getnames())
                    self.assertIn("real.txt", names)
                    self.assertNotIn("secret.txt", names)
                    self.assertFalse(
                        any(
                            name.startswith("backups/")
                            for name in names
                        )
                    )

    def test_concurrent_backup_is_rejected(self):
        in_flight = self.make_backup()
        in_flight.status = Backup.Status.RUNNING
        in_flight.save(
            update_fields=["status", "updated_at"]
        )

        second = self.make_backup(
            filename="DolphinFlow_Backup_2026-09-05_020000.dfbak"
        )

        with _make_fake_pg_dump():
            BackupService(second).run()

        second.refresh_from_db()
        self.assertEqual(second.status, Backup.Status.FAILED)
        self.assertIn(
            "پشتیبان‌گیری دیگری در حال اجراست",
            second.error_message,
        )
        self.assertFalse(
            (self.backup_root / second.filename).exists()
        )

    def test_sequential_backups_are_allowed(self):
        first = self.make_backup()

        with _make_fake_pg_dump():
            BackupService(first).run()

        first.refresh_from_db()
        self.assertEqual(first.status, Backup.Status.SUCCESS)

        second = self.make_backup(
            filename="DolphinFlow_Backup_2026-09-05_020000.dfbak"
        )

        with _make_fake_pg_dump():
            BackupService(second).run()

        second.refresh_from_db()
        self.assertEqual(second.status, Backup.Status.SUCCESS)

    def test_oldest_queued_claims_slot_others_fail(self):
        first = self.make_backup()
        second = self.make_backup(
            filename="DolphinFlow_Backup_2026-09-05_020000.dfbak"
        )

        with _make_fake_pg_dump():
            BackupService(first).run()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Backup.Status.SUCCESS)
        self.assertEqual(second.status, Backup.Status.FAILED)
        self.assertIn(
            "پشتیبان‌گیری دیگری در حال اجراست",
            second.error_message,
        )

    def test_successful_backup_is_not_rerun(self):
        backup = self.make_backup()

        with _make_fake_pg_dump():
            BackupService(backup).run()

        final_path = self.backup_root / backup.storage_path
        before = final_path.read_bytes()

        with mock.patch(
            "backup.services.subprocess.run",
            side_effect=AssertionError("must not run again"),
        ):
            BackupService(backup).run()

        self.assertEqual(final_path.read_bytes(), before)
        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)

    def test_error_message_never_contains_password(self):
        password = settings.DATABASES["default"].get("PASSWORD")
        backup = self.make_backup()

        with _make_fake_pg_dump(
            fail=True,
            stderr=f"detail with {password} inside",
        ):
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertNotIn(password, backup.error_message)

    # ----------------------------------------------------------
    # BACKUP_INCLUDE_MEDIA / includes_media
    # ----------------------------------------------------------

    def test_media_excluded_when_includes_media_false(self):
        self.write_media("photo.jpg")
        backup = self.make_backup(includes_media=False)

        with _make_fake_pg_dump():
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)
        self.assertEqual(backup.media_size, 0)

        with self.open_archive(backup) as archive:
            self.assertEqual(
                set(archive.getnames()),
                {"manifest.json", "database.dump"},
            )

            manifest = json.loads(
                archive.extractfile("manifest.json").read()
            )
            self.assertFalse(manifest["includes_media"])
            self.assertEqual(manifest["media_size"], 0)

    def test_media_included_when_includes_media_true(self):
        self.write_media("photo.jpg")
        backup = self.make_backup(includes_media=True)

        with _make_fake_pg_dump():
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)
        self.assertGreater(backup.media_size, 0)

        with self.open_archive(backup) as archive:
            self.assertIn("media.tar.gz", archive.getnames())
            manifest = json.loads(
                archive.extractfile("manifest.json").read()
            )
            self.assertTrue(manifest["includes_media"])

    # ----------------------------------------------------------
    # RUNNING backups must never restart
    # ----------------------------------------------------------

    def test_running_backup_is_not_rerun(self):
        backup = self.make_backup(status=Backup.Status.RUNNING)

        with mock.patch(
            "backup.services.subprocess.run",
            side_effect=AssertionError("must not re-execute"),
        ):
            result = BackupService(backup).run()

        self.assertEqual(result["status"], Backup.Status.RUNNING)
        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.RUNNING)
        self.assertFalse(
            (self.backup_root / backup.filename).exists()
        )

    def test_stale_queued_invocation_does_not_restart_running_backup(self):
        """A worker that read QUEUED before another claimed it must not run."""
        backup = self.make_backup()
        stale = Backup.objects.get(pk=backup.pk)

        # Another worker claimed the slot after `stale` was fetched.
        Backup.objects.filter(pk=backup.pk).update(
            status=Backup.Status.RUNNING,
        )

        with mock.patch(
            "backup.services.subprocess.run",
            side_effect=AssertionError("must not re-execute"),
        ):
            result = BackupService(stale).run()

        self.assertEqual(result["status"], Backup.Status.RUNNING)
        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.RUNNING)

    # ----------------------------------------------------------
    # Filename collisions must not destroy existing backups
    # ----------------------------------------------------------

    def test_filename_collision_fails_new_backup_and_keeps_old_file(self):
        first = self.make_backup()

        with _make_fake_pg_dump():
            BackupService(first).run()

        first.refresh_from_db()
        self.assertEqual(first.status, Backup.Status.SUCCESS)

        final_path = self.backup_root / first.storage_path
        original_bytes = final_path.read_bytes()

        # A second backup (e.g. same-second create) receives the same filename.
        second = self.make_backup(filename=first.filename)

        with _make_fake_pg_dump():
            BackupService(second).run()

        second.refresh_from_db()
        self.assertEqual(second.status, Backup.Status.FAILED)
        self.assertIn("already exists", second.error_message)

        # The original successful backup file is untouched.
        self.assertEqual(final_path.read_bytes(), original_bytes)
        first.refresh_from_db()
        self.assertEqual(first.status, Backup.Status.SUCCESS)
        self.assertEqual(first.checksum, hashlib.sha256(original_bytes).hexdigest())


class LocalBackupStorageTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "root"
        self.storage = LocalBackupStorage(root=self.root)

    def test_path_for_rejects_traversal(self):
        for bad in (
            "",
            "../../etc/passwd",
            "/etc/passwd",
            "a/../../../etc/passwd",
        ):
            with self.assertRaises(BackupStorageError):
                self.storage.path_for(bad)

    def test_path_for_resolves_inside_root(self):
        path = self.storage.path_for(
            "DolphinFlow_Backup_x.dfbak"
        )
        self.assertEqual(
            path,
            (self.root / "DolphinFlow_Backup_x.dfbak").resolve(),
        )

    def test_finalize_is_atomic_and_guards_filename(self):
        self.storage.ensure_root()
        tmp_file = self.tmp / "tmp.dfbak"
        tmp_file.write_bytes(b"archive-bytes")

        final = self.storage.finalize(
            tmp_file,
            "DolphinFlow_Backup_2026-09-04_020000.dfbak",
        )

        self.assertTrue(final.exists())
        self.assertEqual(final.read_bytes(), b"archive-bytes")
        self.assertFalse(tmp_file.exists())

        with self.assertRaises(BackupStorageError):
            self.storage.finalize(tmp_file, "../../evil.dfbak")

    def test_delete_ignores_missing_file(self):
        self.storage.delete(
            "DolphinFlow_Backup_does-not-exist.dfbak"
        )

    def test_delete_removes_only_own_file(self):
        self.storage.ensure_root()
        victim = self.root / "a.dfbak"
        victim.write_bytes(b"x")
        self.storage.delete("a.dfbak")
        self.assertFalse(victim.exists())

    def test_finalize_refuses_to_overwrite_existing_file(self):
        self.storage.ensure_root()

        existing = (
            self.root / "DolphinFlow_Backup_2026-09-04_020000.dfbak"
        )
        existing.write_bytes(b"OLD-BACKUP")

        tmp_file = self.tmp / "new.dfbak"
        tmp_file.write_bytes(b"NEW-BACKUP")

        with self.assertRaises(BackupStorageError):
            self.storage.finalize(tmp_file, existing.name)

        # The existing backup survives and the temporary file is untouched.
        self.assertEqual(existing.read_bytes(), b"OLD-BACKUP")
        self.assertEqual(tmp_file.read_bytes(), b"NEW-BACKUP")
