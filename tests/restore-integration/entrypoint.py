#!/usr/bin/python3
import os

ENV_KEYS = (
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "REDIS_HOST",
    "REDIS_PORT",
    "DJANGO_DEBUG",
    "DJANGO_ALLOWED_HOSTS",
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "DJANGO_SECRET_KEY",
    "BACKUP_ROOT",
    "MEDIA_ROOT",
    "PG_DUMP_PATH",
    "PG_RESTORE_PATH",
    "MAGFA_DOMAIN",
    "MAGFA_USERNAME",
    "MAGFA_PASSWORD",
    "MAGFA_SENDER",
    "SMS_CREDENTIALS_ENCRYPTION_KEY",
    "RESTORE_SERVICE_UNITS",
)

def systemd_quote(value):
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    return f'"{value}"'

os.umask(0o077)
env_file = "/run/restore-test.env"

with open(env_file, "w", encoding="utf-8") as output:
    for key in ENV_KEYS:
        if key in os.environ:
            output.write(f"{key}={systemd_quote(os.environ[key])}\n")

os.chmod(env_file, 0o600)
os.execv("/sbin/init", ["/sbin/init"])
