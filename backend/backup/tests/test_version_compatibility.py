"""
Tests for PostgreSQL version compatibility in Backup/Restore.

Covers:
- pg_dump version detection and manifest storage
- pg_restore version detection
- Archive/restore client compatibility checks
- Error translation for unsupported version errors
- Missing/malformed metadata handling
- Backward compatibility with old manifests (no version metadata)
"""

import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from backup.models import Backup, Restore
from backup.restore_services import RestoreError, RestoreService
from backup.services import BackupError, BackupService
from backup.version_detection import (
    detect_pg_dump_version,
    detect_pg_restore_version,
    extract_major_version,
)


class VersionDetectionTestCase(TestCase):
    """Tests for version detection helpers."""

    def test_extract_major_version(self):
        self.assertEqual(extract_major_version("16.3"), 16)
        self.assertEqual(extract_major_version("15.2.1"), 15)
        self.assertEqual(extract_major_version("14.0"), 14)
        self.assertIsNone(extract_major_version(None))
        self.assertIsNone(extract_major_version(""))
        self.assertIsNone(extract_major_version("not-a-version"))

    def test_detect_pg_dump_version_with_mock(self):
        """Test version detection when pg_dump --version works."""
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["pg_dump", "--version"],
                0,
                stdout="pg_dump (PostgreSQL) 16.3\n",
                stderr="",
            ),
        ):
            version = detect_pg_dump_version("pg_dump")
            self.assertEqual(version, "16.3")

    def test_detect_pg_dump_version_fallback(self):
        """Test version detection with non-standard output format."""
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["pg_dump", "--version"],
                0,
                stdout="pg_dump version: 15.2\n",
                stderr="",
            ),
        ):
            version = detect_pg_dump_version("pg_dump")
            self.assertEqual(version, "15.2")

    def test_detect_pg_dump_version_fails_silently(self):
        """Test that version detection failure returns None, doesn't raise."""
        with mock.patch(
            "subprocess.run",
            side_effect=FileNotFoundError("pg_dump not found"),
        ):
            version = detect_pg_dump_version("pg_dump")
            self.assertIsNone(version)

    def test_detect_pg_restore_version_with_mock(self):
        """Test pg_restore version detection."""
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["pg_restore", "--version"],
                0,
                stdout="pg_restore (PostgreSQL) 15.2\n",
                stderr="",
            ),
        ):
            version = detect_pg_restore_version("pg_restore")
            self.assertEqual(version, "15.2")

    def test_detect_pg_restore_version_fails_silently(self):
        """Test that pg_restore version detection failure returns None."""
        with mock.patch(
            "subprocess.run",
            side_effect=FileNotFoundError("pg_restore not found"),
        ):
            version = detect_pg_restore_version("pg_restore")
            self.assertIsNone(version)


class BackupVersionInManifestTestCase(TestCase):
    """Tests that pg_dump version is stored in manifest.json."""

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
            "filename": "DolphinFlow_Backup_2026-09-04_020000.dfbak",
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

    def test_manifest_contains_pg_dump_version_when_detectable(self):
        """Test that manifest.json includes pg_dump_version when detectable."""
        self.write_media("photo.jpg")
        backup = self.make_backup()

        with mock.patch(
            "subprocess.run",
            side_effect=[
                # pg_dump --version
                subprocess.CompletedProcess(
                    ["pg_dump", "--version"],
                    0,
                    stdout="pg_dump (PostgreSQL) 16.3\n",
                    stderr="",
                ),
                # Actual pg_dump command (writes fake dump)
                subprocess.CompletedProcess(
                    ["pg_dump", "--format=custom", "--file", str(self.tmp / "database.dump")],
                    0,
                    stdout="",
                    stderr="",
                ),
            ],
        ):
            # Write a fake dump file for the backup
            dump_path = self.tmp / "database.dump"
            dump_path.write_bytes(b"FAKE-DUMP")

            result = BackupService(backup).run()

        self.assertEqual(result["status"], Backup.Status.SUCCESS)

        with self.open_archive(backup) as archive:
            manifest_raw = archive.extractfile("manifest.json").read()
            manifest = json.loads(manifest_raw)

            # pg_dump_version should be present
            self.assertIn("pg_dump_version", manifest)
            self.assertEqual(manifest["pg_dump_version"], "16.3")
            self.assertIn("pg_dump_major_version", manifest)
            self.assertEqual(manifest["pg_dump_major_version"], 16)

    def test_manifest_handles_missing_pg_dump_version(self):
        """Test that manifest works when pg_dump version is not detectable."""
        self.write_media("photo.jpg")
        backup = self.make_backup()

        with mock.patch(
            "subprocess.run",
            side_effect=[
                # pg_dump --version fails
                subprocess.CompletedProcess(
                    ["pg_dump", "--version"],
                    1,
                    stdout="",
                    stderr="",
                ),
                # Actual pg_dump command (writes fake dump)
                subprocess.CompletedProcess(
                    ["pg_dump", "--format=custom", "--file", str(self.tmp / "database.dump")],
                    0,
                    stdout="",
                    stderr="",
                ),
            ],
        ):
            # Write a fake dump file for the backup
            dump_path = self.tmp / "database.dump"
            dump_path.write_bytes(b"FAKE-DUMP")

            result = BackupService(backup).run()

        self.assertEqual(result["status"], Backup.Status.SUCCESS)

        with self.open_archive(backup) as archive:
            manifest_raw = archive.extractfile("manifest.json").read()
            manifest = json.loads(manifest_raw)

            # pg_dump_version should be None/null
            self.assertIn("pg_dump_version", manifest)
            self.assertIsNone(manifest["pg_dump_version"])
            self.assertIn("pg_dump_major_version", manifest)
            self.assertIsNone(manifest["pg_dump_major_version"])

    def test_old_manifest_without_version_metadata_still_works(self):
        """Test that old manifests without pg_dump_version are still accepted."""
        backup = self.make_backup()

        # Build an archive with an old manifest (no pg_dump_version field)
        archive_path = self.backup_root / backup.filename
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive_path, "w") as archive:
            # Old-style manifest without version info
            old_manifest = {
                "format": "dolphin-flow-backup",
                "format_version": 1,
                "product_version": "1.0.0",
                "backup_id": backup.pk,
                "filename": backup.filename,
                "created_at": "2026-09-04T02:00:00+00:00",
                "created_by": None,
                "database_engine": "postgresql",
                "database_backup_format": "custom",
                "includes_media": True,
                "database_size": 100,
                "media_size": 50,
                # No pg_dump_version, no pg_dump_major_version
            }
            manifest_bytes = json.dumps(old_manifest).encode("utf-8")

            for arcname, data in (
                ("manifest.json", manifest_bytes),
                ("database.dump", b"FAKE-DUMP"),
                ("media.tar.gz", b"FAKE-MEDIA"),
            ):
                info = tarfile.TarInfo(arcname)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

        # Create a Restore for this archive
        restore = Restore.objects.create(
            backup=backup,
            archive_filename=backup.filename,
            requested_by_username="testuser",
        )

        # Mock both pg_dump and pg_restore
        with mock.patch(
            "subprocess.run",
            side_effect=[
                # pg_restore --version
                subprocess.CompletedProcess(
                    ["pg_restore", "--version"],
                    0,
                    stdout="pg_restore (PostgreSQL) 16.3\n",
                    stderr="",
                ),
                # pg_restore --list (validation)
                subprocess.CompletedProcess(
                    ["pg_restore", "--list", str(self.tmp / "database.dump")],
                    0,
                    stdout="; Database dump\n2; 145344 TABLE public accounts_user\n",
                    stderr="",
                ),
                # pg_restore actual restore
                subprocess.CompletedProcess(
                    ["pg_restore", "--clean", "--if-exists"],
                    0,
                    stdout="",
                    stderr="",
                ),
            ],
        ):
            result = RestoreService(restore, archive_path=archive_path).run()

        self.assertEqual(result["status"], Restore.Status.SUCCESS)
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)


FAKE_DUMP_BYTES = b"FAKE-PG-DUMP-CUSTOM-FORMAT" * 20


def _make_fake_pg_restore(fail=False, stderr="", version="16.3"):
    """Patch pg_restore only (tests that never trigger pg_dump).

    This dispatcher handles pg_restore --version, --list, and actual restore.
    """
    def fake_run(command, env=None, capture_output=False, text=False, check=False):
        # pg_restore --version
        if "--version" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"pg_restore (PostgreSQL) {version}\n",
                stderr="",
            )

        # pg_restore --list (validation)
        if "--list" in command:
            if fail:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr=stderr,
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=";\n; PostgreSQL database dump\n;\n"
                "2; 145344 TABLE public accounts_user\n",
                stderr="",
            )

        # pg_restore actual restore
        if fail:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr=stderr,
            )

        return subprocess.CompletedProcess(command, 0)

    return mock.patch("subprocess.run", side_effect=fake_run)


def _make_fake_tools_both(
    fail_restore=False,
    stderr="",
    pg_restore_version="16.3",
    fail_version=False,
):
    """Patch subprocess.run with a dispatcher for pg_dump AND pg_restore.

    This is needed for tests that run the full restore pipeline including
    the safety backup (which runs pg_dump).
    """
    def fake_run(command, env=None, capture_output=False, text=False, check=False):
        cmd_str = " ".join(command) if command else ""

        # pg_dump --version
        if "pg_dump" in cmd_str and "--version" in cmd_str:
            if fail_version:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="pg_dump (PostgreSQL) 16.3\n",
                stderr="",
            )

        # pg_dump actual dump
        if "pg_dump" in cmd_str and "--format=custom" in cmd_str:
            if "--file" in command:
                file_index = command.index("--file")
                dest = Path(command[file_index + 1])
                if dest.parent.exists():
                    dest.write_bytes(FAKE_DUMP_BYTES)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        # pg_restore --version
        if "pg_restore" in cmd_str and "--version" in cmd_str:
            if fail_version:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"pg_restore (PostgreSQL) {pg_restore_version}\n",
                stderr="",
            )

        # pg_restore --list (validation)
        if "--list" in command:
            if fail_restore:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr=stderr,
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=";\n; PostgreSQL database dump\n;\n"
                "2; 145344 TABLE public accounts_user\n",
                stderr="",
            )

        # pg_restore actual restore
        if fail_restore:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr=stderr,
            )

        return subprocess.CompletedProcess(command, 0)

    return mock.patch("subprocess.run", side_effect=fake_run)


class RestoreVersionCompatibilityTestCase(TestCase):
    """Tests for version compatibility checks during restore."""

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
                PG_RESTORE_PATH="pg_restore",
            )
        )

    def make_backup(self, **kwargs):
        defaults = {
            "filename": "DolphinFlow_Backup_2026-09-04_020000.dfbak",
        }
        defaults.update(kwargs)
        return Backup.objects.create(**defaults)

    def build_dfbak(self, filename, manifest, dump=b"DUMP", media=None):
        """Build a .dfbak archive with the given manifest."""
        target = self.backup_root / filename
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

            if media is not None:
                info = tarfile.TarInfo("media.tar.gz")
                info.size = len(media)
                archive.addfile(info, io.BytesIO(media))

        return target

    def test_rejects_newer_dump_version(self):
        """Test that restore rejects when archive has newer pg_dump major version."""
        # Manifest with pg_dump 17 (newer than our pg_restore 16)
        newer_manifest = {
            "format": "dolphin-flow-backup",
            "format_version": 1,
            "product_version": "1.0.0",
            "backup_id": 1,
            "filename": "newer.dfbak",
            "created_at": "2026-09-04T02:00:00+00:00",
            "created_by": None,
            "database_engine": "postgresql",
            "database_backup_format": "custom",
            "includes_media": True,
            "database_size": 100,
            "media_size": 50,
            "pg_dump_version": "17.1",
            "pg_dump_major_version": 17,
        }

        archive_path = self.build_dfbak(
            "newer.dfbak",
            newer_manifest,
            dump=b"DUMP",
            media=b"FAKE-MEDIA",
        )

        restore = Restore.objects.create(
            backup=None,
            archive_filename="newer.dfbak",
            requested_by_username="testuser",
            includes_media=True,
        )

        # pg_restore reports version 16 (older than archive's 17)
        # Use the dispatcher that handles pg_dump (for safety backup) and pg_restore
        with _make_fake_tools_both(
            pg_restore_version="16.3",
        ):
            # This should raise RestoreError before any destructive operation
            with self.assertRaises(RestoreError) as cm:
                RestoreService(restore, archive_path=archive_path).run()

        self.assertIn("نسخه بالاتر", str(cm.exception))
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.FAILED)

    def test_accepts_same_version(self):
        """Test that restore accepts when archive and restore have same major version."""
        same_version_manifest = {
            "format": "dolphin-flow-backup",
            "format_version": 1,
            "product_version": "1.0.0",
            "backup_id": 1,
            "filename": "same.dfbak",
            "created_at": "2026-09-04T02:00:00+00:00",
            "created_by": None,
            "database_engine": "postgresql",
            "database_backup_format": "custom",
            "includes_media": True,
            "database_size": 100,
            "media_size": 50,
            "pg_dump_version": "16.3",
            "pg_dump_major_version": 16,
        }

        archive_path = self.build_dfbak(
            "same.dfbak",
            same_version_manifest,
            dump=b"DUMP",
            media=b"FAKE-MEDIA",
        )

        restore = Restore.objects.create(
            backup=None,
            archive_filename="same.dfbak",
            requested_by_username="testuser",
            includes_media=True,
        )

        # pg_restore reports version 16 (same as archive's 16)
        with _make_fake_tools_both(
            pg_restore_version="16.3",
        ):
            result = RestoreService(restore, archive_path=archive_path).run()

        self.assertEqual(result["status"], Restore.Status.SUCCESS)
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)

    def test_accepts_missing_version_metadata(self):
        """Test that restore works when manifest has no version metadata (backward compat)."""
        old_manifest = {
            "format": "dolphin-flow-backup",
            "format_version": 1,
            "product_version": "1.0.0",
            "backup_id": 1,
            "filename": "old.dfbak",
            "created_at": "2026-09-04T02:00:00+00:00",
            "created_by": None,
            "database_engine": "postgresql",
            "database_backup_format": "custom",
            "includes_media": True,
            "database_size": 100,
            "media_size": 50,
            # No pg_dump_version, no pg_dump_major_version
        }

        archive_path = self.build_dfbak(
            "old.dfbak",
            old_manifest,
            dump=b"DUMP",
            media=b"FAKE-MEDIA",
        )

        restore = Restore.objects.create(
            backup=None,
            archive_filename="old.dfbak",
            requested_by_username="testuser",
            includes_media=True,
        )

        with _make_fake_tools_both(
            pg_restore_version="16.3",
        ):
            result = RestoreService(restore, archive_path=archive_path).run()

        self.assertEqual(result["status"], Restore.Status.SUCCESS)
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)

    def test_translates_unsupported_version_error(self):
        """Test that 'unsupported version (...) in file header' is translated to clear Persian."""
        compatible_manifest = {
            "format": "dolphin-flow-backup",
            "format_version": 1,
            "product_version": "1.0.0",
            "backup_id": 1,
            "filename": "test.dfbak",
            "created_at": "2026-09-04T02:00:00+00:00",
            "created_by": None,
            "database_engine": "postgresql",
            "database_backup_format": "custom",
            "includes_media": True,
            "database_size": 100,
            "media_size": 50,
            "pg_dump_version": "16.3",
            "pg_dump_major_version": 16,
        }

        archive_path = self.build_dfbak(
            "test.dfbak",
            compatible_manifest,
            dump=b"DUMP",
            media=b"FAKE-MEDIA",
        )

        restore = Restore.objects.create(
            backup=None,
            archive_filename="test.dfbak",
            requested_by_username="testuser",
            includes_media=True,
        )

        # pg_restore reports compatible version, but --list fails with
        # "unsupported version (...) in file header"
        with mock.patch(
            "subprocess.run",
            side_effect=[
                # pg_restore --version
                subprocess.CompletedProcess(
                    ["pg_restore", "--version"],
                    0,
                    stdout="pg_restore (PostgreSQL) 16.3\n",
                    stderr="",
                ),
                # pg_restore --list fails with unsupported version error
                subprocess.CompletedProcess(
                    ["pg_restore", "--list", str(self.tmp / "database.dump")],
                    1,
                    stdout="",
                    stderr="pg_restore: unsupported version 17.0 in file header\n",
                ),
            ],
        ):
            with self.assertRaises(RestoreError) as cm:
                RestoreService(restore, archive_path=archive_path).run()

        # Should get translated Persian error, not generic "invalid dump"
        error_msg = str(cm.exception)
        self.assertIn("سازگار نیست", error_msg)
        self.assertNotIn("pg_restore: unsupported version", error_msg)

    def test_rejects_dump_with_missing_manifest(self):
        """Test that restore rejects archive without manifest (but still checks version first)."""
        # Build archive without manifest (will fail validation)
        archive_path = self.backup_root / "no-manifest.dfbak"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w") as archive:
            dump = b"DUMP"
            info = tarfile.TarInfo("database.dump")
            info.size = len(dump)
            archive.addfile(info, io.BytesIO(dump))

        restore = Restore.objects.create(
            backup=None,
            archive_filename="no-manifest.dfbak",
            requested_by_username="testuser",
            includes_media=False,
        )

        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["pg_restore", "--version"],
                0,
                stdout="pg_restore (PostgreSQL) 16.3\n",
                stderr="",
            ),
        ):
            with self.assertRaises(RestoreError) as cm:
                RestoreService(restore, archive_path=archive_path).run()

        self.assertIn("manifest", str(cm.exception).lower())

    def test_restore_does_not_fail_for_version_detection_failure(self):
        """Test that restore doesn't fail when pg_restore version detection fails."""
        old_manifest = {
            "format": "dolphin-flow-backup",
            "format_version": 1,
            "product_version": "1.0.0",
            "backup_id": 1,
            "filename": "test.dfbak",
            "created_at": "2026-09-04T02:00:00+00:00",
            "created_by": None,
            "database_engine": "postgresql",
            "database_backup_format": "custom",
            "includes_media": True,
            "database_size": 100,
            "media_size": 50,
            # No version metadata
        }

        archive_path = self.build_dfbak(
            "test.dfbak",
            old_manifest,
            dump=b"DUMP",
            media=b"FAKE-MEDIA",
        )

        restore = Restore.objects.create(
            backup=None,
            archive_filename="test.dfbak",
            requested_by_username="testuser",
            includes_media=True,
        )

        # pg_restore --version fails, but --list works
        with mock.patch(
            "subprocess.run",
            side_effect=[
                # pg_restore --version fails
                subprocess.CompletedProcess(
                    ["pg_restore", "--version"],
                    1,
                    stdout="",
                    stderr="",
                ),
                # pg_restore --list (validation) - succeeds
                subprocess.CompletedProcess(
                    ["pg_restore", "--list", str(self.tmp / "database.dump")],
                    0,
                    stdout="; Database dump\n2; 145344 TABLE public accounts_user\n",
                    stderr="",
                ),
                # pg_restore actual restore
                subprocess.CompletedProcess(
                    ["pg_restore", "--clean", "--if-exists"],
                    0,
                    stdout="",
                    stderr="",
                ),
            ],
        ):
            result = RestoreService(restore, archive_path=archive_path).run()

        self.assertEqual(result["status"], Restore.Status.SUCCESS)
        restore.refresh_from_db()
        self.assertEqual(restore.status, Restore.Status.SUCCESS)
