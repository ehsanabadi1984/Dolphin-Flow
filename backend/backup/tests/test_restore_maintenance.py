import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from celery import Celery
from celery.exceptions import Ignore
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from backup.restore_maintenance import (
    RestoreMaintenanceASGIMiddleware,
    RestoreMaintenanceError,
    activate_maintenance,
    deactivate_maintenance,
    maintenance_marker_path,
    maintenance_is_active,
    read_maintenance_state,
)
from backup.restore_maintenance_middleware import RestoreMaintenanceMiddleware
from backup.restore_maintenance_tasks import RestoreMaintenanceAwareTask
from backup.restore_drain import RestoreDrainLock, acquire_application_work_lease


class RestoreMaintenanceGateTests(SimpleTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings_override = override_settings(
            BACKUP_ROOT=Path(self.temp_dir.name) / "backups"
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def test_gate_is_persistent_and_requires_matching_owner_to_clear(self):
        operation_id = "a" * 32
        self.assertFalse(maintenance_is_active())

        self.assertEqual(activate_maintenance(operation_id), operation_id)
        self.assertTrue(maintenance_is_active())
        self.assertEqual(read_maintenance_state()["operation_id"], operation_id)

        with self.assertRaises(RestoreMaintenanceError):
            activate_maintenance("b" * 32)
        with self.assertRaises(RestoreMaintenanceError):
            deactivate_maintenance("b" * 32)

        self.assertTrue(deactivate_maintenance(operation_id))
        self.assertFalse(maintenance_is_active())

    def test_marker_rejects_invalid_operation_id(self):
        with self.assertRaises(RestoreMaintenanceError):
            activate_maintenance("../unsafe")

    def test_marker_rejects_symlink(self):
        marker = maintenance_marker_path()
        marker.parent.mkdir(parents=True)
        target = marker.parent / "target"
        target.write_text('{"operation_id":"' + ("a" * 32) + '"}')
        marker.symlink_to(target)

        with self.assertRaises(RestoreMaintenanceError):
            maintenance_is_active()

    def test_http_requests_are_rejected_while_gate_is_active(self):
        activate_maintenance("c" * 32)
        middleware = RestoreMaintenanceMiddleware(
            lambda request: HttpResponse("application")
        )
        response = middleware(RequestFactory().get("/"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "60")

    def test_http_requests_continue_without_gate(self):
        middleware = RestoreMaintenanceMiddleware(
            lambda request: HttpResponse("application")
        )
        response = middleware(RequestFactory().get("/"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"application")

    def test_websocket_handshake_is_closed_while_gate_is_active(self):
        activate_maintenance("d" * 32)
        app = Mock()
        middleware = RestoreMaintenanceASGIMiddleware(app)
        sent = []

        async def receive():
            return {"type": "websocket.connect"}

        async def send(message):
            sent.append(message)

        asyncio.run(
            middleware(
                {"type": "websocket", "path": "/ws/"},
                receive,
                send,
            )
        )

        self.assertEqual(sent, [{"type": "websocket.close", "code": 1013}])
        app.assert_not_called()

    def test_websocket_holds_drain_lease_for_connection_lifetime(self):
        async def app(scope, receive, send):
            with self.assertRaises(RestoreMaintenanceError):
                RestoreDrainLock.acquire(exclusive=True, timeout=0)

        middleware = RestoreMaintenanceASGIMiddleware(app)

        async def run():
            await middleware(
                {"type": "websocket", "path": "/ws/"},
                Mock(),
                Mock(),
            )

        asyncio.run(run())
        with RestoreDrainLock.acquire(exclusive=True, timeout=0):
            self.assertTrue(True)

    def test_websocket_passes_through_without_gate(self):
        app = AsyncMock()
        middleware = RestoreMaintenanceASGIMiddleware(app)

        async def run():
            await middleware(
                {"type": "websocket", "path": "/ws/"},
                Mock(),
                Mock(),
            )

        asyncio.run(run())
        app.assert_called_once()

    def test_exclusive_drain_waits_for_inflight_shared_work(self):
        shared = acquire_application_work_lease()
        try:
            with self.assertRaises(RestoreMaintenanceError):
                RestoreDrainLock.acquire(exclusive=True, timeout=0)
        finally:
            shared.release()

        with RestoreDrainLock.acquire(exclusive=True, timeout=0):
            with self.assertRaises(RestoreMaintenanceError):
                acquire_application_work_lease(timeout=0)

    def test_http_request_holds_lease_until_response_is_built(self):
        def application(_request):
            with self.assertRaises(RestoreMaintenanceError):
                RestoreDrainLock.acquire(exclusive=True, timeout=0)
            return HttpResponse("application")

        middleware = RestoreMaintenanceMiddleware(application)
        response = middleware(RequestFactory().get("/"))
        self.assertEqual(response.status_code, 200)

        with RestoreDrainLock.acquire(exclusive=True, timeout=0):
            self.assertTrue(True)

    def test_streaming_http_response_holds_lease_until_closed(self):
        from django.http import StreamingHttpResponse

        middleware = RestoreMaintenanceMiddleware(
            lambda _request: StreamingHttpResponse(iter([b"chunk"]))
        )
        response = middleware(RequestFactory().get("/"))

        with self.assertRaises(RestoreMaintenanceError):
            RestoreDrainLock.acquire(exclusive=True, timeout=0)

        response.close()
        with RestoreDrainLock.acquire(exclusive=True, timeout=0):
            self.assertTrue(True)

    def test_new_celery_tasks_are_ignored_during_maintenance(self):
        activate_maintenance("e" * 32)
        task = RestoreMaintenanceAwareTask()
        task.run = Mock(return_value="ran")

        with self.assertRaises(Ignore):
            task()

        task.run.assert_not_called()

    def test_worker_task_hook_ignores_tasks_during_maintenance(self):
        activate_maintenance("f" * 32)
        task = RestoreMaintenanceAwareTask()
        task.run = Mock(return_value="ran")

        with self.assertRaises(Ignore):
            task.before_start("task-id", (), {})

        task.run.assert_not_called()

    def test_celery_tasks_run_without_gate(self):
        task = RestoreMaintenanceAwareTask()
        task.bind(Celery("restore-maintenance-tests"))
        task.run = Mock(return_value="ran")

        self.assertEqual(task(), "ran")
        task.run.assert_called_once()
