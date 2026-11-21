from unittest import TestCase, mock

from backup.restore_services import RestoreError
from backup.staged_database_cutover import StagedDatabaseCutover


class StagedDatabaseCutoverValidationTests(TestCase):
    def test_rejects_live_database_as_staging(self):
        with self.assertRaises(RestoreError):
            StagedDatabaseCutover(
                "dolphinflow",
                mock.Mock(),
                {"NAME": "dolphinflow"},
            )

    def test_rejects_untrusted_staging_name(self):
        with self.assertRaises(RestoreError):
            StagedDatabaseCutover(
                "production_database",
                mock.Mock(),
                {"NAME": "dolphinflow"},
            )

    def test_rejects_maintenance_database_as_live(self):
        with self.assertRaises(RestoreError):
            StagedDatabaseCutover(
                "dolphinflow_restore_12_abcdef123456",
                mock.Mock(),
                {"NAME": "postgres"},
            )

    def test_generates_separate_previous_database_name(self):
        cutover = StagedDatabaseCutover(
            "dolphinflow_restore_12_abcdef123456",
            mock.Mock(),
            {"NAME": "dolphinflow"},
        )
        self.assertNotEqual(cutover.previous_name, cutover.live_name)
        self.assertNotEqual(cutover.previous_name, cutover.staging_name)
        self.assertIn("_previous_", cutover.previous_name)
