"""Conservatively roll back a crashed staged restore cutover."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pathlib import Path

from backup.restore_journal import RestoreJournal
from backup.restore_maintenance import RestoreMaintenanceError
from backup.restore_services import RestoreError
from backup.staged_restore_recovery import StagedRestoreRecovery


class Command(BaseCommand):
    help = (
        "بازیابی محافظه‌کارانه عملیات Cutover نیمه‌تمام؛ "
        "فقط دیتابیس و رسانه قبلی را بازمی‌گرداند و چیزی را حذف نمی‌کند."
    )

    def add_arguments(self, parser):
        parser.add_argument("--operation-id", required=True)
        parser.add_argument(
            "--service-unit",
            action="append",
            dest="service_units",
            required=True,
            help="نام هر واحد systemd؛ برای هر سرویس یک بار تکرار شود.",
        )

    def handle(self, *args, **options):
        try:
            journal = RestoreJournal(
                options["operation_id"],
                root=getattr(
                    settings,
                    "RESTORE_JOURNAL_ROOT",
                    Path(settings.BACKUP_ROOT) / ".restore-journal",
                ),
            )
            result = StagedRestoreRecovery(journal).rollback(
                service_units=options["service_units"]
            )
        except (RestoreError, RestoreMaintenanceError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Recovery complete: {result['status']} | operation={options['operation_id']}"
        ))
        self.stdout.write(
            "دیتابیس و رسانه قبلی بازگردانده و وضعیت Journal تأیید شد. "
            "منابع staging و نسخه‌های نگهداری‌شده حذف نشده‌اند."
        )
