from unittest import TestCase, mock

from backup.restore_quiescence import assert_database_quiescent
from backup.restore_services import RestoreError


class RestoreQuiescenceTests(TestCase):
    @mock.patch("backup.restore_quiescence.DatabaseWrapper")
    def test_quiescent_database_passes(self, wrapper_class):
        admin = wrapper_class.return_value
        cursor = mock.MagicMock()
        cursor.fetchall.return_value = []
        admin.cursor.return_value.__enter__.return_value = cursor

        result = assert_database_quiescent(
            {"NAME": "dolphinflow", "HOST": "localhost"}
        )

        self.assertEqual(
            result,
            {"database": "dolphinflow", "active_sessions": 0},
        )
        cursor.execute.assert_called_once()
        admin.close.assert_called_once()

    @mock.patch("backup.restore_quiescence.DatabaseWrapper")
    def test_active_sessions_block_cutover(self, wrapper_class):
        admin = wrapper_class.return_value
        cursor = mock.MagicMock()
        cursor.fetchall.return_value = [(123,), (456,)]
        admin.cursor.return_value.__enter__.return_value = cursor

        with self.assertRaisesRegex(RestoreError, "۲ اتصال|2 اتصال"):
            assert_database_quiescent({"NAME": "dolphinflow"})

        admin.close.assert_called_once()

    def test_maintenance_database_is_rejected(self):
        with self.assertRaises(RestoreError):
            assert_database_quiescent({"NAME": "postgres"})

    def test_missing_database_name_is_rejected(self):
        with self.assertRaises(RestoreError):
            assert_database_quiescent({"NAME": ""})
