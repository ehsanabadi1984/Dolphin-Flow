"""Activate the persistent request/task gate before stopping application services."""

from django.core.management.base import BaseCommand, CommandError

from backup.restore_maintenance import (
    RestoreMaintenanceError,
    activate_maintenance,
)


class Command(BaseCommand):
    help = "فعال‌کردن قفل پایدار Maintenance برای آماده‌سازی Restore."

    def add_arguments(self, parser):
        parser.add_argument("--operation-id", dest="operation_id")

    def handle(self, *args, **options):
        try:
            operation_id = activate_maintenance(options.get("operation_id"))
        except RestoreMaintenanceError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            "Maintenance فعال شد. درخواست‌های جدید HTTP، WebSocket و وظایف جدید Celery مسدود می‌شوند."
        ))
        self.stdout.write(f"Operation ID: {operation_id}")
        self.stdout.write(
            "اکنون سرویس‌های وب، همه Workerها و Beat را به‌صورت graceful متوقف کنید؛ "
            "سپس فرمان verify_restore_quiescence را اجرا کنید."
        )
