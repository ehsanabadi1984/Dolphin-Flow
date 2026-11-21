from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from backup.restore_journal import RestoreJournal
from backup.restore_recovery import inspect_restore_journals
from backup.restore_services import RestoreError


class RestoreRecoveryInventoryTests(SimpleTestCase):
    def test_missing_journal_directory_returns_empty_inventory(self):
        with TemporaryDirectory() as temp:
            self.assertEqual(
                inspect_restore_journals(root=Path(temp) / "not-created"),
                [],
            )

    def test_interrupted_journals_are_reported_without_mutation(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            journal = RestoreJournal.new(
                201,
                root=root,
                database={"original": "dolphinflow", "staging": "restore_201"},
                media={"live": "/srv/app/media", "staging": "/srv/app/.media-stage"},
            )
            journal.update(phase="QUIESCING")

            before = journal.path.read_bytes()
            inventory = inspect_restore_journals(root=root)

            self.assertEqual(len(inventory), 1)
            self.assertEqual(inventory[0]["restore_id"], 201)
            self.assertEqual(inventory[0]["phase"], "QUIESCING")
            self.assertEqual(inventory[0]["status"], "INTERRUPTED")
            self.assertTrue(inventory[0]["recovery_required"])
            self.assertEqual(journal.path.read_bytes(), before)

    def test_terminal_journals_do_not_require_recovery(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            completed = RestoreJournal.new(202, root=root)
            completed.update(phase="QUIESCING")
            completed.update(phase="ROLLBACK_REQUIRED")
            completed.update(phase="ROLLED_BACK")

            inventory = inspect_restore_journals(root=root)

            self.assertEqual(inventory[0]["phase"], "ROLLED_BACK")
            self.assertEqual(inventory[0]["status"], "TERMINAL")
            self.assertFalse(inventory[0]["recovery_required"])

    def test_corrupt_and_unexpected_json_files_are_reported(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            root.mkdir()
            corrupt_id = "a" * 32
            (root / f"{corrupt_id}.json").write_text("{broken", encoding="utf-8")
            (root / "unexpected.json").write_text("{}", encoding="utf-8")

            inventory = inspect_restore_journals(root=root)

            self.assertEqual(len(inventory), 2)
            self.assertTrue(all(item["status"] == "INVALID" for item in inventory))
            self.assertTrue(all(item["recovery_required"] for item in inventory))

    def test_lock_and_temporary_files_are_ignored(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            root.mkdir()
            (root / ".restore-operation.lock").write_text("{}", encoding="utf-8")
            (root / ".partial.tmp").write_text("partial", encoding="utf-8")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            self.assertEqual(inspect_restore_journals(root=root), [])


    def test_symlink_journal_is_reported_invalid_without_reading_target(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            root.mkdir()
            external = Path(temp) / "external.json"
            external.write_text(
                '{"schema_version":1,"operation_id":"%s","restore_id":777,'
                '"phase":"PREPARED","created_at":"now","updated_at":"now",'
                '"database":{},"media":{},"error":""}' % ("c" * 32),
                encoding="utf-8",
            )
            (root / f'{"c" * 32}.json').symlink_to(external)

            inventory = inspect_restore_journals(root=root)

            self.assertEqual(len(inventory), 1)
            self.assertEqual(inventory[0]["status"], "INVALID")
            self.assertTrue(inventory[0]["recovery_required"])
            self.assertIn("Symlink", inventory[0]["error"])

    def test_non_directory_journal_path_is_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "not-a-directory"
            root.write_text("file", encoding="utf-8")

            with self.assertRaises(RestoreError):
                inspect_restore_journals(root=root)
