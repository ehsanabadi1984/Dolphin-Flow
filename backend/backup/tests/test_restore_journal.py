import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings

from backup.restore_services import RestoreError
from backup.restore_journal import RestoreJournal


class RestoreJournalTests(SimpleTestCase):
    def test_new_journal_is_durable_and_can_be_reopened(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            journal = RestoreJournal.new(
                123,
                root=root,
                database={"staging": "dolphinflow_restore_test"},
                media={"staging": "/srv/app/.media.restore-test"},
            )

            reopened = RestoreJournal(journal.operation_id, root=root)
            payload = reopened.read()

            self.assertEqual(payload["restore_id"], 123)
            self.assertEqual(payload["phase"], "PREPARED")
            self.assertEqual(
                payload["database"]["staging"],
                "dolphinflow_restore_test",
            )
            self.assertTrue(reopened.path.is_file())
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(reopened.path).st_mode & 0o777, 0o600)

    def test_phase_transitions_follow_cutover_order(self):
        with TemporaryDirectory() as temp:
            journal = RestoreJournal.new(124, root=Path(temp) / "journal")

            for phase in (
                "QUIESCING",
                "DATABASE_SWAPPED",
                "MEDIA_SWAPPED",
                "COMPLETED",
            ):
                payload = journal.update(phase=phase)

            self.assertEqual(payload["phase"], "COMPLETED")

    def test_invalid_phase_transition_is_rejected(self):
        with TemporaryDirectory() as temp:
            journal = RestoreJournal.new(125, root=Path(temp) / "journal")

            with self.assertRaises(RestoreError):
                journal.update(phase="MEDIA_SWAPPED")

            self.assertEqual(journal.read()["phase"], "PREPARED")

    def test_rollback_path_is_recorded_and_terminal(self):
        with TemporaryDirectory() as temp:
            journal = RestoreJournal.new(126, root=Path(temp) / "journal")
            journal.update(phase="ROLLBACK_REQUIRED", error="media swap failed")
            payload = journal.update(phase="ROLLED_BACK")

            self.assertEqual(payload["phase"], "ROLLED_BACK")
            self.assertEqual(payload["error"], "media swap failed")

            with self.assertRaises(RestoreError):
                journal.update(phase="PREPARED")

    def test_updates_merge_resource_metadata_without_losing_other_fields(self):
        with TemporaryDirectory() as temp:
            journal = RestoreJournal.new(
                127,
                root=Path(temp) / "journal",
                database={"original": "dolphinflow"},
                media={"live": "/srv/app/media"},
            )
            payload = journal.update(
                database={"staging": "dolphinflow_restore_127"},
                media={"previous": "/srv/app/.media.previous-127"},
            )

            self.assertEqual(
                payload["database"],
                {
                    "original": "dolphinflow",
                    "staging": "dolphinflow_restore_127",
                },
            )
            self.assertEqual(
                payload["media"],
                {
                    "live": "/srv/app/media",
                    "previous": "/srv/app/.media.previous-127",
                },
            )

    def test_invalid_operation_id_and_media_root_location_are_rejected(self):
        with TemporaryDirectory() as temp:
            with self.assertRaises(RestoreError):
                RestoreJournal("../escape", root=Path(temp))

            media_root = Path(temp) / "media"
            with override_settings(MEDIA_ROOT=media_root):
                with self.assertRaises(RestoreError):
                    RestoreJournal("a" * 32, root=media_root / ".journal")

    def test_corrupt_journal_is_rejected(self):
        with TemporaryDirectory() as temp:
            journal = RestoreJournal.new(128, root=Path(temp) / "journal")
            journal.path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(RestoreError):
                journal.read()

    def test_delete_removes_only_its_journal(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            first = RestoreJournal.new(129, root=root)
            second = RestoreJournal.new(130, root=root)

            first.delete()

            self.assertFalse(first.path.exists())
            self.assertTrue(second.path.exists())
