import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings

from backup.restore_services import RestoreError
from backup.restore_lock import RestoreOperationLock


class RestoreOperationLockTests(SimpleTestCase):
    def test_only_one_instance_can_hold_the_lock(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            first = RestoreOperationLock(root=root, operation_id="first", restore_id=1)
            second = RestoreOperationLock(root=root, operation_id="second", restore_id=2)

            first.acquire()
            try:
                self.assertTrue(first.acquired)
                with self.assertRaises(RestoreError):
                    second.acquire()
                self.assertFalse(second.acquired)
            finally:
                first.release()

            second.acquire()
            self.assertTrue(second.acquired)
            second.release()

    def test_lock_metadata_is_written_with_restricted_permissions(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            lock = RestoreOperationLock(
                root=root, operation_id="operation-123", restore_id=123
            )

            with lock:
                metadata = json.loads(lock.path.read_text(encoding="utf-8"))
                self.assertEqual(metadata["operation_id"], "operation-123")
                self.assertEqual(metadata["restore_id"], 123)
                self.assertEqual(metadata["pid"], os.getpid())
                self.assertEqual(os.stat(lock.path).st_mode & 0o777, 0o600)
                self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)

            self.assertFalse(lock.acquired)

    def test_context_manager_releases_lock_after_exception(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            first = RestoreOperationLock(root=root)
            second = RestoreOperationLock(root=root)

            with self.assertRaises(RuntimeError):
                with first:
                    raise RuntimeError("simulated worker failure")

            with second:
                self.assertTrue(second.acquired)

    def test_lock_location_inside_media_root_is_rejected(self):
        with TemporaryDirectory() as temp:
            media_root = Path(temp) / "media"
            with override_settings(MEDIA_ROOT=media_root):
                with self.assertRaises(RestoreError):
                    RestoreOperationLock(root=media_root / ".journal")
    
    def test_lock_is_released_when_metadata_write_fails(self):
        from unittest.mock import patch

        with TemporaryDirectory() as temp:
            root = Path(temp) / "journal"
            first = RestoreOperationLock(root=root)
            second = RestoreOperationLock(root=root)

            with patch("backup.restore_lock.os.write", side_effect=OSError("disk error")):
                with self.assertRaises(RestoreError):
                    first.acquire()

            with second:
                self.assertTrue(second.acquired)
