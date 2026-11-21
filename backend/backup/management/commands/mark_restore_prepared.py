"""Reconcile a Restore row with a fully prepared staged-restore journal."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from backup.models import Restore
from backup.restore_journal import RestoreJournal
from backup.restore_services import RestoreError


class Command(BaseCommand):
    help = (
        "ثبت وضعیت PREPARED برای Restore موجود، فقط پس از تأیید وجود "
        "دیتابیس و رسانه staging؛ بدون اجرای Cutover."
    )

    def add_arguments(self, parser):
        parser.add_argument("--operation-id", required=True)

    def handle(self, *args, **options):
        operation_id = options["operation_id"]
        try:
            journal = RestoreJournal(operation_id)
            payload = journal.read()
        except RestoreError as exc:
            raise CommandError(str(exc)) from exc

        if payload["phase"] != "PREPARED":
            raise CommandError("Journal در وضعیت PREPARED نیست؛ هیچ تغییری انجام نشد.")

        database = payload["database"]
        media = payload["media"]
        if not database.get("prepared") or not database.get("staging_name"):
            raise CommandError("دیتابیس staging آماده نیست؛ هیچ تغییری انجام نشد.")
        if media.get("included") and (
            not media.get("prepared") or not media.get("staging_path")
        ):
            raise CommandError("رسانه staging آماده نیست؛ هیچ تغییری انجام نشد.")

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                [database["staging_name"]],
            )
            if cursor.fetchone() is None:
                raise CommandError("دیتابیس staging وجود ندارد؛ هیچ تغییری انجام نشد.")

        if media.get("included") and not Path(media["staging_path"]).is_dir():
            raise CommandError("پوشه رسانه staging وجود ندارد؛ هیچ تغییری انجام نشد.")

        restore_id = payload["restore_id"]
        updated = Restore.objects.filter(
            pk=restore_id,
            status=Restore.Status.RESTORING,
        ).update(
            status=Restore.Status.PREPARED,
            updated_at=timezone.now(),
        )

        if not updated:
            restore = Restore.objects.filter(pk=restore_id).first()
            if restore is None:
                raise CommandError(
                    f"Restore #{restore_id} پیدا نشد؛ Journal و staging حفظ شدند."
                )
            if restore.status != Restore.Status.PREPARED:
                raise CommandError(
                    f"وضعیت فعلی Restore برابر {restore.status} است؛ "
                    "به‌صورت خودکار تغییر داده نشد."
                )

        self.stdout.write(self.style.SUCCESS(
            f"Restore #{restore_id}: PREPARED | operation={operation_id} | "
            "Cutover انجام نشد."
        ))
