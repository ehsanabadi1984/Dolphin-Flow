from unittest import mock

from django.test import TestCase

from backup.models import Backup
from backup.tasks import run_backup


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