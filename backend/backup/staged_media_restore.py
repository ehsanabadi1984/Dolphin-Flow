"""Prepare restored media in an isolated sibling directory.

This module intentionally does not replace MEDIA_ROOT. Cutover and rollback
remain a separate, explicitly orchestrated operation.
"""

import logging
import secrets
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from django.conf import settings

from .restore_services import RestoreError, _assert_safe_member

logger = logging.getLogger(__name__)


class StagedMediaRestore:
    """Extract and validate media without modifying the live MEDIA_ROOT."""

    def __init__(self, restore_id, media_root=None):
        self.restore_id = int(restore_id)
        self.media_root = Path(media_root or settings.MEDIA_ROOT).absolute()
        self.stage_dir = None
        self._prepared = False
        self.file_count = 0
        self.total_bytes = 0

    def _create_stage_directory(self):
        root = self.media_root
        parent = root.parent

        if root.is_symlink():
            raise RestoreError("مسیر MEDIA_ROOT نمی‌تواند پیوند نمادین باشد.")
        if not parent.exists() or not parent.is_dir():
            raise RestoreError("پوشه والد MEDIA_ROOT در دسترس نیست.")
        if root.exists() and not root.is_dir():
            raise RestoreError("MEDIA_ROOT یک پوشه معتبر نیست.")

        token = secrets.token_hex(8)
        stage = parent / f".{root.name}.restore-{self.restore_id}-{token}"
        stage.mkdir(mode=0o700)
        if stage.stat().st_dev != parent.stat().st_dev:
            shutil.rmtree(stage, ignore_errors=True)
            raise RestoreError("پوشه staging رسانه روی فایل‌سیستم مناسبی ساخته نشد.")

        self.stage_dir = stage
        return stage

    @staticmethod
    def _normalized_member_name(member):
        name = member.name
        if not name or "\\\\" in name or "\\x00" in name:
            raise RestoreError("نام فایل نامعتبر در بایگانی رسانه یافت شد.")

        path = PurePosixPath(name)
        if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
            raise RestoreError(f"مسیر ناامن در بایگانی رسانه یافت شد: {name!r}")

        return path

    def prepare(self, media_archive_path):
        """Extract regular files into a new sibling staging directory."""
        if self.stage_dir is not None:
            raise RestoreError("این سرویس قبلاً برای آماده‌سازی رسانه استفاده شده است.")

        archive_path = Path(media_archive_path)
        if not archive_path.is_file() or archive_path.stat().st_size == 0:
            raise RestoreError("فایل آرشیو رسانه یافت نشد یا خالی است.")

        stage = self._create_stage_directory()
        seen = set()
        file_paths = set()
        directory_paths = set()

        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                members = archive.getmembers()
                for member in members:
                    _assert_safe_member(member)
                    relative = self._normalized_member_name(member)
                    key = relative.as_posix()
                    if key in seen:
                        raise RestoreError(f"مسیر تکراری در آرشیو رسانه یافت شد: {key}")
                    seen.add(key)

                    if member.isfile():
                        file_paths.add(key)
                        if member.size < 0:
                            raise RestoreError("اندازه فایل در آرشیو رسانه نامعتبر است.")
                        self.total_bytes += member.size
                    else:
                        directory_paths.add(key)

                for file_name in file_paths:
                    parts = PurePosixPath(file_name).parts
                    for index in range(1, len(parts)):
                        parent_name = PurePosixPath(*parts[:index]).as_posix()
                        if parent_name in file_paths:
                            raise RestoreError("ساختار مسیرهای آرشیو رسانه با هم تداخل دارد.")

                if file_paths & directory_paths:
                    raise RestoreError("یک مسیر در آرشیو هم‌زمان فایل و پوشه است.")

                free_bytes = shutil.disk_usage(stage).free
                if self.total_bytes > free_bytes:
                    raise RestoreError("فضای آزاد دیسک برای آماده‌سازی رسانه کافی نیست.")

                for member in members:
                    relative = self._normalized_member_name(member)
                    destination = stage.joinpath(*relative.parts)

                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue

                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise RestoreError(f"خواندن فایل رسانه ناموفق بود: {member.name}")
                    with source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    self.file_count += 1

            actual_count = sum(1 for item in stage.rglob("*") if item.is_file())
            actual_bytes = sum(item.stat().st_size for item in stage.rglob("*") if item.is_file())
            if actual_count != self.file_count or actual_bytes != self.total_bytes:
                raise RestoreError("اعتبارسنجی فایل‌های استخراج‌شده رسانه ناموفق بود.")

            self._prepared = True
            logger.info(
                "Restore #%s: staged %s media file(s), %s byte(s) at %s",
                self.restore_id, self.file_count, self.total_bytes, self.stage_dir,
            )
            return self.stage_dir

        except (tarfile.TarError, OSError) as exc:
            self.cleanup()
            raise RestoreError("آماده‌سازی آرشیو رسانه ناموفق بود: " + str(exc)) from exc
        except Exception:
            self.cleanup()
            raise

    def cleanup(self):
        """Remove only this instance's staging directory."""
        if self.stage_dir is not None:
            shutil.rmtree(self.stage_dir, ignore_errors=True)
            self.stage_dir = None
        self._prepared = False
