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


import secrets
import tempfile
from pathlib import Path

from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.db.backends.postgresql.base import DatabaseWrapper

from backup.restore_journal import RestoreJournal


@skipUnlessDBFeature("supports_transactions")
class StagedDatabaseCutoverPostgreSQLTests(TransactionTestCase):
    databases = {"default"}
    """Exercise real PostgreSQL renames using disposable databases only."""

    def setUp(self):
        super().setUp()
        self.config = dict(connections["default"].settings_dict)
        self.config.pop("TEST", None)
        self.live_name = f"cutover_live_{secrets.token_hex(5)}"
        self.staging_name = f"dolphinflow_restore_1_{secrets.token_hex(5)}"
        # Django's test runner rewrites NAME to test_<database>; this test
        # creates its own disposable live DB and must point the cutover there.
        self.config["NAME"] = self.live_name
        self.previous_name = None
        self.admin = self._admin_connection()
        with self.admin.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {self.admin.ops.quote_name(self.live_name)}")
            cursor.execute(
                f"CREATE DATABASE {self.admin.ops.quote_name(self.staging_name)}"
            )
        self._seed(self.live_name, "original")
        self._seed(self.staging_name, "restored")
        self.journal_dir = tempfile.TemporaryDirectory()
        self.journal = RestoreJournal.new(
            1,
            root=Path(self.journal_dir.name),
            database={
                "live_name": self.live_name,
                "staging_name": self.staging_name,
                "prepared": True,
            },
        )

    def tearDown(self):
        try:
            names = {self.live_name, self.staging_name}
            if self.previous_name:
                names.add(self.previous_name)
            with self.admin.cursor() as cursor:
                for name in names:
                    cursor.execute(
                        f"DROP DATABASE IF EXISTS {self.admin.ops.quote_name(name)} WITH (FORCE)"
                    )
        finally:
            self.admin.close()
            if hasattr(self, "journal_dir"):
                self.journal_dir.cleanup()
            super().tearDown()

    def _admin_connection(self):
        config = dict(self.config)
        config["NAME"] = "postgres"
        config["OPTIONS"] = config.get("OPTIONS") or {}
        connection = DatabaseWrapper(
            config, alias=f"cutover_test_admin_{secrets.token_hex(4)}"
        )
        connection.ensure_connection()
        connection.set_autocommit(True)
        return connection

    def _seed(self, database_name, marker):
        config = dict(self.config)
        config["NAME"] = database_name
        connection = DatabaseWrapper(
            config, alias=f"cutover_test_seed_{secrets.token_hex(4)}"
        )
        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE cutover_probe (marker text NOT NULL)")
                cursor.execute(
                    "INSERT INTO cutover_probe (marker) VALUES (%s)", [marker]
                )
        finally:
            connection.close()

    def _read_marker(self, database_name):
        config = dict(self.config)
        config["NAME"] = database_name
        connection = DatabaseWrapper(
            config, alias=f"cutover_test_read_{secrets.token_hex(4)}"
        )
        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT marker FROM cutover_probe")
                return cursor.fetchone()[0]
        finally:
            connection.close()

    def test_swap_and_rollback_preserve_both_database_contents(self):
        from backup.staged_database_cutover import StagedDatabaseCutover

        cutover = StagedDatabaseCutover(
            self.staging_name, self.journal, self.config
        )
        self.previous_name = cutover.previous_name

        result = cutover.swap()

        self.assertEqual(result["live_database"], self.live_name)
        self.assertEqual(self._read_marker(self.live_name), "restored")
        self.assertEqual(self._read_marker(self.previous_name), "original")
        self.assertEqual(self.journal.read()["phase"], "DATABASE_SWAPPED")

        cutover.rollback()

        self.assertEqual(self._read_marker(self.live_name), "original")
        self.assertEqual(self._read_marker(self.staging_name), "restored")
        self.assertEqual(self.journal.read()["phase"], "ROLLED_BACK")
