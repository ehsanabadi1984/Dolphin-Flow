from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from django.db.models import TextChoices

from backup.models import Restore
from backup.restore_services import RestoreError
from backup.staged_restore_preparation import StagedRestorePreparationService


class StagedRestorePreparationTests(TestCase):
    def setUp(self):
        self.restore = mock.MagicMock()
        self.restore.pk = 456
        self.restore.status = Restore.Status.QUEUED
        self.restore.Status = Restore.Status

        self.service = StagedRestorePreparationService(self.restore)
        self.service._claim_slot = mock.Mock(return_value=True)
        self.service._resolve_archive_path = mock.Mock(return_value=Path("/tmp/source.dfbak"))
        self.service._verify_checksum = mock.Mock()
        self.service._validate_archive = mock.Mock(
            return_value={"includes_media": True}
        )
        self.service._create_safety_backup = mock.Mock(
            return_value=SimpleNamespace(pk=77, filename="safety.dfbak")
        )
        self.service._capture_backup_state = mock.Mock(
            return_value={"filename": "safety.dfbak", "storage_path": "safety.dfbak"}
        )
        self.service._materialize = mock.Mock(
            return_value=(Path("/tmp/database.dump"), Path("/tmp/media.tar.gz"))
        )
        self.service._validate_dump_file = mock.Mock()
        self.service._mark_terminal = mock.Mock()
        self.service._cleanup_temp_dir = mock.Mock()

    @mock.patch("backup.staged_restore_preparation.RestoreOperationLock")
    @mock.patch("backup.staged_restore_preparation.inspect_restore_journals", return_value=[])
    @mock.patch("backup.staged_restore_preparation.RestoreJournal.new")
    @mock.patch("backup.staged_restore_preparation.StagedMediaRestore")
    @mock.patch("backup.staged_restore_preparation.StagedDatabaseRestore")
    def test_success_prepares_resources_and_never_cuts_over(
        self, database_class, media_class, journal_new, inventory, lock_class
    ):
        database = database_class.return_value
        database.database_name = "dolphinflow_restore_456_abcd"
        media = media_class.return_value
        media.stage_dir = Path("/tmp/.media.restore-456-token")
        media.file_count = 3
        media.total_bytes = 120
        journal_new.return_value.operation_id = "a" * 32

        result = self.service.run()

        self.assertEqual(result["status"], "PREPARED")
        self.assertEqual(result["staging_database"], database.database_name)
        database.prepare.assert_called_once_with(Path("/tmp/database.dump"))
        database.close.assert_called_once_with()
        database.drop_database.assert_not_called()
        media.prepare.assert_called_once_with(Path("/tmp/media.tar.gz"))
        media.cleanup.assert_not_called()
        journal_new.assert_called_once()
        self.service._mark_terminal.assert_not_called()
        lock_class.return_value.acquire.assert_called_once_with()
        lock_class.return_value.release.assert_called_once_with()

    @mock.patch("backup.staged_restore_preparation.RestoreOperationLock")
    @mock.patch(
        "backup.staged_restore_preparation.inspect_restore_journals",
        return_value=[{"recovery_required": True}],
    )
    def test_existing_recovery_journal_blocks_new_preparation(
        self, inventory, lock_class
    ):
        result = self.service.run()

        self.assertEqual(result["status"], Restore.Status.QUEUED)
        self.service._claim_slot.assert_not_called()
        self.service._mark_terminal.assert_called_once()
        lock_class.return_value.release.assert_called_once_with()

    @mock.patch("backup.staged_restore_preparation.RestoreOperationLock")
    @mock.patch("backup.staged_restore_preparation.inspect_restore_journals", return_value=[])
    @mock.patch("backup.staged_restore_preparation.StagedMediaRestore")
    @mock.patch("backup.staged_restore_preparation.StagedDatabaseRestore")
    def test_media_failure_drops_prepared_database(
        self, database_class, media_class, inventory, lock_class
    ):
        database = database_class.return_value
        database.database_name = "dolphinflow_restore_456_abcd"
        media_class.return_value.prepare.side_effect = RestoreError("media failed")

        result = self.service.run()

        self.assertEqual(result["status"], Restore.Status.QUEUED)
        database.close.assert_called()
        database.drop_database.assert_called_once_with()
        media_class.return_value.cleanup.assert_called_once_with()
        self.service._mark_terminal.assert_called_once()
