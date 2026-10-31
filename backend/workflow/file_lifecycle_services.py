"""Centralized lifecycle management for workflow form-file storage objects.

The database stores references to the original storage object. This service
never copies file bytes and only deletes an object after checking all live
form and internal-sharing references.
"""

from django.db import transaction

from .form_file_models import FormFile, SharedFileAsset
from .models import FileShareMessage


ACTIVE_SHARE_STATUSES = (
    FileShareMessage.Status.PENDING,
    FileShareMessage.Status.READ,
    FileShareMessage.Status.RESPONDED,
    FileShareMessage.Status.COMPLETED,
)


class FileLifecycleService:
    @staticmethod
    @transaction.atomic
    def get_or_create_asset(form_file):
        """Return the single Asset for this already-stored physical object."""
        if not form_file or not form_file.pk or not form_file.file or not form_file.file.name:
            raise ValueError("A saved FormFile with a stored file is required.")

        locked_file = (
            FormFile.objects.select_for_update()
            .select_related("field")
            .get(pk=form_file.pk)
        )
        return SharedFileAsset.get_or_create_for_form_file(locked_file)

    @staticmethod
    @transaction.atomic
    def detach_asset_source(form_file):
        """Keep Asset snapshots independent from a mutable FormFile row."""
        if not form_file or not form_file.pk or not form_file.file or not form_file.file.name:
            return 0

        assets = list(
            SharedFileAsset.objects.select_for_update().filter(
                form_file_id=form_file.pk,
                storage_backend="default",
                storage_name=form_file.file.name,
            )
        )
        if not assets:
            return 0
        return SharedFileAsset.objects.filter(
            pk__in=[asset.pk for asset in assets]
        ).update(form_file=None)

    @classmethod
    @transaction.atomic
    def delete_form_file(cls, form_file):
        """Remove a FormFile row and schedule safe physical cleanup after commit."""
        if form_file is None or form_file.pk is None:
            return (0, {})
        locked_file = (
            FormFile.objects.select_for_update()
            .select_related("field")
            .filter(pk=form_file.pk)
            .first()
        )
        if locked_file is None:
            return (0, {})
        file_name = locked_file.file.name if locked_file.file else ""
        storage = locked_file.file.storage if locked_file.file else None
        delete_result = locked_file.delete()
        if file_name and storage:
            cls.schedule_storage_delete(
                storage=storage,
                file_name=file_name,
                storage_backend="default",
            )
        return delete_result

    @classmethod
    def schedule_storage_delete(cls, *, storage, file_name, storage_backend="default"):
        if not storage or not file_name:
            return
        transaction.on_commit(
            lambda storage=storage, file_name=file_name, storage_backend=storage_backend:
                cls._delete_if_unreferenced(
                    storage=storage,
                    file_name=file_name,
                    storage_backend=storage_backend,
                )
        )

    @classmethod
    def schedule_asset_cleanup(cls, asset_id):
        asset = SharedFileAsset.objects.filter(pk=asset_id).first()
        if asset is None:
            return
        storage = FormFile._meta.get_field("file").storage
        cls.schedule_storage_delete(
            storage=storage,
            file_name=asset.storage_name,
            storage_backend=asset.storage_backend,
        )

    @staticmethod
    def _delete_if_unreferenced(*, storage, file_name, storage_backend):
        """Recheck references under row locks immediately before deleting bytes."""
        with transaction.atomic():
            assets = list(
                SharedFileAsset.objects.select_for_update()
                .filter(
                    storage_backend=storage_backend,
                    storage_name=file_name,
                )
                .order_by("pk")
            )
            if FormFile.objects.filter(file=file_name).exists():
                return False

            asset_ids = [asset.pk for asset in assets]
            if asset_ids and FileShareMessage.objects.filter(
                asset_id__in=asset_ids,
                status__in=ACTIVE_SHARE_STATUSES,
            ).exists():
                return False

            storage.delete(file_name)
            return True
