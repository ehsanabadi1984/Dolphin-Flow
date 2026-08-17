from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.test import TransactionTestCase

import asyncio

from config.asgi import application
from workflow.models import Notification
from workflow.notification_services import NotificationService


User = get_user_model()


class NotificationConsumerTests(TransactionTestCase):

    def test_authenticated_user_can_connect(self):
        user = User.objects.create_user(
            username="notification_test",
            password="test-password",
        )

        session = SessionStore()
        session["_auth_user_id"] = str(user.pk)
        session["_auth_user_backend"] = (
            "django.contrib.auth.backends.ModelBackend"
        )
        session["_auth_user_hash"] = (
            user.get_session_auth_hash()
        )
        session.create()

        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=[
                (
                    b"cookie",
                    f"sessionid={session.session_key}".encode(),
                ),
            ],
        )

        connected, _ = async_to_sync(
            communicator.connect
        )()

        self.assertTrue(connected)

        try:
            async_to_sync(
                communicator.disconnect
            )()
        except asyncio.CancelledError:
            pass

    def test_notification_service_delivers_notification_to_websocket(self):

        async def run_test():

            user = await sync_to_async(
                User.objects.create_user
            )(
                username="notification_delivery_test",
                password="test-password",
            )

            session = SessionStore()
            session["_auth_user_id"] = str(user.pk)
            session["_auth_user_backend"] = (
                "django.contrib.auth.backends.ModelBackend"
            )
            session["_auth_user_hash"] = (
                user.get_session_auth_hash()
            )

            await sync_to_async(
                session.create
            )()

            communicator = WebsocketCommunicator(
                application,
                "/ws/notifications/",
                headers=[
                    (
                        b"cookie",
                        f"sessionid={session.session_key}".encode(),
                    ),
                ],
            )

            connected, _ = await communicator.connect()

            self.assertTrue(connected)

            notification = await sync_to_async(
                NotificationService.create
            )(
                recipient=user,
                notification_type=(
                    Notification.NotificationType.ACTION_REQUIRED
                ),
                title="تست اعلان",
                message="این یک اعلان آزمایشی است.",
            )

            payload = await communicator.receive_json_from()

            self.assertEqual(
                payload["id"],
                notification.id,
            )

            self.assertEqual(
                payload["title"],
                "تست اعلان",
            )

            self.assertEqual(
                payload["message"],
                "این یک اعلان آزمایشی است.",
            )

            self.assertEqual(
                payload["type"],
                Notification.NotificationType.ACTION_REQUIRED,
            )

            self.assertIsNone(
                payload["workflow_instance_id"]
            )

            try:
                await communicator.disconnect()
            except asyncio.CancelledError:
                pass

        async_to_sync(run_test)()