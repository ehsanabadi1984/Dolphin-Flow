from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from backup.models import Backup, Restore
from backup.restore_journal import RestoreJournal
from backup.restore_maintenance import activate_maintenance


class CutoverStagedRestoreCommandTests(TestCase):
    def _environment(self, root):
        root = Path(root)
        backup_root = root / "backups"
        journal_root = root / "journal"
        media_root = root / "media"
        backup_root.mkdir()
        journal_root.mkdir()
        media_root.mkdir()
        override = override_settings(
            BACKUP_ROOT=backup_root,
            RESTORE_JOURNAL_ROOT=journal_root,
            MEDIA_ROOT=media_root,
            RESTORE_DRAIN_TIMEOUT_SECONDS=1,
        )
        override.enable()
        self.addCleanup(override.disable)

        journal = RestoreJournal.new(
            501,
            root=journal_root,
            database={
                "original_name": "dolphinflow",
                "staging_name": "dolphinflow_restore_501_abcdef123456",
                "prepared": True,
                "safety_backup": {
                    "filename": "safety.dfbak",
                    "storage_path": "safety.dfbak",
                    "size": 123,
                    "includes_media": True,
                    "checksum": "a" * 64,
                    "status": Backup.Status.SUCCESS,
                    "is_pre_restore_backup": True,
                    "error_message": "",
                },
            },
            media={
                "included": False,
                "prepared": False,
                "media_root": str(media_root),
            },
            restore={
                "archive_filename": "source.dfbak",
                "product_version": "1.0.0",
                "database_engine": "postgresql",
                "database_backup_format": "custom",
                "includes_media": False,
                "started_at": "2026-11-21T10:00:00+00:00",
                "requested_by_username": "operator",
                "pre_restore_backup_filename": "safety.dfbak",
            },
        )
        return journal, backup_root

    def test_cutover_requires_matching_maintenance_marker(self):
        with TemporaryDirectory() as temp:
            journal, _ = self._environment(temp)
            with self.assertRaises(CommandError):
                call_command(
                    "cutover_staged_restore",
                    operation_id=journal.operation_id,
                    service_units=["dolphinplus-daphne.service"],
                    stdout=StringIO(),
                )
            self.assertEqual(journal.read()["phase"], "PREPARED")

    @mock.patch(
        "backup.management.commands.cutover_staged_restore.assert_database_quiescent",
        return_value={"database": "dolphinflow", "active_sessions": 0},
    )
    @mock.patch(
        "backup.management.commands.cutover_staged_restore.assert_systemd_services_stopped",
        return_value=[{"service": "dolphinplus-daphne.service", "state": "inactive"}],
    )
    @mock.patch(
        "backup.management.commands.cutover_staged_restore.close_restore_worker_connection"
    )
    @mock.patch(
        "backup.management.commands.cutover_staged_restore.StagedRestoreCutover"
    )
    def test_successful_cutover_recreates_audit_rows_and_keeps_maintenance(
        self, cutover_class, close_connection, services_check, database_check
    ):
        with TemporaryDirectory() as temp:
            journal, backup_root = self._environment(temp)
            activate_maintenance(journal.operation_id)

            def complete_journal():
                journal.update(phase="QUIESCING")
                journal.update(phase="DATABASE_SWAPPED")
                journal.update(phase="COMPLETED")
                return {"status": "COMPLETED", "operation_id": journal.operation_id}

            cutover_class.return_value.run.side_effect = complete_journal
            output = StringIO()
            call_command(
                "cutover_staged_restore",
                operation_id=journal.operation_id,
                service_units=["dolphinplus-daphne.service"],
                stdout=output,
            )

            self.assertEqual(journal.read()["phase"], "COMPLETED")
            self.assertTrue((backup_root / ".restore-maintenance").exists())
            self.assertTrue(
                Backup.objects.filter(
                    filename="safety.dfbak",
                    storage_path="safety.dfbak",
                    is_pre_restore_backup=True,
                ).exists()
            )
            audit = Restore.objects.get(
                archive_filename="source.dfbak",
                requested_by_username="operator",
                status=Restore.Status.SUCCESS,
            )
            self.assertIsNotNone(audit.completed_at)
            self.assertIn("Maintenance همچنان فعال است", output.getvalue())
            services_check.assert_called_once_with(["dolphinplus-daphne.service"])
            database_check.assert_called_once()
            self.assertGreaterEqual(close_connection.call_count, 2)

            # A retry after a crash during audit recreation must not cut over again
            # or create duplicate audit rows.
            call_command(
                "cutover_staged_restore",
                operation_id=journal.operation_id,
                service_units=["dolphinplus-daphne.service"],
                stdout=StringIO(),
            )
            cutover_class.return_value.run.assert_called_once()
            self.assertEqual(
                Restore.objects.filter(
                    archive_filename="source.dfbak",
                    requested_by_username="operator",
                    status=Restore.Status.SUCCESS,
                ).count(),
                1,
            )

    @mock.patch(
        "backup.management.commands.cutover_staged_restore.assert_database_quiescent",
        return_value={"database": "dolphinflow", "active_sessions": 0},
    )
    @mock.patch(
        "backup.management.commands.cutover_staged_restore.close_restore_worker_connection"
    )
    @mock.patch(
        "backup.management.commands.cutover_staged_restore.StagedRestoreCutover"
    )
    def test_wsl_manual_service_attestation_uses_same_cutover(
        self, cutover_class, close_connection, database_check
    ):
        with TemporaryDirectory() as temp:
            journal, _ = self._environment(temp)
            activate_maintenance(journal.operation_id)

            def complete_journal():
                journal.update(phase="QUIESCING")
                journal.update(phase="DATABASE_SWAPPED")
                journal.update(phase="COMPLETED")
                return {"status": "COMPLETED", "operation_id": journal.operation_id}

            cutover_class.return_value.run.side_effect = complete_journal
            output = StringIO()
            call_command(
                "cutover_staged_restore",
                operation_id=journal.operation_id,
                services_stopped=True,
                stdout=output,
            )
            self.assertEqual(journal.read()["phase"], "COMPLETED")
            self.assertIn("operator-attestation", output.getvalue())
            database_check.assert_called_once()
            self.assertGreaterEqual(close_connection.call_count, 2)
