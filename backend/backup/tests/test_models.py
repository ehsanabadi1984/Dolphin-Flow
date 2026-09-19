from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from backup.models import Backup, BackupSchedule, Restore, generate_backup_filename


class BackupModelTests(TestCase):
    def test_default_status_is_queued(self):
        backup = Backup.objects.create()
        self.assertEqual(backup.status, Backup.Status.QUEUED)

    def test_status_choices(self):
        choices = dict(Backup.Status.choices)
        self.assertEqual(
            choices,
            {
                "QUEUED": "در صف",
                "RUNNING": "در حال اجرا",
                "SUCCESS": "موفق",
                "FAILED": "ناموفق",
            },
        )

    def test_meta_permissions_include_create_and_download(self):
        codenames = {
            codename
            for codename, _ in Backup._meta.permissions
        }
        self.assertIn("create_backup", codenames)
        self.assertIn("download_backup", codenames)

    def test_duration_none_without_completion(self):
        backup = Backup.objects.create()
        self.assertIsNone(backup.duration)
        self.assertEqual(backup.duration_display, "—")

    def test_duration_derived_from_started_and_completed(self):
        start = timezone.now()
        backup = Backup.objects.create(
            started_at=start,
            completed_at=start + timezone.timedelta(seconds=65),
        )
        self.assertEqual(
            backup.duration,
            timezone.timedelta(seconds=65),
        )
        self.assertEqual(
            backup.duration_display,
            "1 دقیقه و 5 ثانیه",
        )

    def test_generate_backup_filename_format(self):
        moment = timezone.make_aware(
            timezone.datetime(2026, 9, 4, 2, 0, 0)
        )
        name = generate_backup_filename(moment)
        self.assertEqual(
            name,
            "DolphinFlow_Backup_2026-09-04_020000.dfbak",
        )

    def test_created_by_link(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="admin",
            password="secret",
        )
        backup = Backup.objects.create(created_by=user)
        self.assertEqual(backup.created_by, user)
        self.assertIn(backup, user.created_backups.all())

    def test_pre_restore_backup_flag_defaults_false(self):
        backup = Backup.objects.create()
        self.assertFalse(backup.is_pre_restore_backup)


class BackupScheduleModelTests(TestCase):
    def test_daily_schedule_calculates_next_run(self):
        now = timezone.make_aware(timezone.datetime(2026, 9, 19, 10, 0, 0))
        schedule = BackupSchedule(
            name="Daily backup",
            frequency=BackupSchedule.Frequency.DAILY,
            time_of_day=timezone.datetime(2026, 9, 19, 12, 30).time(),
        )
        next_run = schedule.calculate_next_run(now)
        self.assertEqual(
            timezone.localtime(next_run).strftime("%Y-%m-%d %H:%M"),
            "2026-09-19 12:30",
        )

    def test_weekly_schedule_calculates_next_weekday(self):
        now = timezone.make_aware(timezone.datetime(2026, 9, 19, 10, 0, 0))
        schedule = BackupSchedule(
            name="Friday backup",
            frequency=BackupSchedule.Frequency.WEEKLY,
            weekday=BackupSchedule.Weekday.FRIDAY,
            time_of_day=timezone.datetime(2026, 9, 19, 9, 0).time(),
        )
        next_run = schedule.calculate_next_run(now)
        self.assertEqual(
            timezone.localtime(next_run).strftime("%Y-%m-%d %H:%M"),
            "2026-09-25 09:00",
        )

    def test_monthly_day_31_uses_last_day_in_short_month(self):
        now = timezone.make_aware(timezone.datetime(2026, 2, 1, 10, 0, 0))
        schedule = BackupSchedule(
            name="Month end backup",
            frequency=BackupSchedule.Frequency.MONTHLY,
            day_of_month=31,
            time_of_day=timezone.datetime(2026, 2, 1, 23, 0).time(),
        )
        next_run = schedule.calculate_next_run(now)
        self.assertEqual(
            timezone.localtime(next_run).strftime("%Y-%m-%d %H:%M"),
            "2026-02-28 23:00",
        )

    def test_interval_schedule_uses_start_anchor(self):
        now = timezone.make_aware(timezone.datetime(2026, 9, 19, 10, 0, 0))
        schedule = BackupSchedule(
            name="Every six hours",
            frequency=BackupSchedule.Frequency.INTERVAL,
            starts_at=now,
            interval_minutes=360,
        )
        next_run = schedule.calculate_next_run(now)
        self.assertEqual(next_run, now + timezone.timedelta(minutes=360))

    def test_schedule_can_be_linked_to_backup(self):
        schedule = BackupSchedule.objects.create(
            name="Scheduled backup",
            enabled=True,
            frequency=BackupSchedule.Frequency.DAILY,
            time_of_day=timezone.datetime(2026, 9, 19, 2, 0).time(),
        )
        backup = Backup.objects.create(schedule=schedule)
        self.assertEqual(backup.schedule, schedule)
        self.assertIn(backup, schedule.backups.all())


class RestoreModelTests(TestCase):
    def test_default_status_is_queued(self):
        restore = Restore.objects.create(
            archive_filename="DolphinFlow_Backup_x.dfbak"
        )
        self.assertEqual(restore.status, Restore.Status.QUEUED)

    def test_status_choices(self):
        choices = dict(Restore.Status.choices)
        self.assertEqual(
            choices,
            {
                "QUEUED": "در صف",
                "RESTORING": "در حال بازیابی",
                "SUCCESS": "موفق",
                "FAILED": "ناموفق",
            },
        )

    def test_meta_permissions_include_restore(self):
        codenames = {
            codename
            for codename, _ in Restore._meta.permissions
        }
        self.assertIn("restore_backup", codenames)

    def test_backup_relation(self):
        backup = Backup.objects.create(
            filename="DolphinFlow_Backup_x.dfbak"
        )
        restore = Restore.objects.create(
            backup=backup,
            archive_filename=backup.filename,
        )
        self.assertEqual(restore.backup, backup)
        self.assertIn(restore, backup.restores.all())

    def test_duration_derived_from_started_and_completed(self):
        start = timezone.now()
        restore = Restore.objects.create(
            archive_filename="a.dfbak",
            started_at=start,
            completed_at=start + timezone.timedelta(seconds=5),
        )
        self.assertEqual(
            restore.duration,
            timezone.timedelta(seconds=5),
        )
        self.assertEqual(restore.duration_display, "5 ثانیه")