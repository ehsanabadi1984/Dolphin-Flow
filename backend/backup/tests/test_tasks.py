import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from backup.models import Backup, BackupSchedule, BackupStorageDestination, Restore
from backup.tasks import replicate_backup_to_network, run_backup, run_restore


class BackupTaskTests(TestCase):
    def test_restore_cutover_task_can_resume_during_maintenance(self):
        from backup.restore_maintenance_tasks import RestoreMaintenanceAwareTask
        from backup.tasks import RestoreCutoverTask

        self.assertFalse(
            issubclass(RestoreCutoverTask, RestoreMaintenanceAwareTask)
        )

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

            destination = BackupStorageDestination.objects.create(
                name="Test mounted network destination",
                backend_type=BackupStorageDestination.BackendType.MOUNTED_FOLDER,
                remote_path=network_root,
            )
            backup = Backup.objects.create(
                filename=source.name,
                status=Backup.Status.SUCCESS,
                storage_path=source.name,
                size=len(payload),
                checksum=hashlib.sha256(payload).hexdigest(),
                destination=Backup.Destination.NETWORK,
                network_storage=destination,
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
            self.assertEqual(backup.network_storage_path, str(target))
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

    def test_runs_staged_restore_preparation_service(self):
        restore = Restore.objects.create(
            archive_filename="DolphinFlow_Backup_x.dfbak"
        )

        with mock.patch(
            "backup.tasks.StagedRestorePreparationService.run",
            return_value={
                "status": "PREPARED",
                "restore_id": restore.pk,
                "operation_id": "a" * 32,
            },
        ) as mocked_run, mock.patch(
            "backup.tasks.run_restore_cutover.apply_async"
        ) as mocked_cutover:
            result = run_restore(restore.pk)

        mocked_run.assert_called_once_with()
        mocked_cutover.assert_called_once_with(
            args=(restore.pk, "a" * 32),
            queue="restore_cutover",
            task_id=f"restore-cutover-{'a' * 32}",
        )
        self.assertEqual(result["status"], "CUTOVER_QUEUED")

    def test_interrupted_restore_preparation_is_reconciled_before_cutover_dispatch(self):
        restore = Restore.objects.create(
            archive_filename="DolphinFlow_Backup_interrupted.dfbak",
            status=Restore.Status.RESTORING,
        )
        with mock.patch(
            "backup.tasks.recover_interrupted_restore_preparation",
            return_value={
                "status": "CUTOVER_PENDING",
                "restore_id": restore.pk,
                "operation_id": "c" * 32,
            },
        ), mock.patch(
            "backup.tasks.run_restore_cutover.apply_async"
        ) as mocked_cutover:
            result = run_restore(restore.pk)

        mocked_cutover.assert_called_once_with(
            args=(restore.pk, "c" * 32),
            queue="restore_cutover",
            task_id=f"restore-cutover-{'c' * 32}",
        )
        self.assertEqual(result["status"], "CUTOVER_QUEUED")

    def test_prepared_restore_is_dispatched_after_preparation_task_redelivery(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        from backup.restore_journal import RestoreJournal

        restore = Restore.objects.create(
            archive_filename="DolphinFlow_Backup_prepared.dfbak",
            status=Restore.Status.PREPARED,
        )
        with TemporaryDirectory() as temp:
            journal_root = Path(temp) / ".restore-journal"
            RestoreJournal.new(
                restore.pk,
                root=journal_root,
                database={"prepared": True},
                media={"included": False},
            )
            with mock.patch(
                "backup.tasks.inspect_restore_journals",
                return_value=[{
                    "restore_id": restore.pk,
                    "operation_id": "b" * 32,
                    "phase": "PREPARED",
                    "status": "PREPARED",
                }],
            ), mock.patch(
                "backup.tasks.run_restore_cutover.apply_async"
            ) as mocked_cutover:
                result = run_restore(restore.pk)

        mocked_cutover.assert_called_once_with(
            args=(restore.pk, "b" * 32),
            queue="restore_cutover",
            task_id=f"restore-cutover-{'b' * 32}",
        )
        self.assertEqual(result["status"], "CUTOVER_QUEUED")
