"""Inspect interrupted restore operations without changing any resources."""

from django.core.management.base import BaseCommand, CommandError

from backup.restore_recovery import inspect_restore_journals


class Command(BaseCommand):
    help = (
        "نمایش وضعیت عملیات Restore؛ این فرمان فقط‌خواندنی است و "
        "هیچ دیتابیس یا فایلی را تغییر نمی‌دهد."
    )

    def handle(self, *args, **options):
        inventory = inspect_restore_journals()
        if not inventory:
            self.stdout.write(self.style.SUCCESS(
                "هیچ عملیات Restore ثبت‌شده‌ای وجود ندارد."
            ))
            return

        recovery_required = 0
        self.stdout.write("گزارش وضعیت عملیات Restore:")
        for item in inventory:
            status = item["status"]
            needs_recovery = item["recovery_required"]
            recovery_required += int(needs_recovery)

            self.stdout.write("")
            self.stdout.write(f"Operation: {item['operation_id']}")
            if "restore_id" in item:
                self.stdout.write(f"Restore ID: {item['restore_id']}")
            self.stdout.write(f"Phase: {item.get('phase', '-')}")
            self.stdout.write(f"Status: {status}")
            self.stdout.write(
                "Recovery required: " + ("YES" if needs_recovery else "NO")
            )
            if item.get("updated_at"):
                self.stdout.write(f"Updated at: {item['updated_at']}")
            if item.get("error"):
                self.stdout.write(f"Error: {item['error']}")

        self.stdout.write("")
        self.stdout.write(
            f"Total: {len(inventory)} | Recovery required: {recovery_required}"
        )

        if recovery_required:
            raise CommandError(
                "عملیات Restore نیازمند بررسی و بازیابی دستی است؛ "
                "هیچ تغییری توسط این فرمان انجام نشد."
            )
        self.stdout.write(self.style.SUCCESS(
            "همه عملیات ثبت‌شده در وضعیت پایانی هستند."
        ))
