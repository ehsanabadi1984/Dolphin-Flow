from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import SimpleTestCase

from backup.restore_journal import RestoreJournal
from backup.restore_services import RestoreError
from backup.staged_restore_cutover import StagedRestoreCutover


class StagedRestoreCutoverTests(SimpleTestCase):
    def _journal(self, root, media_included=True):
        parent = Path(root)
        media_root = parent / "media"
        media_root.mkdir()
        stage = parent / ".media.restore-7-token"
        if media_included:
            stage.mkdir()
        return RestoreJournal.new(
            7,
            root=parent / "journal",
            database={"prepared": True, "staging_name": "dolphinflow_restore_7_abcdef123456"},
            media={
                "included": media_included,
                "prepared": media_included,
                "media_root": str(media_root),
                "staging_path": str(stage) if media_included else "",
            },
        ), media_root

    @mock.patch("backup.staged_restore_cutover.StagedMediaCutover")
    @mock.patch("backup.staged_restore_cutover.StagedDatabaseCutover")
    def test_success_promotes_database_and_media_and_completes_journal(
        self, database_cls, media_cls
    ):
        with TemporaryDirectory() as temp:
            journal, media_root = self._journal(temp)
            def successful_database_swap():
                journal.update(phase="QUIESCING")
                journal.update(phase="DATABASE_SWAPPED")
                return {"live_database": "dolphinflow"}

            def successful_media_swap():
                journal.update(phase="MEDIA_SWAPPED")
                return {"live_path": str(media_root)}

            database_cls.return_value.swap.side_effect = successful_database_swap
            media_cls.return_value.swap.side_effect = successful_media_swap

            result = StagedRestoreCutover(journal, media_root=media_root).run()

            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(journal.read()["phase"], "COMPLETED")
            database_cls.return_value.swap.assert_called_once()
            media_cls.return_value.swap.assert_called_once()

    @mock.patch("backup.staged_restore_cutover.StagedMediaCutover")
    @mock.patch("backup.staged_restore_cutover.StagedDatabaseCutover")
    def test_media_failure_rolls_back_both_resources_and_marks_terminal(
        self, database_cls, media_cls
    ):
        with TemporaryDirectory() as temp:
            journal, media_root = self._journal(temp)
            database_cls.return_value.swap.side_effect = lambda: (
                journal.update(phase="QUIESCING"),
                journal.update(phase="DATABASE_SWAPPED"),
                {"live_database": "dolphinflow"},
            )[-1]
            media_cls.return_value.swap.side_effect = OSError("simulated media failure")

            with self.assertRaises(RestoreError):
                StagedRestoreCutover(journal, media_root=media_root).run()

            media_cls.return_value.rollback.assert_called_once_with(update_journal=False)
            database_cls.return_value.rollback.assert_called_once_with(finalize_journal=False)
            self.assertEqual(journal.read()["phase"], "ROLLED_BACK")

    def test_unprepared_journal_is_rejected_before_cutover(self):
        with TemporaryDirectory() as temp:
            journal, media_root = self._journal(temp)
            journal.update(database={"prepared": False})

            with self.assertRaises(RestoreError):
                StagedRestoreCutover(journal, media_root=media_root).run()

            self.assertEqual(journal.read()["phase"], "PREPARED")
