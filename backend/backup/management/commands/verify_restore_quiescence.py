"""Verify the maintenance gate, stopped systemd units and DB quiescence."""

from django.core.management.base import BaseCommand, CommandError

from backup.restore_maintenance import (
    RestoreMaintenanceError,
    read_maintenance_state,
)
from backup.restore_quiescence import (
    assert_database_quiescent,
    assert_systemd_services_stopped,
)
from backup.restore_services import RestoreError


class Command(BaseCommand):
    help = (
        "تأیید توقف سرویس‌های برنامه و صفر بودن اتصال‌های دیتابیس "
        "پیش از Cutover؛ این فرمان فقط بررسی می‌کند."
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
            state = read_maintenance_state()
            if state is None:
                raise RestoreError("Maintenance فعال نیست؛ ابتدا آن را فعال کنید.")
            if state.get("operation_id") != options["operation_id"]:
                raise RestoreError("شناسه عملیات با نشانگر Maintenance مطابقت ندارد.")

            services = assert_systemd_services_stopped(options["service_units"])
            database = assert_database_quiescent()

        except (RestoreError, RestoreMaintenanceError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("سرویس‌های متوقف‌شده:")
        for item in services:
            self.stdout.write(f"- {item['service']}: {item['state']}")
        self.stdout.write(
            f"Database: {database['database']} | Active sessions: {database['active_sessions']}"
        )
        self.stdout.write(self.style.SUCCESS(
            "بررسی Quiescence موفق بود. سرویس‌ها را تا پایان Cutover روشن نکنید."
        ))
