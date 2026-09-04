import logging

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import ModelAdmin
from django.core.exceptions import PermissionDenied
from django.http import (
    FileResponse,
    Http404,
    HttpResponseNotAllowed,
)
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path

from workflow.admin import dolphin_admin_site

from .models import Backup, generate_backup_filename
from .storage import BackupStorageError, LocalBackupStorage
from .tasks import run_backup

logger = logging.getLogger(__name__)


@admin.register(Backup, site=dolphin_admin_site)
class BackupAdmin(ModelAdmin):
    admin_category = "system"
    admin_section = "backups"

    list_display = (
        "filename",
        "status",
        "size",
        "created_at",
        "created_by",
    )

    readonly_fields = (
        "filename",
        "status",
        "started_at",
        "completed_at",
        "storage_path",
        "size",
        "database_size",
        "media_size",
        "includes_media",
        "checksum",
        "created_by",
        "error_message",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        # Creation happens exclusively through the "Create Backup" endpoint,
        # never through Django's generic add form.
        return False

    def has_change_permission(self, request, obj=None):
        # Backups are immutable once created.
        return False

    # ----------------------------------------------------------
    # URL wiring
    # ----------------------------------------------------------

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "create/",
                self.admin_site.admin_view(
                    self.create_backup_view
                ),
                name="backup_backup_create",
            ),
            path(
                "<path:object_id>/download/",
                self.admin_site.admin_view(
                    self.download_backup_view
                ),
                name="backup_backup_download",
            ),
        ]

        return custom_urls + urls

    # ----------------------------------------------------------
    # Permission helpers
    # ----------------------------------------------------------

    def _has_perm(self, request, codename):
        return request.user.has_perm(f"backup.{codename}")

    # ----------------------------------------------------------
    # List page
    # ----------------------------------------------------------

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied

        extra_context = extra_context or {}

        extra_context.update(
            {
                "opts": self.model._meta,
                "backups": list(
                    Backup.objects.select_related("created_by")
                    .order_by("-created_at")[:100]
                ),
                "latest_success": (
                    Backup.objects.filter(
                        status=Backup.Status.SUCCESS
                    )
                    .order_by("-completed_at")
                    .first()
                ),
                "has_active_backup": Backup.objects.filter(
                    status__in=(
                        Backup.Status.QUEUED,
                        Backup.Status.RUNNING,
                    )
                ).exists(),
                "can_create_backup": self._has_perm(
                    request,
                    "create_backup",
                ),
                "can_download_backup": self._has_perm(
                    request,
                    "download_backup",
                ),
                "can_delete_backup": self._has_perm(
                    request,
                    "delete_backup",
                ),
                "title": "پشتیبان‌گیری",
            }
        )

        context = {
            **self.admin_site.each_context(request),
            **extra_context,
        }

        return TemplateResponse(
            request,
            "admin/backup/backup/change_list.html",
            context,
        )

    # ----------------------------------------------------------
    # Create Backup (async: record QUEUED, enqueue Celery task)
    # ----------------------------------------------------------

    def create_backup_view(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        if not self._has_perm(request, "create_backup"):
            raise PermissionDenied

        active_exists = Backup.objects.filter(
            status__in=(
                Backup.Status.QUEUED,
                Backup.Status.RUNNING,
            )
        ).exists()

        if active_exists:
            messages.warning(
                request,
                "هم‌اکنون یک پشتیبان‌گیری در حال اجراست؛ "
                "پس از اتمام آن دوباره تلاش کنید.",
            )
            return redirect(
                "admin:backup_backup_changelist"
            )

        backup = Backup.objects.create(
            filename=generate_backup_filename(),
            includes_media=settings.BACKUP_INCLUDE_MEDIA,
            created_by=(
                request.user
                if request.user.is_authenticated
                else None
            ),
        )

        run_backup.delay(backup.pk)

        messages.success(
            request,
            f"پشتیبان‌گیری «{backup.filename}» در صف اجرا قرار گرفت.",
        )

        return redirect("admin:backup_backup_changelist")

    # ----------------------------------------------------------
    # Download (only successful, permission-protected, path-safe)
    # ----------------------------------------------------------

    def download_backup_view(self, request, object_id):
        if not self._has_perm(request, "download_backup"):
            raise PermissionDenied

        backup = get_object_or_404(Backup, pk=object_id)

        if backup.status != Backup.Status.SUCCESS:
            raise Http404("پشتیبان هنوز آماده دانلود نیست.")

        storage = LocalBackupStorage()

        try:
            path = storage.path_for(backup.storage_path)
        except BackupStorageError:
            raise Http404("فایل پشتیبان یافت نشد.")

        if not storage.exists(path):
            raise Http404("فایل پشتیبان یافت نشد.")

        return FileResponse(
            storage.open(backup.storage_path, "rb"),
            as_attachment=True,
            filename=backup.filename,
        )

    # ----------------------------------------------------------
    # Delete (admin confirmation flow + safe file removal)
    # ----------------------------------------------------------

    def delete_model(self, request, obj):
        if obj.storage_path:
            try:
                LocalBackupStorage().delete(obj.storage_path)
            except BackupStorageError as exc:
                logger.error(
                    "Refusing to remove file for backup #%s: %s",
                    obj.pk,
                    exc,
                )
                raise

        super().delete_model(request, obj)