"""
Backup storage abstraction.
"""

import base64
import hashlib
import shutil
import uuid
from pathlib import Path

from django.conf import settings


class BackupStorageError(Exception):
    """Raised for unsafe or invalid storage operations."""


class BackupImportError(Exception):
    """Raised when an imported backup file fails validation or staging."""


def _credential_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise BackupStorageError("کتابخانه cryptography نصب نیست.") from exc
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    )
    return Fernet(key)


def encrypt_storage_secret(value):
    if not value:
        return ""
    return _credential_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_storage_secret(value):
    if not value:
        return ""
    try:
        return _credential_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise BackupStorageError(
            "رمز ذخیره‌شده مقصد شبکه قابل رمزگشایی نیست."
        ) from exc


class BackupStorage:
    IMPORT_STAGING_SUFFIX = ".importing"
    root = None

    def safe_stage_name(self, original_filename):
        raise NotImplementedError

    def finalize_import(self, staging_path, target_name):
        raise NotImplementedError

    def path_for(self, relpath):
        raise NotImplementedError

    def exists(self, path):
        raise NotImplementedError

    def open(self, relpath, mode="rb"):
        raise NotImplementedError

    def delete(self, relpath):
        raise NotImplementedError

    def finalize(self, tmp_absolute_path, filename):
        raise NotImplementedError


class LocalBackupStorage(BackupStorage):
    """Filesystem-backed storage rooted at settings.BACKUP_ROOT."""

    def __init__(self, root=None):
        self.root = Path(root or settings.BACKUP_ROOT).resolve()

    def ensure_root(self):
        self.root.mkdir(parents=True, exist_ok=True)

    def safe_stage_name(self, original_filename):
        if not original_filename:
            raise BackupStorageError("uploaded filename is empty")
        name = Path(original_filename).name
        if not name or name.startswith("."):
            raise BackupStorageError("unsafe uploaded filename")
        return f".{name}{self.IMPORT_STAGING_SUFFIX}"

    def finalize_import(self, staging_path, target_name):
        if not target_name or Path(target_name).is_absolute() or ".." in Path(target_name).parts:
            raise BackupStorageError(f"unsafe import target name: {target_name!r}")
        self.ensure_root()
        staging = Path(staging_path)
        if not staging.exists():
            raise BackupStorageError(f"staging file does not exist: {staging}")
        final_path = self.root / target_name
        if final_path.exists():
            suffix = Path(target_name).suffix
            base_name = Path(target_name).stem
            final_path = self.root / f"{base_name}_{uuid.uuid4().hex[:8]}{suffix}"
        staging.replace(final_path)
        return final_path

    def path_for(self, relpath):
        if not relpath:
            raise BackupStorageError("storage path is empty")
        candidate = Path(relpath)
        if candidate.is_absolute():
            raise BackupStorageError("absolute storage paths are not allowed")
        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise BackupStorageError(
                f"storage path resolves outside the backup root: {relpath!r}"
            )
        return resolved

    def exists(self, path):
        return Path(path).is_file()

    def open(self, relpath, mode="rb"):
        return open(self.path_for(relpath), mode)

    def delete(self, relpath):
        path = self.path_for(relpath)
        if path.exists():
            path.unlink()

    def finalize(self, tmp_absolute_path, filename):
        if not filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
            raise BackupStorageError(f"unsafe backup filename: {filename!r}")
        self.ensure_root()
        final_path = self.root / filename
        tmp_path = Path(tmp_absolute_path)
        if not tmp_path.exists():
            raise BackupStorageError(f"temporary archive does not exist: {tmp_path}")
        if final_path.exists():
            raise BackupStorageError(f"a backup file already exists: {filename!r}")
        tmp_path.replace(final_path)
        return final_path


class NetworkBackupStorage:
    """Transfer completed backup archives to an SMB or SFTP destination."""

    def __init__(self, destination):
        self.destination = destination

    @staticmethod
    def _safe_filename(filename):
        if (
            not filename
            or Path(filename).is_absolute()
            or ".." in Path(filename).parts
            or Path(filename).name != filename
        ):
            raise BackupStorageError(f"نام فایل شبکه ناامن است: {filename!r}")
        return filename

    def _remote_relative_path(self, filename):
        filename = self._safe_filename(filename)
        relative = (self.destination.remote_path or "").strip("/\\")
        return f"{relative}/{filename}" if relative else filename

    def _smb_path(self, filename):
        share = self.destination.share.strip("/\\")
        if not share:
            raise BackupStorageError("نام Share برای SMB تنظیم نشده است.")
        relative = self._remote_relative_path(filename).replace("/", "\\")
        return f"\\\\{self.destination.host}\\{share}\\{relative}"

    def copy_from_local(self, source_path, filename):
        backend = self.destination.backend_type
        if backend == self.destination.BackendType.SMB:
            return self._copy_smb(source_path, filename)
        if backend == self.destination.BackendType.SFTP:
            return self._copy_sftp(source_path, filename)
        if backend == self.destination.BackendType.MOUNTED_FOLDER:
            return self._copy_mounted(source_path, filename)
        raise BackupStorageError("نوع مقصد شبکه پشتیبانی نمی‌شود.")

    def _copy_mounted(self, source_path, filename):
        root = Path(self.destination.remote_path).resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = root / self._safe_filename(filename)
        temp = root / f".{target.name}.copying"
        shutil.copy2(source_path, temp)
        temp.replace(target)
        return str(target), target.stat().st_size

    def _copy_smb(self, source_path, filename):
        try:
            import smbclient
        except ImportError as exc:
            raise BackupStorageError(
                "کتابخانه SMB نصب نیست؛ وابستگی smbprotocol را نصب کنید."
            ) from exc

        try:
            smbclient.register_session(
                self.destination.host.strip(),
                username=self.destination.username,
                password=self.destination.get_password(),
                port=self.destination.port or 445,
            )
            remote = self._smb_path(filename)
            remote_dir = remote.rsplit("\\", 1)[0]
            smbclient.makedirs(remote_dir, exist_ok=True)
            temp = f"{remote}.copying"
            with open(source_path, "rb") as source, smbclient.open_file(
                temp, mode="wb"
            ) as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            try:
                smbclient.remove(remote)
            except OSError:
                pass
            smbclient.rename(temp, remote)
            return remote, smbclient.stat(remote).st_size
        except Exception as exc:
            raise BackupStorageError(
                f"انتقال فایل به مقصد SMB ناموفق بود: {exc}"
            ) from exc

    def _copy_sftp(self, source_path, filename):
        try:
            import paramiko
        except ImportError as exc:
            raise BackupStorageError(
                "کتابخانه SFTP نصب نیست؛ وابستگی paramiko را نصب کنید."
            ) from exc

        remote = "/" + self._remote_relative_path(filename)
        temp = f"{remote}.copying"
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(
                hostname=self.destination.host.strip(),
                port=self.destination.port or 22,
                username=self.destination.username,
                password=self.destination.get_password(),
                timeout=15,
                banner_timeout=15,
                auth_timeout=15,
            )
            sftp = client.open_sftp()
            try:
                self._sftp_mkdirs(sftp, remote.rsplit("/", 1)[0])
                sftp.put(str(source_path), temp)
                try:
                    sftp.remove(remote)
                except OSError:
                    pass
                sftp.rename(temp, remote)
                size = sftp.stat(remote).st_size
            finally:
                sftp.close()
            return remote, size
        except Exception as exc:
            raise BackupStorageError(
                f"انتقال فایل به مقصد SFTP ناموفق بود: {exc}"
            ) from exc
        finally:
            client.close()

    @staticmethod
    def _sftp_mkdirs(sftp, path):
        parts = [part for part in path.split("/") if part]
        current = ""
        for part in parts:
            current += "/" + part
            try:
                sftp.stat(current)
            except OSError:
                sftp.mkdir(current)

    def download_to_local(self, remote_path, local_path):
        if not remote_path:
            raise BackupStorageError("مسیر فایل شبکه خالی است.")
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            if self.destination.backend_type == self.destination.BackendType.SMB:
                import smbclient
                smbclient.register_session(
                    self.destination.host.strip(),
                    username=self.destination.username,
                    password=self.destination.get_password(),
                    port=self.destination.port or 445,
                )
                with smbclient.open_file(remote_path, mode="rb") as source, open(
                    destination, "wb"
                ) as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
            elif self.destination.backend_type == self.destination.BackendType.SFTP:
                import paramiko
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                client.connect(
                    hostname=self.destination.host.strip(),
                    port=self.destination.port or 22,
                    username=self.destination.username,
                    password=self.destination.get_password(),
                    timeout=15,
                    banner_timeout=15,
                    auth_timeout=15,
                )
                try:
                    sftp = client.open_sftp()
                    try:
                        sftp.get(remote_path, str(destination))
                    finally:
                        sftp.close()
                finally:
                    client.close()
            elif self.destination.backend_type == self.destination.BackendType.MOUNTED_FOLDER:
                shutil.copy2(remote_path, destination)
            else:
                raise BackupStorageError("نوع مقصد شبکه پشتیبانی نمی‌شود.")
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise BackupStorageError(
                f"دریافت فایل از مقصد شبکه ناموفق بود: {exc}"
            ) from exc

        return destination

    def delete(self, remote_path):
        if not remote_path:
            return
        backend = self.destination.backend_type
        try:
            if backend == self.destination.BackendType.SMB:
                import smbclient
                smbclient.register_session(
                    self.destination.host.strip(),
                    username=self.destination.username,
                    password=self.destination.get_password(),
                    port=self.destination.port or 445,
                )
                smbclient.remove(remote_path)
            elif backend == self.destination.BackendType.SFTP:
                import paramiko
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                client.connect(
                    hostname=self.destination.host.strip(),
                    port=self.destination.port or 22,
                    username=self.destination.username,
                    password=self.destination.get_password(),
                    timeout=15,
                    banner_timeout=15,
                    auth_timeout=15,
                )
                try:
                    sftp = client.open_sftp()
                    try:
                        sftp.remove(remote_path)
                    finally:
                        sftp.close()
                finally:
                    client.close()
            elif backend == self.destination.BackendType.MOUNTED_FOLDER:
                Path(remote_path).unlink(missing_ok=True)
        except FileNotFoundError:
            return
        except Exception as exc:
            raise BackupStorageError(
                f"حذف فایل از مقصد شبکه ناموفق بود: {exc}"
            ) from exc
