from django.db.models import Prefetch

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

        history_fields = []
        for item in sorted(
            top_level,
            key=lambda value: (value["display_order"], value["form_field"].pk),
        ):
            field = item["form_field"]
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

        history_groups = []
        for bucket in sorted(
            groups.values(),
            key=lambda value: (
                value["display_order"],
                value["group"].pk,
            ),
        ):
            group = bucket["group"]
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
                    data=data,
                    fields=fields,
                )

            if items:
                history_groups.append(
                    {
                        "code": group.code,
                        "name": group.name,
                        "group_type": group.group_type,
                        "display_order": bucket["display_order"],
                        "items": items,
                    }
                )

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
    def _build_normal_items(*, data, fields):
        if not fields:
            return []

        group = fields[0]["form_field"].repeatable_group
        raw_items = data.get(group.code, [])
        if not isinstance(raw_items, list):
            return []

        items = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue

            item_fields = []
            for item in fields:
                field = item["form_field"]
                value = raw_item.get(field.code, "")
                item_fields.append(
                    HistoryService._serialize_field(
                        field=field,
                        value=value,
                        display_label=item["display_label"],
                        display_order=item["display_order"],
                        history_field_id=item["history_field_id"],
                    )
                )

            if item_fields:
                items.append(
                    {
                        "row_id": raw_item.get("_id"),
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
        instance_devices = (
            InstanceDevice.objects
            .filter(
                device_id=device_id,
                instance__workflow__memberships__user=user,
                instance__workflow__memberships__is_active=True,
            )
            .values_list("instance_id", flat=True)
            .distinct()
        )

        executions = (
            WorkflowStepExecution.objects
            .filter(
                instance_id__in=instance_devices,
                is_submitted=True,
            )
            .select_related(
                "instance",
                "instance__workflow",
                "workflow_step",
            )
            .order_by("-submitted_at", "-pk")
        )

        history = []
        for execution in executions:
            snapshot = execution.data.get("history") if execution.data else None
            if not isinstance(snapshot, dict):
                continue

            matched_groups = []
            for group in snapshot.get("repeatable_groups", []):
                if not isinstance(group, dict):
                    continue
                matched_items = [
                    item
                    for item in group.get("items", [])
                    if item.get("device_id") == device_id
                ]
                if matched_items:
                    matched_groups.append(
                        {
                            **group,
                            "items": matched_items,
                        }
                    )

            if matched_groups or snapshot.get("fields"):
                history.append(
                    {
                        "execution": execution,
                        "snapshot": {
                            **snapshot,
                            "repeatable_groups": matched_groups,
                        },
                    }
                )

        return history
