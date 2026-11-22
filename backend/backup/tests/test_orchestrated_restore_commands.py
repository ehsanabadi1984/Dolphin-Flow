from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from backup.models import Restore
from backup.restore_journal import RestoreJournal
from backup.restore_maintenance import activate_maintenance, read_maintenance_state


class OrchestratedRestoreCommandTests(TestCase):
    def _environment(self, root, phase="PREPARED"):
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

        restore = Restore.objects.create(
            archive_filename="source.dfbak",
            status=Restore.Status.PREPARED,
        )
        journal = RestoreJournal.new(
            restore.pk,
            root=journal_root,
            database={
                "original_name": "dolphinflow",
                "staging_name": "dolphinflow_restore_test",
                "prepared": True,
            },
            media={
                "included": False,
                "prepared": False,
                "media_root": str(media_root),
            },
        )
        if phase != "PREPARED":
            journal.update(phase="QUIESCING")
        return restore, journal, backup_root

    def _invoke(self, operation_id, *units):
        args = ["--operation-id", operation_id]
        for unit in units:
            args.extend(["--service-unit", unit])
        call_command("orchestrate_staged_restore", *args)

    @mock.patch("backup.management.commands.orchestrate_staged_restore._finalize_restore_audit")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.assert_database_quiescent",
                return_value={"database": "dolphinflow", "active_sessions": 0})
    @mock.patch("backup.management.commands.orchestrate_staged_restore.assert_systemd_services_stopped")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.close_restore_worker_connection")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.Command._health_check")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.Command._start")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.Command._stop")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.Command._active_units")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.StagedRestoreCutover")
    def test_success_completes_cutover_starts_services_and_clears_maintenance(
        self, cutover_class, active_units, stop, start, health, close_connection,
        services_stopped, database_quiescent, finalize_audit
    ):
        with TemporaryDirectory() as temp:
            restore, journal, _ = self._environment(temp)
            unit = "dolphinplus-daphne.service"
            active_units.return_value = [unit]

            def complete():
                journal.update(phase="QUIESCING")
                journal.update(phase="DATABASE_SWAPPED")
                journal.update(phase="VALIDATING")
                return {"status": "VALIDATING"}

            cutover_class.return_value.run.side_effect = complete
            self._invoke(journal.operation_id, unit)

            self.assertEqual(journal.read()["phase"], "COMPLETED")
            self.assertIsNone(read_maintenance_state())
            stop.assert_called_once_with([unit])
            start.assert_called_once_with([unit])
            self.assertEqual(health.call_count, 2)
            database_quiescent.assert_called_once()
            finalize_audit.assert_called_once()
            restore.refresh_from_db()
            self.assertEqual(restore.status, Restore.Status.PREPARED)

    @mock.patch("backup.management.commands.orchestrate_staged_restore.Command._health_check")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.Command._start")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.Command._stop")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.Command._active_units")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.StagedRestoreRecovery")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.StagedRestoreCutover")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.assert_systemd_services_stopped")
    @mock.patch("backup.management.commands.orchestrate_staged_restore.assert_database_quiescent",
                return_value={"database": "dolphinflow", "active_sessions": 0})
    @mock.patch("backup.management.commands.orchestrate_staged_restore.close_restore_worker_connection")
    def test_cutover_failure_rolls_back_and_restores_previous_service_state(
        self, close_connection, database_quiescent, services_stopped, cutover_class,
        recovery_class, active_units, stop, start, health
    ):
        with TemporaryDirectory() as temp:
            restore, journal, _ = self._environment(temp)
            unit = "dolphinplus-daphne.service"
            active_units.return_value = [unit]

            def fail_after_database_swap():
                journal.update(phase="QUIESCING")
                journal.update(phase="DATABASE_SWAPPED")
                raise RuntimeError("simulated media failure")

            cutover_class.return_value.run.side_effect = fail_after_database_swap

            def rollback(**kwargs):
                journal.update(phase="ROLLBACK_REQUIRED")
                journal.update(phase="ROLLED_BACK")

            recovery_class.return_value.rollback.side_effect = rollback

            with self.assertRaises(CommandError):
                self._invoke(journal.operation_id, unit)

            self.assertEqual(journal.read()["phase"], "ROLLED_BACK")
            self.assertIsNone(read_maintenance_state())
            recovery_class.return_value.rollback.assert_called_once_with(service_units=[unit])
            start.assert_called_once_with([unit])
            restore.refresh_from_db()
            self.assertEqual(restore.status, Restore.Status.FAILED)


class RecoverOrchestratedRestoreCommandTests(TestCase):
    def _environment(self, root, phase="PREPARED"):
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
        )
        override.enable()
        self.addCleanup(override.disable)

        restore = Restore.objects.create(
            archive_filename="source.dfbak",
            status=Restore.Status.RESTORING,
        )
        unit = "dolphinplus-daphne.service"
        journal = RestoreJournal.new(
            restore.pk,
            root=journal_root,
            database={"prepared": True},
            media={"included": False, "media_root": str(media_root)},
            restore={"orchestrator": {
                "service_units": [unit],
                "previously_active_units": [unit],
            }},
        )
        if phase != "PREPARED":
            journal.update(phase="QUIESCING")
        activate_maintenance(journal.operation_id)
        return restore, journal, unit

    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._health")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._active_units")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._systemctl")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.assert_systemd_services_stopped")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.close_restore_worker_connection")
    def test_recovery_of_prepared_operation_restarts_prior_services_and_clears_gate(
        self, close_connection, services_stopped, systemctl, active_units, health
    ):
        with TemporaryDirectory() as temp:
            restore, journal, unit = self._environment(temp)
            active_units.return_value = [unit]

            call_command("recover_orchestrated_restore", operation_id=journal.operation_id)

            systemctl.assert_any_call("stop", unit)
            systemctl.assert_any_call("start", unit)
            health.assert_called_once()
            self.assertIsNone(read_maintenance_state())
            self.assertEqual(journal.read()["phase"], "PREPARED")
            restore.refresh_from_db()
            self.assertEqual(restore.status, Restore.Status.RESTORING)

    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._health")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._active_units")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._systemctl")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.assert_systemd_services_stopped")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.close_restore_worker_connection")
    def test_failed_recovery_keeps_maintenance_gate_and_reports_error(
        self, close_connection, services_stopped, systemctl, active_units, health
    ):
        with TemporaryDirectory() as temp:
            restore, journal, unit = self._environment(temp)
            active_units.return_value = [unit]
            health.side_effect = RuntimeError("health check failed")

            with self.assertRaises(CommandError):
                call_command("recover_orchestrated_restore", operation_id=journal.operation_id)

            self.assertEqual(read_maintenance_state()["operation_id"], journal.operation_id)
            systemctl.assert_any_call("stop", unit)

    @mock.patch("backup.management.commands.recover_orchestrated_restore.call_command")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._health")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._active_units")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.Command._systemctl")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.assert_systemd_services_stopped")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.close_restore_worker_connection")
    @mock.patch("backup.management.commands.recover_orchestrated_restore.StagedRestoreRecovery")
    def test_crash_after_cutover_started_rolls_back_before_restarting_services(
        self, recovery_class, close_connection, services_stopped, systemctl,
        active_units, health, management_call
    ):
        with TemporaryDirectory() as temp:
            restore, journal, unit = self._environment(temp, phase="QUIESCING")
            active_units.return_value = [unit]

            def rollback(**kwargs):
                journal.update(phase="ROLLBACK_REQUIRED")
                journal.update(phase="ROLLED_BACK")

            recovery_class.return_value.rollback.side_effect = rollback

            call_command("recover_orchestrated_restore", operation_id=journal.operation_id)

            recovery_class.return_value.rollback.assert_called_once_with(
                service_units=[unit],
                lock_held=True,
            )
            management_call.assert_called_once_with("migrate", interactive=False, verbosity=0)
            systemctl.assert_any_call("start", unit)
            self.assertIsNone(read_maintenance_state())
            self.assertEqual(journal.read()["phase"], "ROLLED_BACK")
            restore.refresh_from_db()
            self.assertEqual(restore.status, Restore.Status.FAILED)
