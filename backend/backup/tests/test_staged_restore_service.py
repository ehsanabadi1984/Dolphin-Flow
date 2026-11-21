from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import SimpleTestCase, override_settings

from backup.restore_services import RestoreError
from backup.staged_restore import StagedDatabaseRestore


class StagedDatabaseRestoreTests(SimpleTestCase):
    def setUp(self):
        self.database_settings = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "dolphinflow",
            "USER": "dolphin",
            "PASSWORD": "secret-value",
            "HOST": "127.0.0.1",
            "PORT": "5432",
            "OPTIONS": {},
        }

    def test_database_name_is_unique_and_postgresql_safe(self):
        first = StagedDatabaseRestore(12, self.database_settings)
        second = StagedDatabaseRestore(12, self.database_settings)

        self.assertNotEqual(first.database_name, second.database_name)
        self.assertTrue(first.database_name.startswith("dolphinflow_restore_"))
        self.assertLessEqual(len(first.database_name.encode("utf-8")), 63)

    @override_settings(PG_RESTORE_PATH="/usr/bin/pg_restore")
    @mock.patch("backup.staged_restore.subprocess.run")
    def test_restore_dump_targets_staging_database_without_clean_flags(
        self, mocked_run
    ):
        mocked_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        service = StagedDatabaseRestore(12, self.database_settings)

        with TemporaryDirectory() as temp_dir:
            dump_path = Path(temp_dir) / "database.dump"
            dump_path.write_bytes(b"dump")
            service.restore_dump(dump_path)

        command = mocked_run.call_args.args[0]
        self.assertIn("--dbname", command)
        self.assertIn(service.database_name, command)
        self.assertNotIn("--clean", command)
        self.assertNotIn("--if-exists", command)
        self.assertNotIn("--password", command)
        self.assertEqual(
            mocked_run.call_args.kwargs["env"]["PGPASSWORD"],
            "secret-value",
        )

    @mock.patch("backup.staged_restore.DatabaseWrapper")
    def test_create_database_uses_maintenance_connection(self, wrapper_class):
        admin = wrapper_class.return_value
        admin.ops.quote_name.side_effect = lambda value: f'"{value}"'
        cursor = mock.MagicMock()
        admin.cursor.return_value.__enter__.return_value = cursor
        service = StagedDatabaseRestore(12, self.database_settings)

        service.create_database()

        admin.ensure_connection.assert_called_once_with()
        admin.set_autocommit.assert_called_once_with(True)
        cursor.execute.assert_called_once_with(
            f'CREATE DATABASE "{service.database_name}"'
        )
        self.assertTrue(service._created)
        admin.close.assert_called_once_with()

    @mock.patch("backup.staged_restore.MigrationLoader")
    @mock.patch("backup.staged_restore.MigrationExecutor")
    def test_migrations_run_on_staging_connection(
        self, executor_class, loader_class
    ):
        stage_connection = object()
        service = StagedDatabaseRestore(12, self.database_settings)
        service._staging_connection = mock.Mock(return_value=stage_connection)
        executor = executor_class.return_value
        executor.loader.graph.leaf_nodes.return_value = [("accounts", "0001_initial")]

        loader_class.return_value.detect_conflicts.return_value = {}\n\n        service.apply_migrations()

        executor_class.assert_called_once_with(stage_connection)
        executor.migrate.assert_called_once_with(
            targets=[("accounts", "0001_initial")]
        )
        loader_class.assert_called_once_with(stage_connection)
        loader_class.return_value.check_consistent_history.assert_called_once_with(
            stage_connection
        )
        loader_class.return_value.detect_conflicts.return_value = {}

    def test_prepare_cleans_up_staging_database_when_restore_fails(self):
        service = StagedDatabaseRestore(12, self.database_settings)
        service.create_database = mock.Mock()
        service.restore_dump = mock.Mock(
            side_effect=RestoreError("restore failed")
        )
        service.close = mock.Mock()
        service.drop_database = mock.Mock()

        with self.assertRaises(RestoreError):
            service.prepare("/tmp/database.dump")

        service.create_database.assert_called_once_with()
        service.close.assert_called_once_with()
        service.drop_database.assert_called_once_with()
