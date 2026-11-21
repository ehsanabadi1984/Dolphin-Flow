from types import SimpleNamespace
from unittest import TestCase, mock

from backup.restore_quiescence import (
    assert_database_quiescent,
    assert_systemd_services_stopped,
)
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


    def test_all_required_systemd_services_must_be_explicitly_listed(self):
        with self.assertRaisesRegex(RestoreError, "مشخص نشده"):
            assert_systemd_services_stopped([])

    def test_inactive_systemd_services_pass(self):
        runner = mock.Mock(return_value=SimpleNamespace(
            returncode=3, stdout="inactive\\n"
        ))
        result = assert_systemd_services_stopped(
            ["dolphinplus-daphne.service", "dolphinplus-celery.service"],
            runner=runner,
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["state"], "inactive")
        self.assertEqual(runner.call_count, 2)

    def test_active_systemd_service_blocks_quiescence(self):
        runner = mock.Mock(return_value=SimpleNamespace(
            returncode=0, stdout="active\\n"
        ))
        with self.assertRaisesRegex(RestoreError, "هنوز متوقف"):
            assert_systemd_services_stopped(
                ["dolphinplus-celery.service"], runner=runner
            )

    def test_unknown_systemd_service_state_blocks_quiescence(self):
        runner = mock.Mock(return_value=SimpleNamespace(
            returncode=4, stdout="unknown\\n"
        ))
        with self.assertRaises(RestoreError):
            assert_systemd_services_stopped(
                ["missing.service"], runner=runner
            )

    def test_systemctl_missing_blocks_quiescence(self):
        runner = mock.Mock(side_effect=FileNotFoundError)
        with self.assertRaisesRegex(RestoreError, "systemctl"):
            assert_systemd_services_stopped(
                ["dolphinplus-celery.service"], runner=runner
            )
