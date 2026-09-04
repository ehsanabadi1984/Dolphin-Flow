import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from backup.models import Backup
from backup.services import BackupService

from .test_service import _make_fake_pg_dump

CHANGELIST_URL = reverse("admin:backup_backup_changelist")
CREATE_URL = reverse("admin:backup_backup_create")


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