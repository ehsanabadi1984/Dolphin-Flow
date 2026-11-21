"""Isolated PostgreSQL staging database preparation for safe restores.

This module deliberately does not switch the application's default database.
It creates a uniquely named empty database, restores the archive there without
DROP/--clean flags, applies Django migrations through an independent connection,
and validates the result. Cutover and media replacement are handled separately.
"""

import logging
import os
import re
import secrets
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader

from .restore_services import (
    POST_RESTORE_REQUIRED_TABLES,
    RestoreError,
)
from .services import sanitize_message

logger = logging.getLogger(__name__)

STAGING_DATABASE_PREFIX = "dolphinflow_restore_"
MAINTENANCE_DATABASE = "postgres"


class StagedDatabaseRestore:
    """Prepare and validate a restored database without touching default DB."""

    def __init__(self, restore_id, database_settings=None):
        self.restore_id = int(restore_id)
        self.database_settings = deepcopy(
            database_settings or settings.DATABASES["default"]
        )
        self.database_name = self._make_database_name()
        self.alias = f"restore_stage_{secrets.token_hex(6)}"
        self._connection = None
        self._created = False

    def _make_database_name(self):
        # PostgreSQL identifiers are limited to 63 bytes. The suffix is
        # generated locally and contains only safe identifier characters.
        suffix = f"{self.restore_id}_{secrets.token_hex(6)}"
        name = f"{STAGING_DATABASE_PREFIX}{suffix}"
        if len(name.encode("utf-8")) > 63 or not re.fullmatch(r"[a-zA-Z0-9_]+", name):
            raise RestoreError("نام دیتابیس موقت معتبر نیست.")
        return name

    @staticmethod
    def _admin_connection_config(database_settings):
        config = deepcopy(database_settings)
        config["NAME"] = MAINTENANCE_DATABASE
        config["OPTIONS"] = config.get("OPTIONS") or {}
        return config

    def _open_admin_connection(self):
        config = self._admin_connection_config(self.database_settings)
        admin = DatabaseWrapper(config, alias=f"restore_admin_{secrets.token_hex(6)}")
        admin.ensure_connection()
        admin.set_autocommit(True)
        return admin

    def create_database(self):
        """Create an empty staging database using a maintenance connection."""
        admin = self._open_admin_connection()
        try:
            quoted_name = admin.ops.quote_name(self.database_name)
            with admin.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE {quoted_name}")
            self._created = True
        except Exception as exc:
            raise RestoreError(
                "ساخت دیتابیس موقت برای بازیابی ناموفق بود: "
                + sanitize_message(str(exc))
            ) from exc
        finally:
            admin.close()

    def _staging_connection(self):
        if self._connection is not None:
            return self._connection
        config = deepcopy(self.database_settings)
        config["NAME"] = self.database_name
        # Never inherit a connection-level test database name.
        config.pop("TEST", None)
        connections.databases[self.alias] = config
        self._connection = connections[self.alias]
        return self._connection

    def _pg_restore_binary(self):
        configured = getattr(settings, "PG_RESTORE_PATH", "pg_restore")
        if configured != "pg_restore":
            return configured
        return shutil.which("pg_restore") or "pg_restore"

    def restore_dump(self, dump_path):
        """Restore into the empty staging DB; intentionally no --clean flags."""
        database = self.database_settings
        command = [
            self._pg_restore_binary(),
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
        ]
        if database.get("HOST"):
            command += ["--host", database["HOST"]]
        if database.get("PORT"):
            command += ["--port", str(database["PORT"])]
        if database.get("USER"):
            command += ["--username", database["USER"]]
        command += ["--dbname", self.database_name, str(Path(dump_path))]

        env = os.environ.copy()
        if database.get("PASSWORD"):
            env["PGPASSWORD"] = database["PASSWORD"]
        try:
            result = subprocess.run(
                command, env=env, capture_output=True, text=True, check=False
            )
        except OSError as exc:
            raise RestoreError(
                "اجرای pg_restore روی دیتابیس موقت ممکن نیست: "
                + sanitize_message(str(exc))
            ) from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "").strip()
            raise RestoreError(
                "بازیابی در دیتابیس موقت ناموفق بود: "
                + sanitize_message(detail)
            )

    def apply_migrations(self):
        """Run current project's migrations only against the staging alias."""
        stage_connection = self._staging_connection()
        try:
            executor = MigrationExecutor(stage_connection)
            executor.migrate(targets=executor.loader.graph.leaf_nodes())
            # Recreate the executor after migration so its loader reflects the
            # final database state and validate migration history.
            loader = MigrationLoader(stage_connection)
            loader.check_consistent_history(stage_connection)
            if loader.detect_conflicts():
                raise RestoreError(
                    "در Migrationهای پروژه تعارض وجود دارد؛ دیتابیس موقت معتبر نیست."
                )
        except RestoreError:
            raise
        except Exception as exc:
            raise RestoreError(
                "اجرای Migrationها روی دیتابیس موقت ناموفق بود: "
                + sanitize_message(str(exc))
            ) from exc

    def validate(self):
        """Check essential tables and migration metadata in staging DB."""
        stage_connection = self._staging_connection()
        try:
            with stage_connection.cursor() as cursor:
                for table in POST_RESTORE_REQUIRED_TABLES:
                    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [table])
                    if not cursor.fetchone()[0]:
                        raise RestoreError(
                            f"دیتابیس موقت فاقد جدول ضروری «{table}» است."
                        )
                cursor.execute("SELECT count(*) FROM django_migrations")
                if not cursor.fetchone()[0]:
                    raise RestoreError(
                        "سوابق Migration در دیتابیس موقت خالی است."
                    )
        except RestoreError:
            raise
        except Exception as exc:
            raise RestoreError(
                "اعتبارسنجی دیتابیس موقت ناموفق بود: "
                + sanitize_message(str(exc))
            ) from exc

    def prepare(self, dump_path):
        """Create, restore, migrate, and validate the staging database."""
        self.create_database()
        try:
            self.restore_dump(dump_path)
            self.apply_migrations()
            self.validate()
        except Exception:
            self.close()
            try:
                self.drop_database()
            except Exception:
                logger.exception(
                    "Staging database cleanup failed after preparation error: %s",
                    self.database_name,
                )
            raise
        return self.database_name

    def close(self):
        """Close only this service's staging connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self.alias in connections:
            del connections[self.alias]

    def drop_database(self):
        """Drop this service's own staging DB; never targets default DB."""
        if not self._created:
            return
        self.close()
        admin = self._open_admin_connection()
        try:
            quoted_name = admin.ops.quote_name(self.database_name)
            with admin.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS {quoted_name} WITH (FORCE)")
            self._created = False
        except Exception as exc:
            logger.exception("Could not drop staging database %s", self.database_name)
            raise RestoreError(
                "حذف دیتابیس موقت ناموفق بود: " + sanitize_message(str(exc))
            ) from exc
        finally:
            admin.close()
