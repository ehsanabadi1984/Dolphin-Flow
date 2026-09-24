from django.db.models import Prefetch

from .form_file_models import FormFile
from .form_services import DynamicFormService
from .models import (
    DeviceIdentifier,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    InstanceDevice,
    WorkflowStepExecution,
)
from .history_models import HistoryConfiguration, HistoryField
from .history_browser_service import HistoryBrowserService
from .repeatable_row_read_services import RepeatableRowReadService
from .formula_bootstrap import _build_context_data
from .formula_services import FormulaService


class HistoryService:
    """
    Build and read immutable History snapshots for any FormDefinition.

    History is configuration-driven when an active HistoryConfiguration
    exists. Forms without an active configuration keep the legacy
    FormField.is_history_enabled behavior as a compatibility fallback.
    """

    SNAPSHOT_VERSION = 1

    @staticmethod
    def build_snapshot(*, instance, user=None):
        form = (
            FormDefinition.objects
            .filter(
                workflow=instance.workflow,
                is_active=True,
            )
            .first()
        )

        if form is None:
            return {
                "version": HistoryService.SNAPSHOT_VERSION,
                "configuration_id": None,
                "fields": [],
                "repeatable_groups": [],
            }

        form_data = (
            FormData.objects
            .filter(instance=instance)
            .first()
        )
        data = form_data.data if form_data and form_data.data else {}

        configuration, _ = HistoryConfiguration.objects.get_or_create(
            form=form,
            defaults={
                "name": f"History - {form.name}",
                "is_active": True,
            },
        )

        if not configuration.is_active:
            return {
                "version": HistoryService.SNAPSHOT_VERSION,
                "configuration_id": configuration.pk,
                "fields": [],
                "repeatable_groups": [],
            }

        configured_fields = list(
            HistoryField.objects
            .filter(
                configuration=configuration,
                is_enabled=True,
                form_field__is_active=True,
                form_field__section__is_active=True,
                form_field__section__form=form,
            )
            .select_related(
                "form_field",
                "form_field__section",
                "form_field__repeatable_group",
                "form_field__repeatable_group__section",
            )
            .order_by("display_order", "id")
        )

        selected = [
            {
                "form_field": item.form_field,
                "display_label": item.display_label or item.form_field.label,
                "display_order": item.display_order,
                "history_field_id": item.pk,
            }
            for item in configured_fields
            if not item.form_field.repeatable_group_id
            or item.form_field.repeatable_group.is_active
        ]

        top_level = []
        groups = {}

        for item in selected:
            field = item["form_field"]
            if field.repeatable_group_id:
                group = field.repeatable_group
                bucket = groups.setdefault(
                    group.pk,
                    {
                        "group": group,
                        "display_order": item["display_order"],
                        "fields": [],
                    },
                )
                bucket["fields"].append(item)
            else:
                top_level.append(item)

        formula_data = None
        if any(
            FormulaService.is_formula(item["form_field"])
            for item in top_level
        ):
            formula_data = FormulaService.calculate_context_data(
                form=form,
                data=_build_context_data(
                    instance=instance,
                    submitted_data=None,
                ),
            )

        history_fields = []
        for item in sorted(
            top_level,
            key=lambda value: (value["display_order"], value["form_field"].pk),
        ):
            field = item["form_field"]
            if FormulaService.is_formula(field):
                value = (formula_data or {}).get(field.code, "")
            else:
                value = data.get(field.code, "")
            history_fields.append(
                HistoryService._serialize_field(
                    field=field,
                    value=value,
                    display_label=item["display_label"],
                    display_order=item["display_order"],
                    history_field_id=item["history_field_id"],
                )
            )

        def build_history_group(group, parent_row=None):
            bucket = groups.get(group.pk)
            if bucket is None:
                return None

            fields = sorted(
                bucket["fields"],
                key=lambda value: (
                    value["display_order"],
                    value["form_field"].pk,
                ),
            )

            if group.group_type == FormRepeatableGroup.GroupType.DEVICE:
                items = HistoryService._build_device_items(
                    instance=instance,
                    fields=fields,
                )
            else:
                items = HistoryService._build_normal_items(
                    instance=instance,
                    group=group,
                    fields=fields,
                    parent_row=parent_row,
                )

            child_buckets = [
                child
                for child in groups.values()
                if child["group"].parent_group_id == group.pk
            ]

            if child_buckets:
                for item in items:
                    row_id = item.get("row_id")
                    if row_id is None:
                        continue

                    row = next(
                        (
                            candidate
                            for candidate in RepeatableRowReadService.get_rows(
                                instance=instance,
                                group=group,
                                parent_row=parent_row,
                            )
                            if candidate.pk == row_id
                        ),
                        None,
                    )
                    if row is None:
                        continue

                    child_groups = []
                    for child_bucket in sorted(
                        child_buckets,
                        key=lambda value: (
                            value["display_order"],
                            value["group"].pk,
                        ),
                    ):
                        child_group = build_history_group(
                            child_bucket["group"],
                            parent_row=row,
                        )
                        if child_group is not None:
                            child_groups.append(child_group)

                    if child_groups:
                        item["child_groups"] = child_groups

            if not items:
                return None

            return {
                "code": group.code,
                "name": group.name,
                "group_type": group.group_type,
                "display_order": bucket["display_order"],
                "items": items,
            }

        history_groups = []
        root_buckets = [
            bucket
            for bucket in groups.values()
            if bucket["group"].parent_group_id is None
        ]
        for bucket in sorted(
            root_buckets,
            key=lambda value: (
                value["display_order"],
                value["group"].pk,
            ),
        ):
            history_group = build_history_group(bucket["group"])
            if history_group is not None:
                history_groups.append(history_group)

        return {
            "version": HistoryService.SNAPSHOT_VERSION,
            "configuration_id": configuration.pk,
            "fields": history_fields,
            "repeatable_groups": history_groups,
        }

    @staticmethod
    def _serialize_field(
        *,
        field,
        value,
        display_label,
        display_order,
        history_field_id,
    ):
        return {
            "code": field.code,
            "label": field.label,
            "display_label": display_label,
            "display_order": display_order,
            "field_type": field.field_type,
            "value": value,
            "display_value": DynamicFormService._get_display_value(
                field=field,
                value=value,
            ),
            "history_field_id": history_field_id,
        }

    @staticmethod
    def _build_normal_items(*, instance, group, fields, parent_row=None):
        if not fields:
            return []

        field_by_code = {
            item["form_field"].code: item
            for item in fields
        }

        items = []

        if parent_row is not None:
            rows = RepeatableRowReadService.get_rows(
                instance=instance,
                group=group,
                parent_row=parent_row,
            )
        else:
            rows = RepeatableRowReadService.get_rows(
                instance=instance,
                group=group,
            )

        for row in rows:
            reconstructed = RepeatableRowReadService.reconstruct_row(
                row=row,
            )
            reconstructed_fields = {
                field["code"]: field
                for field in reconstructed["fields"]
            }

            item_fields = []
            for code, config in field_by_code.items():
                field = config["form_field"]
                value_data = reconstructed_fields.get(code)
                if value_data is None:
                    continue

                serialized = HistoryService._serialize_field(
                    field=field,
                    value=value_data["value"],
                    display_label=config["display_label"],
                    display_order=config["display_order"],
                    history_field_id=config["history_field_id"],
                )
                serialized["display_value"] = value_data["display_value"]

                if field.field_type == FormField.FieldType.FILE:
                    form_file = (
                        FormFile.objects
                        .filter(
                            form_data__instance=instance,
                            field=field,
                            row_id=str(row.pk),
                        )
                        .first()
                    )
                    if form_file is not None:
                        serialized["file"] = {
                            "name": form_file.original_name,
                            "size": form_file.file_size,
                            "content_type": form_file.content_type,
                        }

                item_fields.append(serialized)

            if item_fields:
                items.append(
                    {
                        "row_id": row.pk,
                        "fields": item_fields,
                    }
                )

        return items

    @staticmethod
    def _build_device_items(*, instance, fields):
        instance_devices = (
            InstanceDevice.objects
            .filter(instance=instance, is_active=True)
            .select_related(
                "device",
                "device__device_model",
                "device__device_model__device_type",
                "draft_device_model",
                "draft_device_model__device_type",
                "draft_device_type",
            )
            .prefetch_related(
                Prefetch(
                    "device__identifiers",
                    queryset=DeviceIdentifier.objects.filter(
                        identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                    ),
                    to_attr="history_imei_identifiers",
                )
            )
        )

        items = []
        for instance_device in instance_devices:
            item_fields = []

            for item in fields:
                field = item["form_field"]
                value = ""
                display_value = ""
                system_key = field.system_key

                if system_key == FormField.SystemKey.IMEI:
                    if instance_device.device:
                        identifiers = getattr(
                            instance_device.device,
                            "history_imei_identifiers",
                            [],
                        )
                        identifier = identifiers[0] if identifiers else None
                        value = identifier.value if identifier else ""
                    else:
                        value = instance_device.draft_imei
                    display_value = str(value)

                elif system_key == FormField.SystemKey.DEVICE_TYPE:
                    if instance_device.device:
                        device_type = (
                            instance_device.device.device_model.device_type
                        )
                    else:
                        device_type = (
                            instance_device.draft_device_model.device_type
                            if instance_device.draft_device_model
                            else instance_device.draft_device_type
                        )
                    if device_type:
                        value = device_type.pk
                        display_value = device_type.name

                elif system_key == FormField.SystemKey.DEVICE_MODEL:
                    device_model = (
                        instance_device.device.device_model
                        if instance_device.device
                        else instance_device.draft_device_model
                    )
                    if device_model:
                        value = device_model.pk
                        display_value = str(device_model)

                elif system_key == FormField.SystemKey.REPORTED_PROBLEM:
                    value = instance_device.reported_problem
                    display_value = str(value)

                elif system_key == FormField.SystemKey.DESCRIPTION:
                    value = instance_device.description
                    display_value = str(value)

                elif system_key == FormField.SystemKey.WARRANTY_STATUS:
                    value = instance_device.warranty_status
                    display_value = DynamicFormService._get_display_value(
                        field=field,
                        value=value,
                    )

                elif system_key == FormField.SystemKey.STATUS:
                    value = instance_device.status
                    display_value = DynamicFormService._get_display_value(
                        field=field,
                        value=value,
                    )

                else:
                    continue

                item_fields.append(
                    HistoryService._serialize_field(
                        field=field,
                        value=value,
                        display_label=item["display_label"],
                        display_order=item["display_order"],
                        history_field_id=item["history_field_id"],
                    )
                )
                item_fields[-1]["display_value"] = display_value

            if item_fields:
                items.append(
                    {
                        "device_id": instance_device.device_id,
                        "instance_device_id": instance_device.pk,
                        "fields": item_fields,
                    }
                )

        return items

    @staticmethod
    def get_device_history(*, device_id, user):
        """Return authorized History snapshots for a device."""
        return HistoryBrowserService.get_history(
            user=user,
            device_id=device_id,
        )
