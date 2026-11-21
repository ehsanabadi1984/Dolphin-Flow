"""Independent end-to-end orchestrator for a prepared staged restore."""
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone

from backup.models import Restore
from backup.restore_journal import RestoreJournal
from backup.restore_lock import RestoreOperationLock
from backup.restore_maintenance import activate_maintenance, deactivate_maintenance, read_maintenance_state
from backup.restore_recovery import inspect_restore_journals
from backup.restore_quiescence import assert_database_quiescent, assert_systemd_services_stopped, close_restore_worker_connection
from backup.restore_services import RestoreError
from backup.staged_restore_cutover import StagedRestoreCutover
from backup.staged_restore_recovery import StagedRestoreRecovery
from backup.staged_restore_preparation import StagedRestorePreparationService
from .cutover_staged_restore import _finalize_restore_audit


class Command(BaseCommand):
    help = "اجرای کامل و خودکار Restore آماده‌شده با Rollback در صورت شکست."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--restore-id", type=int)
        target.add_argument("--operation-id")
        parser.add_argument("--service-unit", action="append", dest="service_units", required=True)

    @staticmethod
    def _run_systemctl(action, unit):
        try:
            result = subprocess.run(
                ["systemctl", action, unit], capture_output=True, text=True,
                check=False, timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RestoreError(f"systemctl {action} برای {unit} ناموفق بود: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "").strip()
            raise RestoreError(f"systemctl {action} برای {unit}: {detail or result.returncode}")
        return result

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

    @classmethod
    def _stop(cls, units):
        for unit in reversed(units):
            cls._run_systemctl("stop", unit)

    @classmethod
    def _start(cls, units):
        for unit in units:
            cls._run_systemctl("start", unit)

    @staticmethod
    def _health_check():
        call_command("check", verbosity=0)
        connections["default"].close()
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                raise RestoreError("آزمون دیتابیس ناموفق بود.")
        if not Path(settings.MEDIA_ROOT).is_dir():
            raise RestoreError("MEDIA_ROOT در دسترس نیست.")

    def handle(self, *args, **options):
        operation_id = options["operation_id"]
        if options["restore_id"] is not None:
            try:
                restore = Restore.objects.get(pk=options["restore_id"])
            except Restore.DoesNotExist as exc:
                raise CommandError("درخواست Restore پیدا نشد.") from exc
            if restore.status == Restore.Status.PREPARED:
                prepared_journals = [
                    item for item in inspect_restore_journals()
                    if item.get("restore_id") == restore.pk
                    and item.get("phase") == "PREPARED"
                    and item.get("status") == "PREPARED"
                ]
                if len(prepared_journals) != 1:
                    raise CommandError(
                        "برای این Restore دقیقاً یک Journal آماده و معتبر پیدا نشد."
                    )
                operation_id = prepared_journals[0]["operation_id"]
                self.stdout.write(
                    f"Restore #{restore.pk} از قبل آماده است؛ Cutover آغاز می‌شود."
                )
            else:
                prepared = StagedRestorePreparationService(restore).run()
                if prepared.get("status") != "PREPARED" or not prepared.get("operation_id"):
                    raise CommandError(
                        "آماده‌سازی Restore انجام نشد یا در حال اجراست: "
                        + str(prepared.get("status", "نامشخص"))
                    )
                operation_id = prepared["operation_id"]
                self.stdout.write(self.style.SUCCESS(
                    f"آماده‌سازی Restore #{restore.pk} کامل شد؛ اجرای Cutover آغاز می‌شود."
                ))
        units = options["service_units"]
        if len(set(units)) != len(units):
            raise CommandError("نام سرویس systemd تکراری است.")
        if any(not unit or unit.startswith("-") or any(ch.isspace() for ch in unit) for unit in units):
            raise CommandError("نام یکی از واحدهای systemd نامعتبر است.")

        root = getattr(settings, "RESTORE_JOURNAL_ROOT", Path(settings.BACKUP_ROOT) / ".restore-journal")
        journal = RestoreJournal(operation_id, root=root)
        maintenance_owned = False
        active_units = []
        database_state = None

        try:
            with RestoreOperationLock(root=root, operation_id=operation_id):
                payload = journal.read()
                if payload["phase"] != "PREPARED":
                    raise RestoreError(f"Journal باید PREPARED باشد؛ وضعیت فعلی: {payload['phase']}")
                if not payload["database"].get("prepared"):
                    raise RestoreError("دیتابیس staging آماده نیست.")
                if payload["media"].get("included") and not payload["media"].get("prepared"):
                    raise RestoreError("Media staging آماده نیست.")
                if read_maintenance_state() is not None:
                    raise RestoreError("Maintenance از قبل فعال است؛ مالکیت آن متعلق به این عملیات نیست.")

                active_units = self._active_units(units)
                if not active_units:
                    raise RestoreError("هیچ سرویس برنامه‌ای فعال نیست؛ توقف کامل قابل اثبات نیست.")
                journal.update(restore={
                    "orchestrator": {
                        "service_units": list(units),
                        "previously_active_units": list(active_units),
                    }
                })
                activate_maintenance(operation_id)
                maintenance_owned = True

                self.stdout.write("۱/۶ توقف Daphne، Celery و سرویس‌های اعلام‌شده...")
                self._stop(active_units)
                assert_systemd_services_stopped(units)
                close_restore_worker_connection()
                database_state = assert_database_quiescent()

                self.stdout.write("۲/۶ Cutover هماهنگ دیتابیس و Media...")
                result = StagedRestoreCutover(journal, defer_completion=True).run()
                if result.get("status") != "VALIDATING":
                    raise RestoreError("Cutover کامل نشد.")

                self.stdout.write("۳/۶ اجرای Migration...")
                close_restore_worker_connection()
                call_command("migrate", interactive=False, verbosity=1)

                self.stdout.write("۴/۶ بررسی دیتابیس و Media...")
                self._health_check()

                self.stdout.write("۵/۶ راه‌اندازی سرویس‌ها...")
                self._start(active_units)
                if set(self._active_units(active_units)) != set(active_units):
                    raise RestoreError("همه سرویس‌ها فعال نشدند.")

                self.stdout.write("۶/۶ Health Check نهایی و پایان Maintenance...")
                self._health_check()
                journal.update(phase="COMPLETED")
                try:
                    _finalize_restore_audit(journal)
                except Exception as audit_exc:
                    self.stderr.write(self.style.WARNING(
                        "Restore سالم است، اما ثبت ردیف Audit نیازمند تلاش مجدد است: "
                        + str(audit_exc)
                    ))
                deactivate_maintenance(operation_id)
                maintenance_owned = False

                self.stdout.write(self.style.SUCCESS(
                    f"Restore #{payload['restore_id']} با موفقیت کامل شد."
                ))
                self.stdout.write(
                    f"اتصال‌های دیتابیس هنگام Cutover: {database_state['active_sessions']}. "
                    "نسخه‌های قبلی DB و Media حفظ شده‌اند."
                )

        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Restore ناموفق بود: {exc}"))
            if maintenance_owned:
                try:
                    if journal.read()["phase"] == "COMPLETED":
                        # Cutover, migrations and health checks have all passed.
                        # A marker-removal/audit issue must not roll back a healthy system.
                        if active_units:
                            current = self._active_units(units)
                            self._start([unit for unit in active_units if unit not in current])
                            if set(self._active_units(active_units)) != set(active_units):
                                raise RestoreError("سرویس‌ها پس از تکمیل Restore فعال نیستند.")
                        self._health_check()
                        deactivate_maintenance(operation_id)
                        maintenance_owned = False
                        self.stderr.write(self.style.WARNING(
                            "Cutover و Health Check موفق بوده‌اند؛ فقط مرحله پایانی با خطا مواجه شد: "
                            + str(exc)
                        ))
                        return
                    if not active_units:
                        raise RestoreError(
                            "وضعیت سرویس‌های فعال قابل تأیید نیست؛ Maintenance برای ایمنی باقی می‌ماند."
                        )
                    # Re-stop any units that may have been started before a health failure.
                    if active_units:
                        currently_active = self._active_units(units)
                        self._stop(currently_active)
                        assert_systemd_services_stopped(units)
                    close_restore_worker_connection()

                    phase = journal.read()["phase"]
                    if phase in {"DATABASE_SWAPPED", "MEDIA_SWAPPED", "VALIDATING", "COMPLETED", "ROLLBACK_REQUIRED"}:
                        self.stderr.write("در حال بازگرداندن دیتابیس و Media قبلی...")
                        StagedRestoreRecovery(journal).rollback(service_units=units)
                        close_restore_worker_connection()
                        call_command("migrate", interactive=False, verbosity=0)
                        phase = "ROLLED_BACK"
                    if phase == "ROLLED_BACK":
                        Restore.objects.filter(pk=journal.read()["restore_id"]).update(
                            status=Restore.Status.FAILED,
                            error_message=("Restore ناموفق بود و نسخه قبلی با موفقیت بازگردانده شد: " + str(exc))[:4000],
                            completed_at=timezone.now(),
                        )

                    if active_units:
                        self._start(active_units)
                        if set(self._active_units(active_units)) != set(active_units):
                            raise RestoreError("راه‌اندازی مجدد سرویس‌ها کامل نشد.")
                    self._health_check()
                    deactivate_maintenance(operation_id)
                    maintenance_owned = False
                    self.stderr.write(self.style.WARNING(
                        "نسخه قبلی بازیابی شد؛ بررسی سلامت موفق بود و Maintenance برداشته شد."
                    ))
                except Exception as recovery_exc:
                    self.stderr.write(self.style.ERROR(
                        "Recovery کامل نشد؛ Maintenance عمداً فعال باقی ماند. "
                        "سرویس‌ها را دستی راه‌اندازی نکنید. " + str(recovery_exc)
                    ))
            try:
                journal.update(error=str(exc))
            except Exception:
                pass
            raise CommandError(str(exc)) from exc
