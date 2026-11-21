"""Resume a crashed restore orchestrator using its durable service metadata."""
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone

from backup.models import Restore
from backup.restore_journal import RestoreJournal
from backup.restore_lock import RestoreOperationLock
from backup.restore_maintenance import deactivate_maintenance, read_maintenance_state
from backup.restore_quiescence import assert_systemd_services_stopped, close_restore_worker_connection
from backup.restore_services import RestoreError
from backup.staged_restore_recovery import StagedRestoreRecovery
from .cutover_staged_restore import _finalize_restore_audit


class Command(BaseCommand):
    help = "ادامه امن Orchestrator متوقف‌شده؛ بازگشت یا تکمیل Restore و راه‌اندازی سرویس‌ها."

    def add_arguments(self, parser):
        parser.add_argument("--operation-id", required=True)
        parser.add_argument("--health-url", default="")
        parser.add_argument("--health-timeout", type=int, default=15)

    @staticmethod
    def _systemctl(action, unit):
        try:
            result = subprocess.run(
                ["systemctl", action, unit], capture_output=True,
                text=True, check=False, timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RestoreError(f"systemctl {action} برای {unit} ناموفق بود: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "").strip()
            raise RestoreError(f"systemctl {action} برای {unit}: {detail or result.returncode}")

    @staticmethod
    def _active_units(units):
        active = []
        for unit in units:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", unit], capture_output=True,
                    text=True, check=False, timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RestoreError(f"بررسی سرویس {unit} ناموفق بود: {exc}") from exc
            state = (result.stdout or "").strip()
            if result.returncode == 0 and state == "active":
                active.append(unit)
            elif state not in {"inactive", "failed"}:
                raise RestoreError(f"وضعیت سرویس {unit} نامشخص است: {state or 'نامعلوم'}")
        return active

    @staticmethod
    def _health(health_url, timeout):
        call_command("check", verbosity=0)
        connections["default"].close()
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                raise RestoreError("آزمون دیتابیس ناموفق بود.")
        if not Path(settings.MEDIA_ROOT).is_dir():
            raise RestoreError("MEDIA_ROOT در دسترس نیست.")
        if health_url:
            try:
                request = urllib.request.Request(
                    health_url, headers={"User-Agent": "Dolphin-Flow-Restore-Recovery"}
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if not 200 <= response.status < 300:
                        raise RestoreError(f"Health URL با کد {response.status} پاسخ داد.")
            except (OSError, urllib.error.URLError) as exc:
                raise RestoreError(f"Health Check HTTP ناموفق بود: {exc}") from exc

    def handle(self, *args, **options):
        operation_id = options["operation_id"]
        timeout = options["health_timeout"]
        if not 1 <= timeout <= 120:
            raise CommandError("--health-timeout باید بین ۱ تا ۱۲۰ باشد.")

        root = getattr(settings, "RESTORE_JOURNAL_ROOT", Path(settings.BACKUP_ROOT) / ".restore-journal")
        journal = RestoreJournal(operation_id, root=root)
        try:
            payload = journal.read()
            maintenance = read_maintenance_state()
            if maintenance is None or maintenance.get("operation_id") != operation_id:
                raise RestoreError("Maintenance فعال و متعلق به این عملیات نیست.")
            orchestrator = payload.get("restore", {}).get("orchestrator", {})
            units = orchestrator.get("service_units") or []
            previously_active = orchestrator.get("previously_active_units") or []
            if not units or not previously_active or not set(previously_active).issubset(set(units)):
                raise RestoreError("اطلاعات سرویس‌ها در Journal ناقص است؛ Recovery خودکار امن نیست.")

            with RestoreOperationLock(root=root, operation_id=operation_id):
                phase = journal.read()["phase"]
                current = self._active_units(units)
                for unit in reversed(current):
                    self._systemctl("stop", unit)
                assert_systemd_services_stopped(units)
                close_restore_worker_connection()

                if phase in {"QUIESCING", "DATABASE_SWAPPED", "MEDIA_SWAPPED", "VALIDATING", "ROLLBACK_REQUIRED"}:
                    self.stdout.write("Cutover نیمه‌تمام شناسایی شد؛ بازگرداندن نسخه قبلی...")
                    StagedRestoreRecovery(journal).rollback(
                        service_units=units,
                        lock_held=True,
                    )
                    close_restore_worker_connection()
                    call_command("migrate", interactive=False, verbosity=0)
                    Restore.objects.filter(pk=payload["restore_id"]).update(
                        status=Restore.Status.FAILED,
                        error_message="Orchestrator قطع شد؛ نسخه قبلی با موفقیت بازیابی شد.",
                        completed_at=timezone.now(),
                    )
                elif phase == "ROLLED_BACK":
                    call_command("migrate", interactive=False, verbosity=0)
                    Restore.objects.filter(pk=payload["restore_id"]).update(
                        status=Restore.Status.FAILED,
                        error_message="Orchestrator قطع شد؛ نسخه قبلی بازیابی شده است.",
                        completed_at=timezone.now(),
                    )
                elif phase not in {"PREPARED", "COMPLETED"}:
                    raise RestoreError(f"مرحله Journal قابل بازیابی نیست: {phase}")

                self.stdout.write("راه‌اندازی مجدد سرویس‌هایی که پیش از Restore فعال بودند...")
                for unit in previously_active:
                    self._systemctl("start", unit)
                if set(self._active_units(previously_active)) != set(previously_active):
                    raise RestoreError("راه‌اندازی مجدد همه سرویس‌ها تأیید نشد.")
                self._health(options["health_url"], timeout)

                if phase == "COMPLETED":
                    try:
                        _finalize_restore_audit(journal)
                    except Exception as audit_exc:
                        self.stderr.write(self.style.WARNING(
                            "ثبت Audit نیازمند تلاش مجدد است: " + str(audit_exc)
                        ))

                deactivate_maintenance(operation_id)
                self.stdout.write(self.style.SUCCESS(
                    f"Recovery کامل شد؛ مرحله Journal: {journal.read()['phase']}."
                ))
                if phase == "PREPARED":
                    self.stdout.write(
                        "هیچ Cutover انجام نشده بود؛ Restore همچنان آماده اجرای مجدد است."
                    )
                elif phase != "COMPLETED":
                    self.stdout.write("نسخه قبلی فعال شد و درخواست Restore ناموفق ثبت شد.")

        except Exception as exc:
            try:
                payload = journal.read()
                units = payload.get("restore", {}).get("orchestrator", {}).get("service_units", [])
                for unit in reversed(self._active_units(units)):
                    self._systemctl("stop", unit)
            except Exception:
                pass
            raise CommandError(
                "Recovery کامل نشد؛ Maintenance عمداً فعال باقی مانده است. "
                "سرویس‌ها را دستی راه‌اندازی نکنید. " + str(exc)
            ) from exc
