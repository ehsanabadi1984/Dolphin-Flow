import logging

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import ModelAdmin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path

from workflow.admin import dolphin_admin_site

from .import_service import BackupImportService
from .models import Backup, Restore, generate_backup_filename
from .restore_services import RestoreError, read_manifest
from .storage import BackupImportError, BackupStorageError, LocalBackupStorage
from .tasks import run_backup, run_restore

logger = logging.getLogger(__name__)


@admin.register(Backup, site=dolphin_admin_site)
class BackupAdmin(ModelAdmin):
    admin_category = "system"
    admin_section = "backups"

    list_display = ("filename", "status", "size", "created_at", "created_by")
    readonly_fields = (
        "filename", "status", "started_at", "completed_at", "storage_path",
        "size", "database_size", "media_size", "includes_media", "checksum",
        "created_by", "error_message", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("create/", self.admin_site.admin_view(self.create_backup_view), name="backup_backup_create"),
            path("import/", self.admin_site.admin_view(self.import_backup_view), name="backup_backup_import"),
            path("import/confirm/", self.admin_site.admin_view(self.import_confirm_view), name="backup_backup_import_confirm"),
            path("<path:object_id>/download/", self.admin_site.admin_view(self.download_backup_view), name="backup_backup_download"),
            path("<path:object_id>/restore/", self.admin_site.admin_view(self.restore_view), name="backup_backup_restore"),
        ]
        return custom_urls + urls

    def _has_perm(self, request, codename):
        return request.user.has_perm(f"backup.{codename}")

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied
        extra_context = extra_context or {}
        extra_context.update({
            "opts": self.model._meta,
            "backups": list(Backup.objects.select_related("created_by").order_by("-created_at")[:100]),
            "latest_success": Backup.objects.filter(status=Backup.Status.SUCCESS).order_by("-completed_at").first(),
            "has_active_backup": Backup.objects.filter(status__in=(Backup.Status.QUEUED, Backup.Status.RUNNING)).exists(),
            "can_create_backup": self._has_perm(request, "create_backup"),
            "can_download_backup": self._has_perm(request, "download_backup"),
            "can_delete_backup": self._has_perm(request, "delete_backup"),
            "can_restore_backup": self._has_perm(request, "restore_backup"),
            "has_active_restore": Restore.objects.filter(status__in=(Restore.Status.QUEUED, Restore.Status.RESTORING)).exists(),
            "title": "پشتیبان‌گیری",
        })
        return TemplateResponse(request, "admin/backup/backup/change_list.html", {
            **self.admin_site.each_context(request), **extra_context,
        })

    def create_backup_view(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self._has_perm(request, "create_backup"):
            raise PermissionDenied
        if Backup.objects.filter(status__in=(Backup.Status.QUEUED, Backup.Status.RUNNING)).exists():
            messages.warning(request, "هم‌اکنون یک پشتیبان‌گیری در حال اجراست؛ پس از اتمام آن دوباره تلاش کنید.")
            return redirect("admin:backup_backup_changelist")
        backup = Backup.objects.create(
            filename=generate_backup_filename(),
            includes_media=settings.BACKUP_INCLUDE_MEDIA,
            created_by=request.user if request.user.is_authenticated else None,
        )
        run_backup.delay(backup.pk)
        messages.success(request, f"پشتیبان‌گیری «{backup.filename}» در صف اجرا قرار گرفت.")
        return redirect("admin:backup_backup_changelist")

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
        return FileResponse(storage.open(backup.storage_path, "rb"), as_attachment=True, filename=backup.filename)

    def _read_manifest_for_backup(self, backup):
        storage = LocalBackupStorage()
        try:
            path = storage.path_for(backup.storage_path)
        except BackupStorageError as exc:
            raise RestoreError(str(exc)) from exc
        if not storage.exists(path):
            raise RestoreError("فایل پشتیبان یافت نشد.")
        return read_manifest(path)

    def _active_operation_message(self):
        if Backup.objects.filter(status__in=(Backup.Status.QUEUED, Backup.Status.RUNNING)).exists():
            return "هم‌اکنون یک پشتیبان‌گیری در حال اجراست؛ پس از اتمام آن دوباره تلاش کنید."
        if Restore.objects.filter(status__in=(Restore.Status.QUEUED, Restore.Status.RESTORING)).exists():
            return "هم‌اکنون یک بازیابی در حال اجراست؛ پس از اتمام آن دوباره تلاش کنید."
        return None

    def restore_view(self, request, object_id):
        if not self._has_perm(request, "restore_backup"):
            raise PermissionDenied
        backup = get_object_or_404(Backup, pk=object_id)
        if backup.status != Backup.Status.SUCCESS:
            messages.warning(request, "فقط پشتیبان‌های موفق قابل بازیابی هستند.")
            return redirect("admin:backup_backup_changelist")
        if request.method != "POST":
            return self._render_restore_confirm(request, backup)
        if request.POST.get("confirm") != "1":
            messages.error(request, "برای شروع بازیابی باید تأیید صریح انجام دهید.")
            return redirect("admin:backup_backup_changelist")
        busy = self._active_operation_message()
        if busy:
            messages.warning(request, busy)
            return redirect("admin:backup_backup_changelist")
        try:
            manifest = self._read_manifest_for_backup(backup)
        except RestoreError as exc:
            messages.error(request, f"بایگانی قابل بازیابی نیست: {exc}")
            return redirect("admin:backup_backup_changelist")
        restore = Restore.objects.create(
            backup=backup,
            archive_filename=backup.filename,
            status=Restore.Status.QUEUED,
            requested_by=request.user if request.user.is_authenticated else None,
            requested_by_username=request.user.get_username() if request.user.is_authenticated else "",
            product_version=str(manifest.get("product_version", "") or ""),
            database_engine=str(manifest.get("database_engine", "") or ""),
            database_backup_format=str(manifest.get("database_backup_format", "") or ""),
            includes_media=bool(manifest.get("includes_media")),
        )
        run_restore.delay(restore.pk)
        messages.success(request, f"بازیابی از «{backup.filename}» در صف اجرا قرار گرفت.")
        return redirect("admin:backup_restore_changelist")

    def _render_restore_confirm(self, request, backup):
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "backup": backup,
            "manifest": None,
            "manifest_error": None,
            "title": f"بازیابی از {backup.filename}",
        }
        try:
            manifest = self._read_manifest_for_backup(backup)
            context["manifest"] = manifest
        except RestoreError as exc:
            context["manifest_error"] = str(exc)
        return TemplateResponse(request, "admin/backup/backup/restore_confirm.html", context)

    # ----------------------------------------------------------
    # Import external .dfbak
    # ----------------------------------------------------------

    def import_backup_view(self, request):
        if not self._has_perm(request, "restore_backup"):
            raise PermissionDenied
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        busy = self._active_operation_message()
        if busy:
            messages.warning(request, busy)
            return redirect("admin:backup_backup_changelist")

        uploaded_file = request.FILES.get("backup_file")
        if not uploaded_file:
            messages.error(request, "فایل پشتیبان انتخاب نشد.")
            return redirect("admin:backup_backup_changelist")

        original_name = uploaded_file.name or ""
        if not original_name.lower().endswith(".dfbak"):
            messages.error(request, "فایل باید با پسوند .dfbak باشد.")
            return redirect("admin:backup_backup_changelist")

        try:
            result = BackupImportService().import_backup(uploaded_file, original_name, user=request.user)
        except BackupImportError as exc:
            logger.warning("Import failed for file %s: %s", original_name, exc)
            messages.error(request, f"مشکلی در خواندن فایل پشتیبان به وجود آمد: {exc}")
            return redirect("admin:backup_backup_changelist")

        request.session["pending_import_backup_id"] = result["backup"].pk
        request.session["pending_import_manifest"] = result["manifest"]
        request.session["pending_import_filename"] = result["filename"]
        request.session.modified = True
        return redirect("admin:backup_backup_import_confirm")

    def import_confirm_view(self, request):
        if not self._has_perm(request, "restore_backup"):
            raise PermissionDenied

        backup_id = request.session.get("pending_import_backup_id")
        manifest_data = request.session.get("pending_import_manifest", {})
        if not backup_id:
            messages.warning(request, "صفحه‌ای برای تأیید پیدا نشد. لطفاً مجدداً آپلود کنید.")
            return redirect("admin:backup_backup_changelist")

        backup = get_object_or_404(Backup, pk=backup_id)

        if request.method != "POST":
            return self._render_import_confirm(request, backup, manifest_data)

        # Capture session data BEFORE clearing it. The old implementation
        # deleted the manifest first and then tried to read it.
        if request.POST.get("confirm") != "1":
            messages.error(request, "برای شروع بازیابی باید تأیید صریح انجام دهید.")
            return redirect("admin:backup_backup_changelist")

        busy = self._active_operation_message()
        if busy:
            messages.warning(request, busy)
            return redirect("admin:backup_backup_changelist")

        restore = Restore.objects.create(
            backup=backup,
            archive_filename=backup.filename,
            status=Restore.Status.QUEUED,
            requested_by=request.user if request.user.is_authenticated else None,
            requested_by_username=request.user.get_username() if request.user.is_authenticated else "",
            product_version=str(manifest_data.get("product_version", "") or ""),
            database_engine=str(manifest_data.get("database_engine", "") or ""),
            database_backup_format=str(manifest_data.get("database_backup_format", "") or ""),
            includes_media=bool(manifest_data.get("includes_media")),
        )

        for key in ("pending_import_backup_id", "pending_import_manifest", "pending_import_filename"):
            request.session.pop(key, None)
        request.session.modified = True

        run_restore.delay(restore.pk)
        messages.success(request, f"بازیابی از «{backup.filename}» در صف اجرا قرار گرفت.")
        return redirect("admin:backup_restore_changelist")

    def _render_import_confirm(self, request, backup, manifest):
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "backup": backup,
            "manifest": {
                "product_version": manifest.get("product_version"),
                "created_at": manifest.get("created_at"),
                "database_engine": manifest.get("database_engine"),
                "database_backup_format": manifest.get("database_backup_format"),
                "includes_media": manifest.get("includes_media"),
                "database_size": manifest.get("database_size"),
                "media_size": manifest.get("media_size"),
                "checksum": backup.checksum,
            },
            "title": f"بازیابی از فایل {backup.filename}",
        }
        return TemplateResponse(request, "admin/backup/backup/import_confirm.html", context)

    def delete_model(self, request, obj):
        if obj.storage_path:
            try:
                LocalBackupStorage().delete(obj.storage_path)
            except BackupStorageError as exc:
                logger.error("Refusing to remove file for backup #%s: %s", obj.pk, exc)
                raise
        super().delete_model(request, obj)


@admin.register(Restore, site=dolphin_admin_site)
class RestoreAdmin(ModelAdmin):
    admin_category = "system"
    admin_section = "backups"
    list_display = ("archive_filename", "status", "created_at", "requested_by_username")
    readonly_fields = (
        "backup", "archive_filename", "product_version", "database_engine",
        "database_backup_format", "includes_media", "status", "started_at",
        "completed_at", "requested_by", "requested_by_username",
        "pre_restore_backup", "pre_restore_backup_filename", "error_message",
        "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied
        extra_context = extra_context or {}
        extra_context.update({
            "opts": self.model._meta,
            "restores": list(Restore.objects.select_related("backup").order_by("-created_at")[:100]),
            "has_active_restore": Restore.objects.filter(status__in=(Restore.Status.QUEUED, Restore.Status.RESTORING)).exists(),
            "title": "بازیابی",
        })
        return TemplateResponse(request, "admin/backup/restore/change_list.html", {
            **self.admin_site.each_context(request), **extra_context,
        })