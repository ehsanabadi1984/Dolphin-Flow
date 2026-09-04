from unittest import mock

from django.test import TestCase

from backup.models import Backup, Restore
from backup.tasks import run_backup, run_restore


class BackupTaskTests(TestCase):
    def test_missing_backup_returns_missing_status(self):
        result = run_backup(999_999)
        self.assertEqual(
            result,
            {"status": "missing", "backup_id": 999_999},
        )

    def test_runs_backup_service(self):
        backup = Backup.objects.create()

        with mock.patch(
            "backup.tasks.BackupService.run",
            return_value={
                "status": Backup.Status.SUCCESS,
                "backup_id": backup.pk,
            },
        ) as mocked_run:
            result = run_backup(backup.pk)

        mocked_run.assert_called_once_with()
        self.assertEqual(result["status"], Backup.Status.SUCCESS)

    def test_missing_restore_returns_missing_status(self):
        result = run_restore(999_999)
        self.assertEqual(
            result,
            {"status": "missing", "restore_id": 999_999},
        )

    def test_runs_restore_service(self):
        restore = Restore.objects.create(
            archive_filename="DolphinFlow_Backup_x.dfbak"
        )

        with mock.patch(
            "backup.tasks.RestoreService.run",
            return_value={
                "status": Restore.Status.SUCCESS,
                "restore_id": restore.pk,
            },
        ) as mocked_run:
            result = run_restore(restore.pk)

        mocked_run.assert_called_once_with()
        self.assertEqual(result["status"], Restore.Status.SUCCESS)