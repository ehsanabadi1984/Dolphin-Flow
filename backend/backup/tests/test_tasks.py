from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from backup.models import Backup, BackupSchedule, Restore
from backup.tasks import replicate_backup_to_network, run_backup, run_restore


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

    def test_process_backup_schedules_queues_due_schedule(self):
        schedule = BackupSchedule.objects.create(
            name="Immediate backup",
            frequency=BackupSchedule.Frequency.ONCE,
            run_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        with mock.patch("backup.tasks.run_backup.delay") as mocked_delay:
            from backup.tasks import process_backup_schedules

            result = process_backup_schedules()

        schedule.refresh_from_db()
        self.assertEqual(
            result["queued_backup_ids"],
            [schedule.backups.get().pk],
        )
        self.assertFalse(schedule.enabled)
        self.assertIsNone(schedule.next_run_at)
        mocked_delay.assert_called_once_with(schedule.backups.get().pk)

    def test_replicate_backup_to_network_copies_and_verifies_archive(self):
        payload = b"network-backup-test"
        with TemporaryDirectory() as local_root, TemporaryDirectory() as network_root:
            source = Path(local_root) / "backup.dfbak"
            source.write_bytes(payload)

            backup = Backup.objects.create(
                filename=source.name,
                status=Backup.Status.SUCCESS,
                storage_path=source.name,
                size=len(payload),
                checksum="",
                destination=Backup.Destination.NETWORK,
                network_status=Backup.NetworkStatus.PENDING,
            )

            with override_settings(
                BACKUP_ROOT=local_root,
                BACKUP_NETWORK_ROOT=network_root,
            ):
                result = replicate_backup_to_network(backup.pk)

            backup.refresh_from_db()
            target = Path(network_root) / source.name

            self.assertEqual(result["status"], "success")
            self.assertEqual(backup.network_status, Backup.NetworkStatus.SUCCESS)
            self.assertEqual(backup.network_storage_path, source.name)
            self.assertEqual(backup.network_size, len(payload))
            self.assertEqual(backup.network_checksum, backup.checksum)
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes(), payload)

    def test_replicate_backup_to_network_marks_failure_when_destination_is_missing(self):
        with TemporaryDirectory() as local_root:
            source = Path(local_root) / "backup.dfbak"
            source.write_bytes(b"network-backup-test")

            backup = Backup.objects.create(
                filename=source.name,
                status=Backup.Status.SUCCESS,
                storage_path=source.name,
                destination=Backup.Destination.NETWORK,
                network_status=Backup.NetworkStatus.PENDING,
            )

            with override_settings(
                BACKUP_ROOT=local_root,
                BACKUP_NETWORK_ROOT=str(
                    Path(local_root) / "missing-network-share"
                ),
            ):
                result = replicate_backup_to_network(backup.pk)

            backup.refresh_from_db()

            self.assertEqual(result["status"], "failed")
            self.assertEqual(
                backup.network_status,
                Backup.NetworkStatus.FAILED,
            )
            self.assertTrue(backup.network_error)

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
