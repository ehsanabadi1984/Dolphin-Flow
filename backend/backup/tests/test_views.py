import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from backup.models import Backup, Restore
from backup.services import BackupService

from .test_service import _make_fake_pg_dump

CHANGELIST_URL = reverse("admin:backup_backup_changelist")
CREATE_URL = reverse("admin:backup_backup_create")
RESTORE_HISTORY_URL = reverse("admin:backup_restore_changelist")


class BackupViewTestCase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.media_root = self.tmp / "media"
        self.backup_root = self.tmp / "backups"
        self.enterContext(
            override_settings(
                BACKUP_ROOT=self.backup_root,
                MEDIA_ROOT=self.media_root,
                PG_DUMP_PATH="pg_dump",
            )
        )

        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="root",
            password="secret",
        )

    _test_counter = 0

    def _next_username(self):
        BackupViewTestCase._test_counter += 1
        return f"staff_{BackupViewTestCase._test_counter}"

    def make_staff(self, *codenames):
        User = get_user_model()
        user = User.objects.create_user(
            username=self._next_username(),
            password="secret",
            is_staff=True,
        )
        for codename in codenames:
            permission = Permission.objects.get(
                codename=codename,
                content_type__app_label="backup",
            )
            user.user_permissions.add(permission)
        return user

    def make_success_backup(self, user=None):
        """Build a real SUCCESS backup with a real file on disk."""
        media_file = self.media_root / "photo.jpg"
        media_file.parent.mkdir(parents=True, exist_ok=True)
        media_file.write_bytes(b"media-content")

        backup = Backup.objects.create(
            filename="DolphinFlow_Backup_2026-09-04_020000.dfbak",
            created_by=user,
        )

        with _make_fake_pg_dump():
            BackupService(backup).run()

        backup.refresh_from_db()
        self.assertEqual(backup.status, Backup.Status.SUCCESS)
        return backup

    # ----------------------------------------------------------
    # Changelist
    # ----------------------------------------------------------

    def test_changelist_requires_staff_login(self):
        response = self.client.get(CHANGELIST_URL)
        self.assertIn(response.status_code, (301, 302))

    def test_changelist_denied_without_view_permission(self):
        user = self.make_staff()
        self.client.force_login(user)
        response = self.client.get(CHANGELIST_URL)
        self.assertEqual(response.status_code, 403)

    def test_changelist_renders_for_superuser(self):
        self.client.force_login(self.superuser)
        response = self.client.get(CHANGELIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پشتیبان‌گیری")
        self.assertContains(response, "ایجاد پشتیبان")
        self.assertContains(response, "هنوز پشتیبانی ایجاد نشده است.")

    def test_changelist_hides_create_button_without_permission(self):
        user = self.make_staff("view_backup")
        self.client.force_login(user)
        response = self.client.get(CHANGELIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "ایجاد پشتیبان")

    def test_changelist_lists_backup_rows(self):
        self.make_success_backup(user=self.superuser)
        self.client.force_login(self.superuser)
        response = self.client.get(CHANGELIST_URL)
        self.assertContains(
            response,
            "DolphinFlow_Backup_2026-09-04_020000.dfbak",
        )
        self.assertContains(response, "دانلود")

    def test_changelist_summary_shows_latest_success(self):
        self.make_success_backup(user=self.superuser)
        self.client.force_login(self.superuser)
        response = self.client.get(CHANGELIST_URL)
        self.assertContains(
            response,
            "آخرین پشتیبان موفق",
        )

    # ----------------------------------------------------------
    # Create
    # ----------------------------------------------------------

    def test_create_requires_permission(self):
        user = self.make_staff("view_backup")
        self.client.force_login(user)
        response = self.client.post(CREATE_URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Backup.objects.count(), 0)

    def test_create_requires_post(self):
        self.client.force_login(self.superuser)
        response = self.client.get(CREATE_URL)
        self.assertEqual(response.status_code, 405)

    def test_create_queues_backup_and_task(self):
        self.client.force_login(self.superuser)

        with mock.patch(
            "backup.admin.run_backup.delay"
        ) as mocked_delay:
            response = self.client.post(
                CREATE_URL,
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Backup.objects.count(), 1)

        backup = Backup.objects.get()
        self.assertEqual(backup.status, Backup.Status.QUEUED)
        self.assertEqual(backup.created_by, self.superuser)
        self.assertTrue(
            backup.filename.startswith("DolphinFlow_Backup_")
        )
        self.assertTrue(backup.filename.endswith(".dfbak"))

        mocked_delay.assert_called_once_with(backup.pk)

        self.assertContains(
            response,
            "در صف اجرا قرار گرفت",
        )

    def test_create_blocked_while_backup_active(self):
        Backup.objects.create(status=Backup.Status.RUNNING)
        self.client.force_login(self.superuser)

        with mock.patch(
            "backup.admin.run_backup.delay"
        ) as mocked_delay:
            response = self.client.post(
                CREATE_URL,
                follow=True,
            )

        self.assertEqual(Backup.objects.count(), 1)
        mocked_delay.assert_not_called()
        self.assertContains(
            response,
            "در حال اجراست",
        )

    def test_create_propagates_backup_include_media_setting(self):
        self.client.force_login(self.superuser)

        with mock.patch(
            "backup.admin.run_backup.delay"
        ), override_settings(BACKUP_INCLUDE_MEDIA=False):
            self.client.post(CREATE_URL)

        backup = Backup.objects.get()
        self.assertFalse(backup.includes_media)

        # Clear the QUEUED record so the active-backup guard does not block
        # the next create.
        Backup.objects.all().delete()

        with mock.patch(
            "backup.admin.run_backup.delay"
        ), override_settings(BACKUP_INCLUDE_MEDIA=True):
            self.client.post(CREATE_URL)

        latest = Backup.objects.get()
        self.assertTrue(latest.includes_media)

    # ----------------------------------------------------------
    # Download
    # ----------------------------------------------------------

    def test_download_requires_permission(self):
        backup = self.make_success_backup(user=self.superuser)
        user = self.make_staff("view_backup")
        self.client.force_login(user)

        response = self.client.get(
            reverse("admin:backup_backup_download", args=[backup.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_download_success(self):
        backup = self.make_success_backup(user=self.superuser)
        self.client.force_login(self.superuser)

        response = self.client.get(
            reverse("admin:backup_backup_download", args=[backup.pk])
        )

        self.assertEqual(response.status_code, 200)
        final_path = self.backup_root / backup.storage_path
        self.assertEqual(
            b"".join(response.streaming_content),
            final_path.read_bytes(),
        )
        self.assertIn(
            "attachment",
            response["Content-Disposition"],
        )
        self.assertIn(
            backup.filename,
            response["Content-Disposition"],
        )

    def test_download_only_for_success(self):
        for status in (
            Backup.Status.QUEUED,
            Backup.Status.RUNNING,
            Backup.Status.FAILED,
        ):
            backup = Backup.objects.create(status=status)
            self.client.force_login(self.superuser)
            response = self.client.get(
                reverse(
                    "admin:backup_backup_download",
                    args=[backup.pk],
                )
            )
            self.assertEqual(response.status_code, 404)

    def test_download_missing_file_is_404(self):
        backup = Backup.objects.create(
            status=Backup.Status.SUCCESS,
            storage_path="ghost.dfbak",
        )
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("admin:backup_backup_download", args=[backup.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_download_rejects_path_traversal(self):
        backup = Backup.objects.create(
            status=Backup.Status.SUCCESS,
            storage_path="../../etc/passwd",
        )
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("admin:backup_backup_download", args=[backup.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_download_unknown_backup_is_404(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("admin:backup_backup_download", args=[999_999])
        )
        self.assertEqual(response.status_code, 404)

    # ----------------------------------------------------------
    # Delete
    # ----------------------------------------------------------

    def test_delete_requires_permission(self):
        backup = self.make_success_backup(user=self.superuser)
        user = self.make_staff("view_backup")
        self.client.force_login(user)
        response = self.client.post(
            reverse("admin:backup_backup_delete", args=[backup.pk]),
            {"post": "yes"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Backup.objects.filter(pk=backup.pk).exists())

    def test_delete_removes_record_and_file(self):
        backup = self.make_success_backup(user=self.superuser)
        final_path = self.backup_root / backup.storage_path
        self.assertTrue(final_path.exists())

        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("admin:backup_backup_delete", args=[backup.pk]),
            {"post": "yes"},
        )

        self.assertIn(response.status_code, (301, 302))
        self.assertFalse(Backup.objects.filter(pk=backup.pk).exists())
        self.assertFalse(final_path.exists())

    def test_delete_backup_without_file(self):
        backup = Backup.objects.create(status=Backup.Status.QUEUED)
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("admin:backup_backup_delete", args=[backup.pk]),
            {"post": "yes"},
        )
        self.assertIn(response.status_code, (301, 302))
        self.assertFalse(Backup.objects.filter(pk=backup.pk).exists())

    # ----------------------------------------------------------
    # System admin navigation
    # ----------------------------------------------------------

    def test_admin_index_shows_backup_under_system(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پشتیبان‌گیری")
        self.assertContains(response, "/admin/backup/backup/")

    def test_manifest_not_exposed_via_media_url(self):
        backup = self.make_success_backup(user=self.superuser)
        media_url = f"/media/{backup.storage_path}"
        self.client.force_login(self.superuser)
        response = self.client.get(media_url)
        self.assertEqual(response.status_code, 404)

    # ----------------------------------------------------------
    # Restore (confirm page + async initiation)
    # ----------------------------------------------------------

    def restore_url(self, backup):
        return reverse(
            "admin:backup_backup_restore",
            args=[backup.pk],
        )

    def test_restore_requires_restore_permission(self):
        backup = self.make_success_backup(user=self.superuser)
        user = self.make_staff("view_backup", "download_backup")
        self.client.force_login(user)

        response = self.client.get(self.restore_url(backup))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            self.restore_url(backup),
            {"confirm": "1"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Restore.objects.count(), 0)

    def test_restore_confirm_page_renders_manifest_preview(self):
        backup = self.make_success_backup(user=self.superuser)
        self.client.force_login(self.superuser)

        response = self.client.get(self.restore_url(backup))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "بازیابی از پشتیبان")
        self.assertContains(response, backup.filename)
        self.assertContains(response, "name=\"confirm\"")
        self.assertContains(response, "postgresql")

    def test_restore_confirm_page_refuses_unsuccessful_backup(self):
        queued = Backup.objects.create(
            status=Backup.Status.QUEUED,
            filename="pending.dfbak",
        )
        self.client.force_login(self.superuser)

        response = self.client.get(self.restore_url(queued))
        self.assertIn(response.status_code, (301, 302))
        self.assertEqual(Restore.objects.count(), 0)

    def test_restore_post_requires_confirmation_flag(self):
        backup = self.make_success_backup(user=self.superuser)
        self.client.force_login(self.superuser)

        with mock.patch(
            "backup.admin.run_restore.delay"
        ) as mocked_delay:
            response = self.client.post(
                self.restore_url(backup),
                {},
                follow=True,
            )

        self.assertEqual(Restore.objects.count(), 0)
        mocked_delay.assert_not_called()
        self.assertContains(response, "تأیید صریح")

    def test_restore_post_queues_restore_and_task(self):
        backup = self.make_success_backup(user=self.superuser)
        self.client.force_login(self.superuser)

        with mock.patch(
            "backup.admin.run_restore.delay"
        ) as mocked_delay:
            response = self.client.post(
                self.restore_url(backup),
                {"confirm": "1"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Restore.objects.count(), 1)

        restore = Restore.objects.get()
        self.assertEqual(restore.status, Restore.Status.QUEUED)
        self.assertEqual(restore.backup_id, backup.pk)
        self.assertEqual(restore.archive_filename, backup.filename)
        self.assertEqual(restore.requested_by, self.superuser)
        self.assertEqual(
            restore.requested_by_username,
            self.superuser.get_username(),
        )
        self.assertTrue(restore.includes_media)
        self.assertEqual(restore.product_version, "1.0.0")

        mocked_delay.assert_called_once_with(restore.pk)

        self.assertContains(
            response,
            "در صف اجرا قرار گرفت",
        )

    def test_restore_post_blocked_while_backup_active(self):
        backup = self.make_success_backup(user=self.superuser)
        Backup.objects.create(status=Backup.Status.RUNNING)
        self.client.force_login(self.superuser)

        with mock.patch(
            "backup.admin.run_restore.delay"
        ) as mocked_delay:
            response = self.client.post(
                self.restore_url(backup),
                {"confirm": "1"},
                follow=True,
            )

        self.assertEqual(Restore.objects.count(), 0)
        mocked_delay.assert_not_called()
        self.assertContains(response, "در حال اجراست")

    def test_restore_post_blocked_while_restore_active(self):
        backup = self.make_success_backup(user=self.superuser)
        Restore.objects.create(
            status=Restore.Status.RESTORING,
            archive_filename="running-restore.dfbak",
        )
        self.client.force_login(self.superuser)

        with mock.patch(
            "backup.admin.run_restore.delay"
        ) as mocked_delay:
            response = self.client.post(
                self.restore_url(backup),
                {"confirm": "1"},
                follow=True,
            )

        self.assertEqual(Restore.objects.count(), 1)
        mocked_delay.assert_not_called()
        self.assertContains(response, "در حال اجراست")

    def test_changelist_hides_restore_button_without_permission(self):
        self.make_success_backup(user=self.superuser)
        user = self.make_staff("view_backup", "download_backup")
        self.client.force_login(user)

        response = self.client.get(CHANGELIST_URL)
        self.assertNotContains(response, "بازیابی")

    def test_changelist_shows_restore_button_with_permission(self):
        self.make_success_backup(user=self.superuser)
        user = self.make_staff(
            "view_backup",
            "download_backup",
            "restore_backup",
        )
        self.client.force_login(user)

        response = self.client.get(CHANGELIST_URL)
        self.assertContains(response, "بازیابی")

    # ----------------------------------------------------------
    # Restore history page
    # ----------------------------------------------------------

    def test_restore_history_requires_view_permission(self):
        user = self.make_staff("view_backup")
        self.client.force_login(user)
        response = self.client.get(RESTORE_HISTORY_URL)
        self.assertEqual(response.status_code, 403)

    def test_restore_history_renders_for_superuser(self):
        self.client.force_login(self.superuser)
        response = self.client.get(RESTORE_HISTORY_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تاریخچه بازیابی")
        self.assertContains(response, "هنوز بازیابی‌ای انجام نشده است.")

    def test_restore_history_lists_rows(self):
        Restore.objects.create(
            archive_filename="history.dfbak",
            status=Restore.Status.FAILED,
            error_message="یک خطای آزمایشی",
            requested_by_username="root",
        )
        self.client.force_login(self.superuser)

        response = self.client.get(RESTORE_HISTORY_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "history.dfbak")
        self.assertContains(response, "یک خطای آزمایشی")
        self.assertContains(response, "root")