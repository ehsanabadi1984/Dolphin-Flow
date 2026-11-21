from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import SimpleTestCase

from backup.restore_services import RestoreError
from backup.staged_media_cutover import StagedMediaCutover


class StagedMediaCutoverTests(SimpleTestCase):
    def test_swap_preserves_previous_media_and_promotes_stage(self):
        with TemporaryDirectory() as temp:
            parent = Path(temp)
            live = parent / "media"
            live.mkdir()
            (live / "old.txt").write_text("old-content")
            stage = parent / ".media.restore-5-token"
            stage.mkdir()
            (stage / "new.txt").write_text("new-content")
            journal = mock.Mock()

            cutover = StagedMediaCutover(stage, journal, media_root=live)
            result = cutover.swap()

            self.assertEqual((live / "new.txt").read_text(), "new-content")
            self.assertEqual((Path(result["previous_path"]) / "old.txt").read_text(), "old-content")
            self.assertFalse(stage.exists())
            journal.update.assert_any_call(phase="MEDIA_SWAPPED")

    def test_rollback_restores_previous_and_keeps_new_tree_as_stage(self):
        with TemporaryDirectory() as temp:
            parent = Path(temp)
            live = parent / "media"
            live.mkdir()
            (live / "old.txt").write_text("old-content")
            stage = parent / ".media.restore-5-token"
            stage.mkdir()
            (stage / "new.txt").write_text("new-content")
            journal = mock.Mock()

            cutover = StagedMediaCutover(stage, journal, media_root=live)
            cutover.swap()
            cutover.rollback()

            self.assertEqual((live / "old.txt").read_text(), "old-content")
            self.assertEqual((stage / "new.txt").read_text(), "new-content")
            self.assertTrue(
                any(call.kwargs.get("phase") == "ROLLBACK_REQUIRED" for call in journal.update.call_args_list)
            )

    def test_rejects_stage_outside_media_parent(self):
        with TemporaryDirectory() as temp:
            parent = Path(temp)
            live = parent / "media"
            live.mkdir()
            other = parent / "elsewhere"
            other.mkdir()
            stage = other / ".media.restore-5-token"
            stage.mkdir()
            with self.assertRaises(RestoreError):
                StagedMediaCutover(stage, mock.Mock(), media_root=live)

    def test_rejects_unrecognized_stage_name(self):
        with TemporaryDirectory() as temp:
            parent = Path(temp)
            live = parent / "media"
            live.mkdir()
            stage = parent / "staging"
            stage.mkdir()
            with self.assertRaises(RestoreError):
                StagedMediaCutover(stage, mock.Mock(), media_root=live)
