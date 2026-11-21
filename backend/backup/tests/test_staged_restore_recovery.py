import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from django.test import override_settings

from backup.restore_journal import RestoreJournal
from backup.restore_maintenance import activate_maintenance, deactivate_maintenance
from backup.restore_services import RestoreError
from backup.staged_restore_recovery import StagedRestoreRecovery


class StagedRestoreRecoveryClassificationTests(TestCase):
    def test_classifies_database_states_from_atomic_rename_protocol(self):
        cases = (
            ({"live": True, "previous": False, "staging": True}, "NOT_SWAPPED"),
            ({"live": False, "previous": True, "staging": True}, "OLD_MOVED"),
            ({"live": True, "previous": True, "staging": False}, "NEW_PROMOTED"),
        )
        for state, expected in cases:
            with self.subTest(state=state):
                self.assertEqual(
                    StagedRestoreRecovery._classify_resource(state, "database"),
                    expected,
                )

    def test_rejects_ambiguous_or_incomplete_database_states(self):
        cases = (
            {"live": False, "previous": False, "staging": True},
            {"live": True, "previous": True, "staging": True},
            {"live": False, "previous": True, "staging": False},
            {"live": False, "previous": False, "staging": False},
        )
        for state in cases:
            with self.subTest(state=state):
                with self.assertRaises(RestoreError):
                    StagedRestoreRecovery._classify_resource(state, "database")

    def test_classification_is_independent_of_journal_flags(self):
        # Recovery must use observed resource names, not potentially stale
        # booleans written immediately before/after a process crash.
        observed = {"live": True, "previous": True, "staging": False}
        self.assertEqual(
            StagedRestoreRecovery._classify_resource(observed, "database"),
            "NEW_PROMOTED",
        )


    def test_classifies_media_states_at_each_rename_boundary(self):
        cases = (
            ({"live": True, "previous": False, "staging": True}, "NOT_SWAPPED"),
            ({"live": False, "previous": True, "staging": True}, "OLD_MOVED"),
            ({"live": True, "previous": True, "staging": False}, "NEW_PROMOTED"),
        )
        for state, expected in cases:
            with self.subTest(state=state):
                self.assertEqual(
                    StagedRestoreRecovery._classify_resource(state, "media"),
                    expected,
                )

    def test_rejects_every_ambiguous_media_state(self):
        cases = (
            {"live": False, "previous": False, "staging": True},
            {"live": True, "previous": True, "staging": True},
            {"live": False, "previous": True, "staging": False},
            {"live": False, "previous": False, "staging": False},
        )
        for state in cases:
            with self.subTest(state=state):
                with self.assertRaises(RestoreError):
                    StagedRestoreRecovery._classify_resource(state, "media")



class _FakeCursor:
    def __init__(self, databases):
        self.databases = databases
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT 1 FROM pg_database"):
            self.row = (1,) if params[0] in self.databases else None
            return
        match = re.match(
            r'ALTER DATABASE "([^"]+)" RENAME TO "([^"]+)"',
            sql,
        )
        if not match:
            raise AssertionError(f"Unexpected SQL: {sql}")
        old, new = match.groups()
        if old not in self.databases or new in self.databases:
            raise AssertionError(f"Invalid fake database rename: {old} -> {new}")
        self.databases.remove(old)
        self.databases.add(new)

    def fetchone(self):
        return self.row


class _FakeAdmin:
    def __init__(self, databases):
        self.databases = databases
        self.ops = self

    def quote_name(self, name):
        return f'"{name}"'

    def cursor(self):
        return _FakeCursor(self.databases)

    def close(self):
        pass


class StagedRestoreRecoveryRollbackTests(TestCase):
    def test_crash_after_both_promotions_restores_previous_db_and_media(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            backup_root = root / "backups"
            journal_root = root / "journals"
            media_root = root / "media"
            media_root.mkdir()
            stage_media = root / ".media.restore-42-token"
            previous_media = root / ".media.previous-token"
            media_root.mkdir(exist_ok=True)
            previous_media.mkdir()
            (media_root / "new.txt").write_text("new", encoding="utf-8")
            (previous_media / "old.txt").write_text("old", encoding="utf-8")

            override = override_settings(
                BACKUP_ROOT=backup_root,
                RESTORE_JOURNAL_ROOT=journal_root,
                MEDIA_ROOT=media_root,
                DATABASES={
                    "default": {
                        "ENGINE": "django.db.backends.postgresql",
                        "NAME": "dolphinflow",
                        "USER": "dolphin",
                        "PASSWORD": "test",
                        "HOST": "127.0.0.1",
                        "PORT": "5432",
                        "OPTIONS": {},
                    }
                },
            )
            override.enable()
            self.addCleanup(override.disable)

            journal = RestoreJournal.new(
                42,
                root=journal_root,
                database={
                    "live_name": "dolphinflow",
                    "previous_name": "dolphinflow_previous",
                    "staging_name": "dolphinflow_restore_42_token",
                    "prepared": True,
                },
                media={
                    "included": True,
                    "live_path": str(media_root),
                    "staging_path": str(stage_media),
                    "previous_path": str(previous_media),
                    "prepared": True,
                },
            )
            journal.update(phase="QUIESCING")
            journal.update(phase="DATABASE_SWAPPED")
            journal.update(phase="MEDIA_SWAPPED")
            activate_maintenance(journal.operation_id)
            self.addCleanup(deactivate_maintenance, journal.operation_id)

            databases = {"dolphinflow", "dolphinflow_previous"}
            admin = _FakeAdmin(databases)
            recovery = StagedRestoreRecovery(journal)

            with (
                patch.object(recovery, "_admin", return_value=admin),
                patch("backup.staged_restore_recovery.assert_systemd_services_stopped"),
                patch("backup.staged_restore_recovery.assert_database_quiescent"),
                patch("backup.staged_restore_recovery.close_restore_worker_connection"),
            ):
                result = recovery.rollback(service_units=["dolphinplus-daphne.service"])

            self.assertEqual(result["status"], "ROLLED_BACK")
            self.assertEqual(journal.read()["phase"], "ROLLED_BACK")
            self.assertEqual(databases, {"dolphinflow", "dolphinflow_restore_42_token"})
            self.assertEqual((media_root / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual((stage_media / "new.txt").read_text(encoding="utf-8"), "new")
            self.assertFalse(previous_media.exists())

    def test_recovery_can_resume_after_interruption_during_media_rollback(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            backup_root = root / "backups"
            journal_root = root / "journals"
            media_root = root / "media"
            media_root.mkdir()
            stage_media = root / ".media.restore-43-token"
            previous_media = root / ".media.previous-token"
            previous_media.mkdir()
            (media_root / "new.txt").write_text("new", encoding="utf-8")
            (previous_media / "old.txt").write_text("old", encoding="utf-8")

            override = override_settings(
                BACKUP_ROOT=backup_root,
                RESTORE_JOURNAL_ROOT=journal_root,
                MEDIA_ROOT=media_root,
                DATABASES={
                    "default": {
                        "ENGINE": "django.db.backends.postgresql",
                        "NAME": "dolphinflow",
                        "USER": "dolphin",
                        "PASSWORD": "test",
                        "HOST": "127.0.0.1",
                        "PORT": "5432",
                        "OPTIONS": {},
                    }
                },
            )
            override.enable()
            self.addCleanup(override.disable)

            journal = RestoreJournal.new(
                43,
                root=journal_root,
                database={
                    "live_name": "dolphinflow",
                    "previous_name": "dolphinflow_previous",
                    "staging_name": "dolphinflow_restore_43_token",
                    "prepared": True,
                },
                media={
                    "included": True,
                    "live_path": str(media_root),
                    "staging_path": str(stage_media),
                    "previous_path": str(previous_media),
                    "prepared": True,
                },
            )
            journal.update(phase="QUIESCING")
            journal.update(phase="DATABASE_SWAPPED")
            journal.update(phase="MEDIA_SWAPPED")
            activate_maintenance(journal.operation_id)
            self.addCleanup(deactivate_maintenance, journal.operation_id)

            databases = {"dolphinflow", "dolphinflow_previous"}
            admin = _FakeAdmin(databases)
            recovery = StagedRestoreRecovery(journal)
            common_patches = (
                patch.object(recovery, "_admin", return_value=admin),
                patch("backup.staged_restore_recovery.assert_systemd_services_stopped"),
                patch("backup.staged_restore_recovery.assert_database_quiescent"),
                patch("backup.staged_restore_recovery.close_restore_worker_connection"),
            )

            for mocked in common_patches:
                mocked.start()
                self.addCleanup(mocked.stop)

            path_type = type(media_root)
            original_rename = path_type.rename
            fail_once = {"value": True}

            def interrupt_media_rollback(path_object, target):
                if path_object == media_root and fail_once["value"]:
                    fail_once["value"] = False
                    raise OSError("simulated process interruption during media rollback")
                return original_rename(path_object, target)

            with patch.object(
                path_type,
                "rename",
                autospec=True,
                side_effect=interrupt_media_rollback,
            ):
                with self.assertRaises(OSError):
                    recovery.rollback(service_units=["dolphinplus-daphne.service"])

            # Database rollback completed before media rollback was interrupted.
            self.assertEqual(databases, {"dolphinflow", "dolphinflow_restore_43_token"})
            self.assertEqual(journal.read()["phase"], "ROLLBACK_REQUIRED")
            self.assertTrue((media_root / "new.txt").exists())
            self.assertTrue((previous_media / "old.txt").exists())

            # A second invocation observes the actual partial state and finishes.
            result = recovery.rollback(service_units=["dolphinplus-daphne.service"])

            self.assertEqual(result["status"], "ROLLED_BACK")
            self.assertEqual(journal.read()["phase"], "ROLLED_BACK")
            self.assertEqual(databases, {"dolphinflow", "dolphinflow_restore_43_token"})
            self.assertEqual((media_root / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual((stage_media / "new.txt").read_text(encoding="utf-8"), "new")
            self.assertFalse(previous_media.exists())
