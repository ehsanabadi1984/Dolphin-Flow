from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from django.core.management import call_command, CommandError
from django.test import override_settings

from backup.restore_maintenance import activate_maintenance


class RestoreQuiescenceCommandTests(TestCase):
    def test_activate_command_creates_gate_and_prints_operation_id(self):
        with TemporaryDirectory() as temp:
            with override_settings(BACKUP_ROOT=Path(temp) / "backups"):
                output = StringIO()
                call_command(
                    "activate_restore_maintenance",
                    operation_id="a" * 32,
                    stdout=output,
                )

                self.assertTrue((Path(temp) / "backups" / ".restore-maintenance").exists())
                self.assertIn("Operation ID: " + ("a" * 32), output.getvalue())

    @mock.patch(
        "backup.management.commands.verify_restore_quiescence.assert_database_quiescent",
        return_value={"database": "dolphinflow", "active_sessions": 0},
    )
    @mock.patch(
        "backup.management.commands.verify_restore_quiescence.assert_systemd_services_stopped",
        return_value=[
            {"service": "dolphinplus-daphne.service", "state": "inactive"},
        ],
    )
    @mock.patch(
        "backup.management.commands.verify_restore_quiescence.read_maintenance_state",
        return_value={"operation_id": "b" * 32},
    )
    def test_verify_command_reports_quiescence(
        self, state_reader, service_check, database_check
    ):
        output = StringIO()
        call_command(
            "verify_restore_quiescence",
            operation_id="b" * 32,
            service_units=["dolphinplus-daphne.service"],
            stdout=output,
        )

        self.assertIn("Active sessions: 0", output.getvalue())
        self.assertIn("بررسی Quiescence موفق بود", output.getvalue())
        service_check.assert_called_once_with([
            "dolphinplus-daphne.service",
        ])
        database_check.assert_called_once_with()

    @mock.patch(
        "backup.management.commands.verify_restore_quiescence.read_maintenance_state",
        return_value={"operation_id": "c" * 32},
    )
    def test_verify_command_rejects_wrong_operation_id(self, state_reader):
        with self.assertRaises(CommandError):
            call_command(
                "verify_restore_quiescence",
                operation_id="d" * 32,
                service_units=["dolphinplus-celery.service"],
                stdout=StringIO(),
            )
