"""Safety gate for PostgreSQL restore cutover.

The application services must be stopped by the deployment/orchestration layer
before this check. This module only closes this worker's default connection and
verifies that no other client sessions remain on the live database.
"""

import secrets
from copy import deepcopy

from django.conf import settings
from django.db import connections
from django.db.backends.postgresql.base import DatabaseWrapper

from .restore_services import RestoreError


MAINTENANCE_DATABASE = "postgres"


def close_restore_worker_connection():
    """Release this Celery worker's default DB session before cutover checks."""
    connections["default"].close()


def assert_database_quiescent(database_settings=None):
    """Require zero other client sessions on the configured live database.

    This is a gate, not a process supervisor: Daphne, Celery workers, beat and
    any external clients must already be stopped/prevented from reconnecting.
    """
    config = deepcopy(database_settings or settings.DATABASES["default"])
    database_name = config.get("NAME")
    if not isinstance(database_name, str) or not database_name.strip():
        raise RestoreError("نام دیتابیس اصلی برای بررسی توقف اتصال‌ها معتبر نیست.")
    if database_name == MAINTENANCE_DATABASE:
        raise RestoreError("اتصال مدیریتی PostgreSQL نمی‌تواند دیتابیس اصلی باشد.")

    admin_config = deepcopy(config)
    admin_config["NAME"] = MAINTENANCE_DATABASE
    admin_config["OPTIONS"] = admin_config.get("OPTIONS") or {}
    admin = DatabaseWrapper(
        admin_config,
        alias=f"restore_quiescence_{secrets.token_hex(6)}",
    )
    try:
        admin.ensure_connection()
        admin.set_autocommit(True)
        with admin.cursor() as cursor:
            cursor.execute(
                """
                SELECT pid
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                  AND backend_type = 'client backend'
                ORDER BY pid
                """,
                [database_name],
            )
            sessions = cursor.fetchall()

        if sessions:
            raise RestoreError(
                "تعویض دیتابیس متوقف شد؛ هنوز "
                f"{len(sessions)} اتصال به دیتابیس اصلی وجود دارد. "
                "سرویس‌های برنامه و Workerها باید کاملاً متوقف شوند."
            )

        return {"database": database_name, "active_sessions": 0}
    except RestoreError:
        raise
    except Exception as exc:
        raise RestoreError(
            "بررسی اتصال‌های دیتابیس پیش از Restore ناموفق بود: " + str(exc)
        ) from exc
    finally:
        admin.close()
