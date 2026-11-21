from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase

from backup.restore_journal import RestoreJournal


class InspectRestoreRecoveryCommandTests(SimpleTestCase):
    def test_empty_inventory_is_reported(self):
        with TemporaryDirectory() as temp:
            with patch(
                "backup.management.commands.inspect_restore_recovery.inspect_restore_journals",
                return_value=[],
            ):
                output = StringIO()
                call_command("inspect_restore_recovery", stdout=output)

        self.assertIn("هیچ عملیات Restore", output.getvalue())

    def test_terminal_inventory_exits_successfully(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            journal = RestoreJournal.new(301, root=root)
            journal.update(phase="QUIESCING")
            journal.update(phase="DATABASE_SWAPPED")
            journal.update(phase="MEDIA_SWAPPED")
            journal.update(phase="COMPLETED")
            with patch(
                "backup.management.commands.inspect_restore_recovery.inspect_restore_journals",
                return_value=[{
                    "operation_id": journal.operation_id,
                    "restore_id": 301,
                    "phase": "COMPLETED",
                    "updated_at": "2026-11-21T00:00:00+00:00",
                    "status": "TERMINAL",
                    "recovery_required": False,
                    "error": "",
                }],
            ):
                output = StringIO()
                call_command("inspect_restore_recovery", stdout=output)

        self.assertIn("Status: TERMINAL", output.getvalue())
        self.assertIn("Recovery required: NO", output.getvalue())

    def test_interrupted_inventory_returns_command_error(self):
        with patch(
            "backup.management.commands.inspect_restore_recovery.inspect_restore_journals",
            return_value=[{
                "operation_id": "a" * 32,
                "restore_id": 302,
                "phase": "DATABASE_SWAPPED",
                "database": {"staging_name": "dolphinflow_restore_302_token"},
                "media": {
                    "staging_path": "/srv/app/.media.restore-302-token",
                    "prepared": False,
                },
                "status": "INTERRUPTED",
                "recovery_required": True,
                "error": "",
            }],
        ):
            output = StringIO()
            with self.assertRaises(CommandError):
                call_command("inspect_restore_recovery", stdout=output)

        self.assertIn("Status: INTERRUPTED", output.getvalue())
        self.assertIn("Recovery required: YES", output.getvalue())
        self.assertIn("Staging database: dolphinflow_restore_302_token", output.getvalue())
        self.assertIn("Staging media path: /srv/app/.media.restore-302-token", output.getvalue())
        self.assertIn("Media staging prepared: NO", output.getvalue())
