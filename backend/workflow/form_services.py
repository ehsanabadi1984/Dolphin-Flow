from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .sla_services import SLAService

from .instance_device_services import InstanceDeviceService
from .device_services import DeviceService
from .models import (
    DeviceModel,
    FormData,
    WorkflowInstance,
    FormDefinition,
    LookupItem,
    StaticChoiceItem,
    InstanceDevice,
    DeviceIdentifier,
    WorkflowStepExecution,
    FormRepeatableGroup,
    DeviceType,
    RepeatableGroupAccess,
    FormField,

    
)

class DynamicFormService:
    """
    Build and persist the dynamic form structure
    for a specific workflow instance and step.
    """

    @staticmethod
    def _parse_repeatable_data(
        *,
        submitted_data,
        group_code,
    ):
        """
        Convert flat POST keys of a repeatable group into
        a list of dictionaries.
        """
        if submitted_data is None:
            return []

        prefix = f"{group_code}_"
        items = {}

        for key in submitted_data.keys():

            if not key.startswith(prefix):
                continue

            remainder = key[len(prefix):]

            parts = remainder.split("_", 1)

            if len(parts) != 2:
                continue

            index, field_code = parts

            if not index.isdigit():
                continue

            index = int(index)

            items.setdefault(
                index,
                {},
            )

            values = submitted_data.getlist(key)

            if len(values) > 1:
                items[index][field_code] = values
            else:
                items[index][field_code] = (
                    values[0]
                    if values
                    else ""
                )

        return [
            items[index]
            for index in sorted(items)
        ]

     
    @staticmethod
    def _build_history_snapshot(
        *,
        instance,
        user,
    ):
        """
        Build an immutable snapshot of all form fields that are
        configured to appear in workflow history.

        The snapshot is built at step submission time.
        """

        workflow = instance.workflow
        step = instance.current_step

        form = (
            FormDefinition.objects
            .filter(
                workflow=workflow,
                is_active=True,
            )
            .prefetch_related(
                "sections__fields",
                "sections__repeatable_groups__fields",
            )
            .first()
        )

        if form is None:
            return {
                "fields": [],
                "repeatable_groups": [],
            }

        form_data = (
            FormData.objects
            .filter(instance=instance)
            .first()
        )

        data = (
            form_data.data
            if form_data and form_data.data
            else {}
        )

        history_fields = []
        history_groups = []

        # -------------------------------------------------
        # Normal fields
        # -------------------------------------------------

        for section in form.sections.filter(
            is_active=True,
        ):
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
                is_history_enabled=True,
            ):
                value = data.get(
                    field.code,
                    "",
                )

                history_fields.append(
                    DynamicFormService._serialize_history_field(
                        field=field,
                        value=value,
                    )
                )

            # -------------------------------------------------
            # Repeatable groups
            # -------------------------------------------------

            for group in section.repeatable_groups.filter(
                is_active=True,
            ):
                group_fields = list(
                    group.fields.filter(
                        is_active=True,
                        is_history_enabled=True,
                    )
                )

                if not group_fields:
                    continue

                # ---------------------------------------------
                # Device group
                # ---------------------------------------------

                if (
                    group.group_type
                    == FormRepeatableGroup.GroupType.DEVICE
                ):
                    group_snapshot = (
                        DynamicFormService
                        ._build_device_history_group(
                            instance=instance,
                            group=group,
                            fields=group_fields,
                        )
                    )

                # ---------------------------------------------
                # Normal repeatable group
                # ---------------------------------------------

                else:
                    group_snapshot = (
                        DynamicFormService
                        ._build_normal_history_group(
                            data=data,
                            group=group,
                            fields=group_fields,
                        )
                    )

                if group_snapshot["items"]:
                    history_groups.append(
                        group_snapshot
                    )

        return {
            "fields": history_fields,
            "repeatable_groups": history_groups,
        }

    @staticmethod
    def _serialize_history_field(
        *,
        field,
        value,
    ):
        """
        Serialize one form field into an immutable history snapshot.
        """

        display_value = (
            DynamicFormService._get_history_display_value(
                field=field,
                value=value,
            )
        )

        return {
            "code": field.code,
            "label": field.label,
            "field_type": field.field_type,
            "value": value,
            "display_value": display_value,
        }

    @staticmethod
    def _get_history_display_value(
        *,
        field,
        value,
    ):
        """
        Resolve the human-readable representation of a field value.
        """

        if value in ("", None):
            return ""

        if isinstance(value, list):
            return [
                DynamicFormService._get_history_display_value(
                    field=field,
                    value=item,
                )
                for item in value
            ]

        if field.field_type != FormField.FieldType.SELECT:
            return str(value)

        choices = DynamicFormService._get_field_choices(
            field
        )

        value_string = str(value)

        for choice in choices:
            if str(choice["value"]) == value_string:
                return choice["label"]

        return str(value)

    @staticmethod
    def _build_normal_history_group(
        *,
        data,
        group,
        fields,
    ):
        raw_items = data.get(
            group.code,
            [],
        )

        if not isinstance(raw_items, list):
            raw_items = []

        items = []

        for raw_item in raw_items:

            if not isinstance(raw_item, dict):
                continue

            item_fields = []

            for field in fields:

                value = raw_item.get(
                    field.code,
                    "",
                )

                item_fields.append(
                    DynamicFormService._serialize_history_field(
                        field=field,
                        value=value,
                    )
                )

            if item_fields:
                items.append(
                    {
                        "fields": item_fields,
                    }
                )

        return {
            "code": group.code,
            "name": group.name,
            "items": items,
        }

    @staticmethod
    def _build_device_history_group(
        *,
        instance,
        group,
        fields,
    ):
        instance_devices = (
            InstanceDeviceService.get_devices_for_instance(
                instance=instance,
            )
        )

        items = []

        for instance_device in instance_devices:

            item_fields = []

            for field in fields:

                value = ""
                display_value = ""

                system_key = field.system_key

                if system_key == FormField.SystemKey.IMEI:

                    if instance_device.device:
                        identifier = (
                            instance_device.device.identifiers
                            .filter(
                                identifier_type=(
                                    DeviceIdentifier.IdentifierType.IMEI
                                )
                            )
                            .first()
                        )

                        value = (
                            identifier.value
                            if identifier
                            else ""
                        )

                    else:
                        value = (
                            instance_device.draft_imei
                        )

                    display_value = str(value)

                elif (
                    system_key
                    == FormField.SystemKey.DEVICE_TYPE
                ):

                    if instance_device.device:
                        device_type = (
                            instance_device
                            .device
                            .device_model
                            .device_type
                        )

                    else:
                        device_type = (
                            instance_device
                            .draft_device_model
                            .device_type
                            if instance_device.draft_device_model
                            else None
                        )

                    if device_type:
                        value = device_type.pk
                        display_value = device_type.name

                elif (
                    system_key
                    == FormField.SystemKey.DEVICE_MODEL
                ):

                    if instance_device.device:
                        device_model = (
                            instance_device
                            .device
                            .device_model
                        )

                    else:
                        device_model = (
                            instance_device.draft_device_model
                        )

                    if device_model:
                        value = device_model.pk
                        display_value = str(device_model)

                elif (
                    system_key
                    == FormField.SystemKey.REPORTED_PROBLEM
                ):
                    value = instance_device.reported_problem
                    display_value = str(value)

                elif (
                    system_key
                    == FormField.SystemKey.DESCRIPTION
                ):
                    value = instance_device.description
                    display_value = str(value)

                elif (
                    system_key
                    == FormField.SystemKey.WARRANTY_STATUS
                ):
                    value = instance_device.warranty_status
                    display_value = str(value)

                elif (
                    system_key
                    == FormField.SystemKey.STATUS
                ):
                    value = instance_device.status
                    display_value = str(value)

                else:
                    # Device fields with no system mapping are
                    # not currently stored in InstanceDevice.
                    continue

                item_fields.append(
                    {
                        "code": field.code,
                        "label": field.label,
                        "field_type": field.field_type,
                        "value": value,
                        "display_value": display_value,
                    }
                )

            if item_fields:
                items.append(
                    {
                        "fields": item_fields,
                    }
                )

        return {
            "code": group.code,
            "name": group.name,
            "items": items,
        }

    @staticmethod
    @transaction.atomic
    def submit_form_for_step(
        *,
        instance,
        user,
    ):
        workflow = instance.workflow
        step = instance.current_step

        if step is None:
            raise ValidationError(
                "این Workflow مرحله فعلی ندارد."
            )

        current_step_execution = (
            instance.step_executions
            .select_for_update()
            .filter(
                workflow_step=step,
            )
            .order_by("-performed_at")
            .first()
        )
        
        if current_step_execution is None:
            raise ValidationError(
                "اجرای مرحله فعلی این Workflow پیدا نشد."
            )

        if current_step_execution.is_submitted:
            raise ValidationError(
                "فرم این مرحله قبلاً ارسال شده است."
            )

        form_data = (
            FormData.objects
            .filter(instance=instance)
            .first()
        )

        if form_data is None:
            raise ValidationError(
                "اطلاعات فرم هنوز ذخیره نشده است."
            )

        if not form_data.data:
            raise ValidationError(
                "ابتدا اطلاعات فرم را ذخیره کنید."
            )

        # -------------------------------------------------
        # Build immutable history snapshot
        # BEFORE locking the step
        # -------------------------------------------------

        history_snapshot = (
            DynamicFormService._build_history_snapshot(
                instance=instance,
                user=user,
            )
        )

        now = timezone.now()

        current_step_execution.is_submitted = True
        current_step_execution.submitted_at = now
        current_step_execution.is_submitted = True
        current_step_execution.submitted_at = now
        current_step_execution.data = {
            "history": history_snapshot,
        }

        current_step_execution.save(
            update_fields=[
                "is_submitted",
                "submitted_at",
                "data",
            ]
        )
        form_data.is_submitted = True
        form_data.submitted_at = now
        form_data.submitted_by = user
        form_data.save(
            update_fields=[
                "is_submitted",
                "submitted_at",
                "submitted_by",
            ]
        )

        # -------------------------------------------------
        # Complete workflow if this is the final step
        # -------------------------------------------------

        has_next_step = workflow.steps.filter(
            is_active=True,
            order__gt=step.order,
        ).exists()

        if not has_next_step:
            instance.status = WorkflowInstance.Status.COMPLETED
            instance.completed_at = now

            instance.save(
                update_fields=[
                    "status",
                    "completed_at",
                ]
            )

        return current_step_execution

    @staticmethod
    def _get_field_choices(field):
        """
        Build choices for a SELECT FormField based on its choice source.
        Returns a list of dictionaries:
        {
            "value": "...",
            "label": "...",
        }
        """

        if field.field_type != field.FieldType.SELECT:
            return []

        # --------------------------------------------------
        # STATIC
        # --------------------------------------------------

        if field.choice_source == field.ChoiceSource.STATIC:
            if not field.choice_static_set_id:
                return []

            return [
                {
                    "value": item.value,
                    "label": item.label,
                }
                for item in (
                    StaticChoiceItem.objects
                    .filter(
                        choice_set_id=field.choice_static_set_id,
                        is_active=True,
                    )
                    .order_by("order", "id")
                )
            ]

        # --------------------------------------------------
        # LOOKUP
        # --------------------------------------------------

        if field.choice_source == field.ChoiceSource.LOOKUP:
            if not field.choice_lookup_list_id:
                return []

            return [
                {
                    "value": item.value,
                    "label": item.label,
                }
                for item in (
                    LookupItem.objects
                    .filter(
                        lookup_list_id=field.choice_lookup_list_id,
                        is_active=True,
                    )
                    .order_by("order", "id")
                )
            ]

        # --------------------------------------------------
        # MODEL
        # --------------------------------------------------

        if field.choice_source == field.ChoiceSource.MODEL:

            if not field.choice_model_id:
                return []

            model_class = field.choice_model.model_class()

            if not model_class:
                return []

            queryset = model_class.objects.all()

            choices = []

            for obj in queryset:
                value = getattr(
                    obj,
                    field.choice_value_field,
                    "",
                )

                label = getattr(
                    obj,
                    field.choice_label_field,
                    "",
                )

                choices.append(
                    {
                        "value": str(value),
                        "label": str(label),
                    }
                )

            return choices

        return []

    @staticmethod
    def get_form_for_step(
        *,
        instance,
        user,
        submitted_data=None,
        edit_mode=False,
    ):
        workflow = instance.workflow
        step = instance.current_step

        if step is None:
            return None
        
        current_step_execution = (
            instance.step_executions
            .filter(
                workflow_step=step,
            )
            .order_by("-performed_at")
            .first()
        )

        step_is_submitted = (
            current_step_execution is not None
            and current_step_execution.is_submitted
        )

        form = (
            FormDefinition.objects.filter(
                workflow=workflow,
                is_active=True,
            )
            .prefetch_related(
                "sections__fields__access_rules",
                "sections__repeatable_groups__fields__access_rules",
            )
            .first()
        )

        if form is None:
            return None

        form_data = FormData.objects.filter(
            instance=instance,
        ).first()

        data = form_data.data if form_data else {}

        current_step_execution = (
            instance.step_executions
            .filter(
                workflow_step=step,
            )
            .order_by("-performed_at")
            .first()
        )

        is_submitted = (
            current_step_execution.is_submitted
            if current_step_execution
            else False
        )

        has_saved_device_data = (
            InstanceDevice.objects
            .filter(
                instance=instance,
                is_active=True,
            )
            .exists()
        )

        has_saved_data = (
            bool(data)
            or has_saved_device_data
        )
        roles = set(
            workflow.memberships.filter(
                user=user,
                is_active=True,
            ).values_list(
                "role",
                flat=True,
            )
        )

        sections = []

        for section in form.sections.filter(
            is_active=True,
        ):
            fields = []

            # -------------------------------------------------
            # Normal fields
            # -------------------------------------------------

            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            ):
                access_rules = field.access_rules.filter(
                    step=step,
                )

                can_view = False
                can_edit = False

                user_rule = access_rules.filter(
                    user=user,
                ).first()

                if user_rule:
                    can_view = user_rule.can_view
                    permission_can_edit = user_rule.can_edit

                else:
                    role_rules = access_rules.filter(
                        role__in=roles,
                        user__isnull=True,
                    )

                    can_view = role_rules.filter(
                        can_view=True,
                    ).exists()

                    permission_can_edit = role_rules.filter(
                        can_edit=True,
                    ).exists()

                if not can_view:
                    continue

                can_edit = (
                    permission_can_edit
                    and edit_mode
                    and not is_submitted
                )

                choices = (
                    DynamicFormService._get_field_choices(field)
                    if field.field_type == field.FieldType.SELECT
                    else []
                )

                fields.append(
                    {
                        "field": field,
                        "can_edit": can_edit,
                        "value": data.get(
                            field.code,
                            "",
                        ),
                        "choices": choices,
                    }
                )

            # -------------------------------------------------
            # Repeatable groups
            # -------------------------------------------------

            repeatable_groups = []

            for group in section.repeatable_groups.filter(
                is_active=True,
            ):



                # -------------------------------------------------
                # Repeatable Group Access
                # -------------------------------------------------

                group_access_rules = group.access_rules.filter(
                    group=group,
                    step=step,
                )

                group_can_view = False
                group_can_edit = False
                group_can_add = False

                user_rule = group_access_rules.filter(
                    user=user,
                ).first()

                if user_rule:
                    group_can_view = user_rule.can_view
                    group_can_edit = user_rule.can_edit
                    group_can_add = user_rule.can_add

                else:
                    role_rules = group_access_rules.filter(
                        role__in=roles,
                        user__isnull=True,
                    )

                    group_can_view = role_rules.filter(
                        can_view=True,
                    ).exists()

                    group_can_edit = role_rules.filter(
                        can_edit=True,
                    ).exists()

                    group_can_add = role_rules.filter(
                        can_add=True,
                    ).exists()

                # Submitted step is always read-only.
                if is_submitted:
                    group_can_edit = False
                    group_can_add = False

                # User has no permission to see this group.
                #----------Debug-----------
                #-------End-Debug----------
                if not group_can_view:
                    continue

                group_fields = []
                group_has_editable_fields = False

                for field in group.fields.filter(
                    is_active=True,
                ):
                    access_rules = field.access_rules.filter(
                        step=step,
                    )

                    can_view = False
                    can_edit = False

                    user_rule = access_rules.filter(
                        user=user,
                    ).first()

                    if user_rule:
                        can_view = user_rule.can_view
                        can_edit = user_rule.can_edit

                    else:
                        role_rules = access_rules.filter(
                            role__in=roles,
                            user__isnull=True,
                        )

                        can_view = role_rules.filter(
                            can_view=True,
                        ).exists()

                        can_edit = role_rules.filter(
                            can_edit=True,
                        ).exists()

                    #---------------Debug-------------
                    #------------End-Debug------------

                    if not can_view:
                        continue

                    effective_can_edit = (
                        can_view
                        and can_edit
                        and group_can_edit
                        and edit_mode
                        and not is_submitted
                    )
                    if effective_can_edit:
                        group_has_editable_fields = True

                    field_data = {
                        "field": field,
                        "can_edit": effective_can_edit,
                        "choices": (
                            DynamicFormService._get_field_choices(field)
                            if field.field_type == field.FieldType.SELECT
                            else []
                        ),
                        "device_types": (
                            DeviceType.objects.filter(
                                is_active=True,
                            )
                            if field.system_key == FormField.SystemKey.DEVICE_TYPE
                            else []
                        ),
                        "device_models": (
                            DeviceModel.objects.filter(
                                is_active=True,
                            )
                            if field.system_key == FormField.SystemKey.DEVICE_MODEL
                            else []
                        ),    
                    }

                    group_fields.append(field_data)
#------------------------Debug-----------------------
# --------------------End-Debug----------------------                    
                if not group_fields:
                    continue

                # Saved repeatable items.
                #
                # Device groups use InstanceDevice
                # as their source of truth.
                #

                if group.group_type == FormRepeatableGroup.GroupType.DEVICE:

                    # =========================================================
                    # DEVICE REPEATABLE GROUP
                    # =========================================================
                    #
                    # Source of truth:
                    #
                    #     InstanceDevice
                    #
                    # A device can be in one of two states:
                    #
                    # 1. Draft device
                    #    instance_device.device is None
                    #
                    #    IMEI / Device Type / Device Model are editable
                    #    according to FieldAccess and edit_mode.
                    #
                    # 2. Existing device
                    #    instance_device.device is not None
                    #
                    #    IMEI / Device Type / Device Model are immutable.
                    #    Other fields remain editable according to permissions.
                    #
                    # =========================================================

                    instance_devices = (
                        InstanceDeviceService.get_devices_for_instance(
                            instance=instance,
                        )
                    )

                    # ---------------------------------------------------------
                    # POST data has priority only when validation failed.
                    #
                    # In normal GET requests, InstanceDevice remains the source
                    # of truth.
                    # ---------------------------------------------------------

                    submitted_device_items = []

                    if submitted_data is not None:
                        submitted_device_items = (
                            DynamicFormService._parse_repeatable_data(
                                submitted_data=submitted_data,
                                group_code=group.code,
                            )
                        )

                    items = []

                    # =========================================================
                    # FIELD HELPERS
                    # =========================================================

                    def get_field_info(field):
                        """
                        Return effective field permissions and metadata.
                        """

                        access_rules = field.access_rules.filter(
                            step=step,
                        )

                        can_view = False
                        permission_can_edit = False

                        user_rule = access_rules.filter(
                            user=user,
                        ).first()

                        if user_rule:

                            can_view = user_rule.can_view
                            permission_can_edit = user_rule.can_edit

                        else:

                            role_rules = access_rules.filter(
                                role__in=roles,
                                user__isnull=True,
                            )

                            can_view = role_rules.filter(
                                can_view=True,
                            ).exists()

                            permission_can_edit = role_rules.filter(
                                can_edit=True,
                            ).exists()

                        effective_can_edit = (
                            can_view
                            and permission_can_edit
                            and edit_mode
                            and not is_submitted
                        )

                        return {
                            "can_view": can_view,
                            "can_edit": effective_can_edit,
                            "permission_can_edit": permission_can_edit,
                        }

                    # =========================================================
                    # SYSTEM FIELD MAP
                    # =========================================================

                    field_map = {}

                    for field in group.fields.filter(
                        is_active=True,
                    ):

                        field_info = get_field_info(field)

                        if not field_info["can_view"]:
                            continue

                        if field.system_key != FormField.SystemKey.NONE:
                            field_map[field.system_key] = field

                    imei_field = field_map.get(
                        FormField.SystemKey.IMEI
                    )

                    device_type_field = field_map.get(
                        FormField.SystemKey.DEVICE_TYPE
                    )

                    device_model_field = field_map.get(
                        FormField.SystemKey.DEVICE_MODEL
                    )

                    # =========================================================
                    # BUILD GROUP FIELDS
                    # =========================================================

                    group_fields = []

                    for field in group.fields.filter(
                        is_active=True,
                    ):

                        field_info = get_field_info(field)

                        if not field_info["can_view"]:
                            continue

                        group_fields.append(
                            {
                                "field": field,
                                "can_edit": field_info["can_edit"],
                                "permission_can_edit": field_info[
                                    "permission_can_edit"
                                ],
                                "choices": (
                                    DynamicFormService._get_field_choices(field)
                                    if field.field_type == field.FieldType.SELECT
                                    else []
                                ),
                                "device_types": (
                                    DeviceType.objects.filter(
                                        is_active=True,
                                    )
                                    if field.system_key
                                    == FormField.SystemKey.DEVICE_TYPE
                                    else []
                                ),
                                "device_models": (
                                    DeviceModel.objects.filter(
                                        is_active=True,
                                    )
                                    if field.system_key
                                    == FormField.SystemKey.DEVICE_MODEL
                                    else []
                                ),
                            }
                        )

                    if not group_fields:
                        continue

                    group_has_editable_fields = any(
                        field_info["can_edit"]
                        for field_info in group_fields
                    )

                    # =========================================================
                    # CASE 1
                    # =========================================================
                    #
                    # Validation failed and POST contains device data.
                    #
                    # Render the submitted values so the operator does not lose
                    # what was entered.
                    #
                    # =========================================================

                    if submitted_device_items:

                        for submitted_item in submitted_device_items:

                            if not isinstance(
                                submitted_item,
                                dict,
                            ):
                                continue

                            # -------------------------------------------------
                            # Resolve submitted IDs
                            # -------------------------------------------------

                            device_type = None
                            device_model = None

                            submitted_device_type_id = (
                                submitted_item.get(
                                    "device_type"
                                )
                            )

                            submitted_device_model_id = (
                                submitted_item.get(
                                    "device_model_id"
                                )
                            )

                            if submitted_device_type_id:

                                device_type = (
                                    DeviceType.objects
                                    .filter(
                                        pk=submitted_device_type_id,
                                        is_active=True,
                                    )
                                    .first()
                                )

                            if submitted_device_model_id:

                                device_model = (
                                    DeviceModel.objects
                                    .filter(
                                        pk=submitted_device_model_id,
                                        is_active=True,
                                    )
                                    .first()
                                )

                            # -------------------------------------------------
                            # Existing device detection
                            # -------------------------------------------------

                            instance_device_id = (
                                submitted_item.get(
                                    "instance_device_id"
                                )
                            )

                            existing_instance_device = None

                            if instance_device_id:

                                existing_instance_device = (
                                    InstanceDevice.objects
                                    .filter(
                                        pk=instance_device_id,
                                        instance=instance,
                                        is_active=True,
                                    )
                                    .select_related(
                                        "device",
                                        "device__device_model",
                                        "device__device_model__device_type",
                                    )
                                    .first()
                                )

                            is_existing_device = (
                                existing_instance_device is not None
                                and existing_instance_device.device_id
                                is not None
                            )

                            # -------------------------------------------------
                            # Existing device:
                            #
                            # Always use the real Device identity.
                            # POST cannot change it.
                            # -------------------------------------------------

                            if is_existing_device:

                                real_device = (
                                    existing_instance_device.device
                                )

                                real_device_model = (
                                    real_device.device_model
                                )

                                real_device_type = (
                                    real_device_model.device_type
                                )

                                device_type = real_device_type
                                device_model = real_device_model

                                imei = ""

                                for identifier in (
                                    real_device.identifiers.all()
                                ):

                                    if (
                                        identifier.identifier_type
                                        == DeviceIdentifier.IdentifierType.IMEI
                                    ):
                                        imei = identifier.value
                                        break

                            else:

                                imei = str(
                                    submitted_item.get(
                                        "imei",
                                        "",
                                    )
                                ).strip()

                            # -------------------------------------------------
                            # Build fields
                            # -------------------------------------------------

                            item_fields = []

                            for field_info in group_fields:

                                field = field_info["field"]

                                value = ""
                                display_value = ""

                                # ---------------------------------------------
                                # IMEI
                                # ---------------------------------------------

                                if (
                                    field.system_key
                                    == FormField.SystemKey.IMEI
                                ):

                                    value = imei
                                    display_value = imei

                                # ---------------------------------------------
                                # DEVICE TYPE
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DEVICE_TYPE
                                ):

                                    value = (
                                        device_type.pk
                                        if device_type
                                        else ""
                                    )

                                    display_value = (
                                        device_type.name
                                        if device_type
                                        else ""
                                    )

                                # ---------------------------------------------
                                # DEVICE MODEL
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DEVICE_MODEL
                                ):

                                    value = (
                                        device_model.pk
                                        if device_model
                                        else ""
                                    )

                                    display_value = (
                                        str(device_model)
                                        if device_model
                                        else ""
                                    )

                                # ---------------------------------------------
                                # REPORTED PROBLEM
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.REPORTED_PROBLEM
                                ):

                                    value = submitted_item.get(
                                        "problem",
                                        "",
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # DESCRIPTION
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DESCRIPTION
                                ):

                                    value = submitted_item.get(
                                        "description",
                                        "",
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # WARRANTY STATUS
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.WARRANTY_STATUS
                                ):

                                    value = submitted_item.get(
                                        "warranty_status",
                                        "",
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # STATUS
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.STATUS
                                ):

                                    value = submitted_item.get(
                                        "status",
                                        "",
                                    )

                                    display_value = value

                                else:

                                    value = submitted_item.get(
                                        field.code,
                                        "",
                                    )

                                    display_value = value

                                # -------------------------------------------------
                                # Existing Device Identity Fields
                                #
                                # IMEI / TYPE / MODEL are immutable.
                                # -------------------------------------------------

                                field_can_edit = field_info[
                                    "can_edit"
                                ]

                                if is_existing_device and (
                                    field.system_key
                                    in {
                                        FormField.SystemKey.IMEI,
                                        FormField.SystemKey.DEVICE_TYPE,
                                        FormField.SystemKey.DEVICE_MODEL,
                                    }
                                ):
                                    field_can_edit = False

                                # -------------------------------------------------
                                # Device models filtered by type
                                # -------------------------------------------------

                                device_models = (
                                    DeviceModel.objects.filter(
                                        device_type=device_type,
                                        is_active=True,
                                    )
                                    .order_by(
                                        "brand",
                                        "name",
                                    )
                                    if (
                                        field.system_key
                                        == FormField.SystemKey.DEVICE_MODEL
                                        and device_type
                                    )
                                    else field_info.get(
                                        "device_models",
                                        [],
                                    )
                                )

                                item_fields.append(
                                    {
                                        "field": field,
                                        "can_edit": field_can_edit,
                                        "is_immutable": (
                                            field.system_key
                                            in {
                                                FormField.SystemKey.IMEI,
                                                FormField.SystemKey.DEVICE_TYPE,
                                                FormField.SystemKey.DEVICE_MODEL,
                                            }
                                        ),
                                        "is_imei_immutable": (
                                            field.system_key
                                            == FormField.SystemKey.IMEI
                                        ),
                                        "value": value,
                                        "display_value": display_value,
                                        "choices": field_info.get(
                                            "choices",
                                            [],
                                        ),
                                        "device_types": field_info.get(
                                            "device_types",
                                            [],
                                        ),
                                        "device_models": device_models,
                                    }
                                )

                            # -------------------------------------------------
                            # Build item
                            # -------------------------------------------------

                            item = {
                                "instance_device_id": (
                                    instance_device_id or ""
                                ),
                                "device_id": (
                                    existing_instance_device.device_id
                                    if is_existing_device
                                    else ""
                                ),
                                "is_existing_device": (
                                    is_existing_device
                                ),
                                "device_model_id": (
                                    device_model.pk
                                    if device_model
                                    else ""
                                ),
                                "device_type": (
                                    device_type.name
                                    if device_type
                                    else ""
                                ),
                                "device_model": (
                                    str(device_model)
                                    if device_model
                                    else ""
                                ),
                                "reported_problem": submitted_item.get(
                                    "problem",
                                    "",
                                ),
                                "description": submitted_item.get(
                                    "description",
                                    "",
                                ),
                                "warranty_status": submitted_item.get(
                                    "warranty_status",
                                    "",
                                ),
                                "status": submitted_item.get(
                                    "status",
                                    "",
                                ),
                                "identifiers": [
                                    {
                                        "type": "IMEI",
                                        "value": imei,
                                    }
                                ],
                                "fields": item_fields,
                            }

                            # -------------------------------------------------
                            # History availability
                            #
                            # Template can use this flag for the "سوابق"
                            # button.
                            # -------------------------------------------------

                            item["has_history"] = (
                                is_existing_device
                            )

                            items.append(item)

                    # =========================================================
                    # CASE 2
                    # =========================================================
                    #
                    # Normal GET:
                    #
                    # Load devices from InstanceDevice.
                    #
                    # =========================================================

                    else:

                        for instance_device in instance_devices:

                            # -------------------------------------------------
                            # Determine device state
                            # -------------------------------------------------

                            is_existing_device = (
                                instance_device.device_id
                                is not None
                            )

                            # -------------------------------------------------
                            # DRAFT DEVICE
                            # -------------------------------------------------

                            if not is_existing_device:

                                draft_model = (
                                    instance_device.draft_device_model
                                )

                                draft_type = (
                                    draft_model.device_type
                                    if draft_model
                                    else None
                                )

                                imei = (
                                    instance_device.draft_imei
                                    or ""
                                )

                                device_type = draft_type
                                device_model = draft_model

                            # -------------------------------------------------
                            # EXISTING DEVICE
                            # -------------------------------------------------

                            else:

                                device = (
                                    instance_device.device
                                )

                                device_model = (
                                    device.device_model
                                )

                                device_type = (
                                    device_model.device_type
                                    if device_model
                                    else None
                                )

                                imei = ""

                                for identifier in (
                                    device.identifiers.all()
                                ):

                                    if (
                                        identifier.identifier_type
                                        == DeviceIdentifier.IdentifierType.IMEI
                                    ):

                                        imei = identifier.value
                                        break

                            # -------------------------------------------------
                            # Device models for selected type
                            # -------------------------------------------------

                            device_models_for_type = (
                                DeviceModel.objects
                                .filter(
                                    device_type=device_type,
                                    is_active=True,
                                )
                                .order_by(
                                    "brand",
                                    "name",
                                )
                                if device_type
                                else DeviceModel.objects.none()
                            )

                            # -------------------------------------------------
                            # Build fields
                            # -------------------------------------------------

                            item_fields = []

                            for field_info in group_fields:

                                field = field_info["field"]

                                value = ""
                                display_value = ""

                                # ---------------------------------------------
                                # IMEI
                                # ---------------------------------------------

                                if (
                                    field.system_key
                                    == FormField.SystemKey.IMEI
                                ):

                                    value = imei
                                    display_value = imei

                                # ---------------------------------------------
                                # DEVICE TYPE
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DEVICE_TYPE
                                ):

                                    value = (
                                        device_type.pk
                                        if device_type
                                        else ""
                                    )

                                    display_value = (
                                        device_type.name
                                        if device_type
                                        else ""
                                    )

                                # ---------------------------------------------
                                # DEVICE MODEL
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DEVICE_MODEL
                                ):

                                    value = (
                                        device_model.pk
                                        if device_model
                                        else ""
                                    )

                                    display_value = (
                                        str(device_model)
                                        if device_model
                                        else ""
                                    )

                                # ---------------------------------------------
                                # REPORTED PROBLEM
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.REPORTED_PROBLEM
                                ):

                                    value = (
                                        instance_device.reported_problem
                                        or ""
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # DESCRIPTION
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.DESCRIPTION
                                ):

                                    value = (
                                        instance_device.description
                                        or ""
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # WARRANTY STATUS
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.WARRANTY_STATUS
                                ):

                                    value = (
                                        instance_device.warranty_status
                                        or ""
                                    )

                                    display_value = value

                                # ---------------------------------------------
                                # STATUS
                                # ---------------------------------------------

                                elif (
                                    field.system_key
                                    == FormField.SystemKey.STATUS
                                ):

                                    value = (
                                        instance_device.status
                                        or ""
                                    )

                                    display_value = value

                                else:

                                    value = ""

                                    display_value = ""

                                # -------------------------------------------------
                                # Identity fields
                                #
                                # Existing Device:
                                #     IMEI / TYPE / MODEL => immutable
                                #
                                # Draft Device:
                                #     according to FieldAccess + edit_mode
                                # -------------------------------------------------

                                field_can_edit = field_info[
                                    "can_edit"
                                ]

                                is_identity_field = (
                                    field.system_key
                                    in {
                                        FormField.SystemKey.IMEI,
                                        FormField.SystemKey.DEVICE_TYPE,
                                        FormField.SystemKey.DEVICE_MODEL,
                                    }
                                )

                                if (
                                    is_existing_device
                                    and is_identity_field
                                ):
                                    field_can_edit = False

                                # -------------------------------------------------
                                # Device model list
                                # -------------------------------------------------

                                device_models = (
                                    device_models_for_type
                                    if (
                                        field.system_key
                                        == FormField.SystemKey.DEVICE_MODEL
                                    )
                                    else field_info.get(
                                        "device_models",
                                        [],
                                    )
                                )

                                item_fields.append(
                                    {
                                        "field": field,
                                        "can_edit": field_can_edit,
                                        "is_immutable": (
                                            is_identity_field
                                        ),
                                        "is_imei_immutable": (
                                            field.system_key
                                            == FormField.SystemKey.IMEI
                                        ),
                                        "value": value,
                                        "display_value": display_value,
                                        "choices": field_info.get(
                                            "choices",
                                            [],
                                        ),
                                        "device_types": field_info.get(
                                            "device_types",
                                            [],
                                        ),
                                        "device_models": device_models,
                                    }
                                )

                            # -------------------------------------------------
                            # Build device item
                            # -------------------------------------------------

                            items.append(
                                {
                                    "instance_device_id": (
                                        instance_device.pk
                                    ),
                                    "device_id": (
                                        instance_device.device_id
                                        or ""
                                    ),
                                    "is_existing_device": (
                                        is_existing_device
                                    ),
                                    "device_model_id": (
                                        device_model.pk
                                        if device_model
                                        else ""
                                    ),
                                    "device_type": (
                                        device_type.name
                                        if device_type
                                        else ""
                                    ),
                                    "device_model": (
                                        str(device_model)
                                        if device_model
                                        else ""
                                    ),
                                    "reported_problem": (
                                        instance_device.reported_problem
                                        or ""
                                    ),
                                    "description": (
                                        instance_device.description
                                        or ""
                                    ),
                                    "warranty_status": (
                                        instance_device.warranty_status
                                        or ""
                                    ),
                                    "status": (
                                        instance_device.status
                                        or ""
                                    ),
                                    "identifiers": [
                                        {
                                            "type": identifier.identifier_type,
                                            "value": identifier.value,
                                        }
                                        for identifier
                                        in (
                                            instance_device.device.identifiers.all()
                                            if instance_device.device
                                            else []
                                        )
                                    ]
                                    or [
                                        {
                                            "type": "IMEI",
                                            "value": imei,
                                        }
                                    ],
                                    "has_history": (
                                        is_existing_device
                                    ),
                                    "fields": item_fields,
                                }
                            )

                                        
                else:
                    raw_items = data.get(
                        group.code,
                        [],
                    )

                    print("========== NORMAL REPEATABLE DEBUG ==========")
                    print("GROUP:", group.code)
                    print("FORM DATA:", repr(data))
                    print("RAW ITEMS:", repr(raw_items))
                    print("==============================================")
                    if not isinstance(raw_items, list):
                        raw_items = []

                    if not raw_items:
                        raw_items = [{}]                                   
                    items = []

                    for raw_item in raw_items:

                        if not isinstance(raw_item, dict):
                            continue

                        item_fields = []

                        for field_info in group_fields:

                            field = field_info["field"]

                            item_fields.append(
                                {
                                    "field": field,
                                    "can_edit": (
                                        field_info["can_edit"]
                                        and group_can_edit
                                        and edit_mode
                                        and not is_submitted
                                    ),
                                    "permission_can_edit": field_info.get(
                                        "permission_can_edit",
                                        False,
                                    ),
                                    "value": raw_item.get(
                                        field.code,
                                        "",
                                    ),
                                    "choices": (
                                        DynamicFormService._get_field_choices(field)
                                        if field.field_type == field.FieldType.SELECT
                                        else []
                                    ),
                                }
                            )

                        items.append(
                            {
                                "fields": item_fields,
                            }
                        )
                    #--------------Debug---------------
                    #---------End-Debug----------------
                repeatable_groups.append(
                    {
                        "group": group,
                        "fields": group_fields,
                        "items": items,
                        "has_editable_fields": group_has_editable_fields,
                        "can_view": group_can_view,
                        "can_edit": group_can_edit,
                        "can_add": group_can_add,
                    }
                )

                    #------------------Debug--------------
                    #---------------End-Debug-------------

            # -------------------------------------------------
            # Add section only when it contains something
            # -------------------------------------------------
            if fields or repeatable_groups:
                sections.append(
                    {
                        "section": section,
                        "fields": fields,
                        "repeatable_groups": repeatable_groups,
                    }
                )

        has_editable_fields = any(
            item["can_edit"]
            for section in sections
            for item in section["fields"]
        ) or any(
            field_info["can_edit"]
            for section in sections
            for group in section["repeatable_groups"]
            for field_info in group["fields"]
        )

        return {
            "form": form,
            "sections": sections,
            "has_saved_data": has_saved_data,
            "is_submitted": step_is_submitted,
            "has_editable_fields": has_editable_fields,
        }

    @staticmethod
    @transaction.atomic
    def save_form_for_step(
        *,
        instance,
        user,
        submitted_data,
    ):
        """
        Save normal form fields and process repeatable groups.

        Device repeatable groups are persisted through
        InstanceDeviceService and are not stored as the
        source of truth inside FormData.data.
        """

        workflow = instance.workflow
        step = instance.current_step

        #-----------ِDebug-----------
        print("========== GET FORM DEBUG ==========")
        print("SUBMITTED DATA:", repr(submitted_data))
        print("====================================")
        #--------End-Debug----------

        if step is None:
            raise ValidationError(
                "این Workflow مرحله فعلی ندارد."
            )

        current_step_execution = (
            instance.step_executions
            .filter(
                workflow_step=step,
            )
            .order_by("-performed_at")
            .first()
        )

        # ---------------------------------------------------------
        # Submitted step is locked
        # ---------------------------------------------------------

        if (
            current_step_execution is not None
            and current_step_execution.is_submitted
        ):
            raise ValidationError(
                "فرم این مرحله قبلاً ارسال شده و دیگر قابل ویرایش نیست."
            )
        form = (
            FormDefinition.objects.filter(
                workflow=workflow,
                is_active=True,
            )
            .prefetch_related(
                "sections__fields__access_rules",
                "sections__repeatable_groups__fields__access_rules",
            )
            .first()
        )

        if form is None:
            raise ValidationError("برای این Workflow فرمی تعریف نشده است.")

        roles = set(
            workflow.memberships.filter(
                user=user,
                is_active=True,
            ).values_list(
                "role",
                flat=True,
            )
        )

        editable_codes = set()

        # -------------------------------------------------
        # 1. Collect editable normal fields
        # -------------------------------------------------

        for section in form.sections.filter(
            is_active=True,
        ):
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            ):
                access_rules = field.access_rules.filter(
                    step=step,
                )

                user_rule = access_rules.filter(
                    user=user,
                ).first()

                if user_rule:
                    can_edit = user_rule.can_edit

                else:
                    role_rules = access_rules.filter(
                        role__in=roles,
                        user__isnull=True,
                    )

                    can_edit = role_rules.filter(
                        can_edit=True,
                    ).exists()

                if can_edit:
                    editable_codes.add(field.code)


        print("========== REQUIRED VALIDATION DEBUG ==========")
        print("SUBMITTED DATA:", repr(submitted_data))
        print("EDITABLE CODES:", repr(editable_codes))

        for section in form.sections.filter(is_active=True):
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            ):
                print(
                    "NORMAL FIELD:",
                    field.code,
                    "label=", field.label,
                    "required=", field.is_required,
                    "editable=", field.code in editable_codes,
                )

        print("===============================================")
        # -------------------------------------------------
        # 2. Validate required normal fields
        # -------------------------------------------------
        required_errors = []

        for section in form.sections.filter(
            is_active=True,
        ):
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            ):
                if not field.is_required:
                    continue

                if field.code not in editable_codes:
                    continue

                value = submitted_data.get(
                    field.code,
                    "",
                )

                if isinstance(value, str):
                    value = value.strip()

                if value in ("", None):
                    required_errors.append(
                        {
                            "type": "field",
                            "code": field.code,
                            "label": field.label,
                            "message": f"فیلد «{field.label}» الزامی است.",
                        }
                    )

        # -------------------------------------------------
        # 2.1 Validate required repeatable groups
        # -------------------------------------------------

        for section in form.sections.filter(
            is_active=True,
        ):
            for group in section.repeatable_groups.filter(
                is_active=True,
            ):

                # -------------------------------------------------
                # Check repeatable-group visibility
                # -------------------------------------------------

                group_access_rules = group.access_rules.filter(
                    step=step,
                )

                group_can_view = False

                user_rule = group_access_rules.filter(
                    user=user,
                ).first()

                if user_rule:
                    group_can_view = user_rule.can_view

                else:
                    group_can_view = (
                        group_access_rules
                        .filter(
                            role__in=roles,
                            user__isnull=True,
                            can_view=True,
                        )
                        .exists()
                    )

                # Hidden group does not participate in validation.
                if not group_can_view:
                    continue

                # -------------------------------------------------
                # Parse submitted items
                #
                # This must happen for BOTH required and optional
                # repeatable groups.
                # -------------------------------------------------

                items = DynamicFormService._parse_repeatable_data(
                    submitted_data=submitted_data,
                    group_code=group.code,
                )

                # -------------------------------------------------
                # Required group validation
                # -------------------------------------------------

                if group.is_required and not items:

                    required_errors.append(
                        {
                            "type": "group",
                            "code": group.code,
                            "label": group.name,
                            "message": (
                                f"گروه «{group.name}» "
                                "حداقل یک مورد الزامی دارد."
                            ),
                        }
                    )

                    # No items exist, therefore there is nothing
                    # inside this group to validate.
                    continue

                # -------------------------------------------------
                # No items → nothing to validate at field level
                # -------------------------------------------------

                if not items:
                    continue

                # -------------------------------------------------
                # Validate required fields inside each item
                # -------------------------------------------------

                for item_index, item in enumerate(items):

                    if not isinstance(item, dict):
                        continue

                    for field in group.fields.filter(
                        is_active=True,
                        is_required=True,
                    ):

                        access_rules = field.access_rules.filter(
                            step=step,
                        )

                        field_can_view = False
                        field_can_edit = False

                        user_rule = access_rules.filter(
                            user=user,
                        ).first()

                        if user_rule:

                            field_can_view = user_rule.can_view
                            field_can_edit = user_rule.can_edit

                        else:

                            role_rules = access_rules.filter(
                                role__in=roles,
                                user__isnull=True,
                            )

                            field_can_view = (
                                role_rules
                                .filter(
                                    can_view=True,
                                )
                                .exists()
                            )

                            field_can_edit = (
                                role_rules
                                .filter(
                                    can_edit=True,
                                )
                                .exists()
                            )

                        # Hidden field must not be validated.
                        if not field_can_view:
                            continue

                        # Only fields the user is allowed to edit
                        # participate in Save validation.
                        if not field_can_edit:
                            continue

                        # -------------------------------------------------
                        # Read submitted value
                        # -------------------------------------------------

                        value = item.get(
                            field.code,
                            "",
                        )

                        if isinstance(value, str):
                            value = value.strip()

                        # -------------------------------------------------
                        # Empty required field
                        # -------------------------------------------------

                        if value in ("", None):

                            required_errors.append(
                                {
                                    "type": "repeatable_field",
                                    "group_code": group.code,
                                    "group_label": group.name,
                                    "field_code": field.code,
                                    "field_label": field.label,
                                    "item_index": item_index,
                                    "message": (
                                        f"فیلد «{field.label}» "
                                        f"در ردیف {item_index + 1} "
                                        "الزامی است."
                                    ),
                                }
                            )        
        # -------------------------------------------------
        # Stop immediately if validation failed
        # -------------------------------------------------

        if required_errors:
            validation_error = ValidationError(
                "Validation failed."
            )

            validation_error.validation_errors = (
                required_errors
            )

            raise validation_error

        form_data, _ = FormData.objects.get_or_create(
                    instance=instance,
                    defaults={
                        "data": {},
                    },
                )
        
        current_data = dict(form_data.data or {})

        # ---------------------------------------------------------
        # Activate DRAFT on first valid form save
        # ---------------------------------------------------------

        if instance.status == WorkflowInstance.Status.DRAFT:

            if current_step_execution is not None:
                raise ValidationError(
                    "وضعیت Draft این Workflow نامعتبر است."
                )

            instance.status = WorkflowInstance.Status.ACTIVE
            instance.save(
                update_fields=[
                    "status",
                ]
            )

            current_step_execution = (
                WorkflowStepExecution.objects.create(
                    instance=instance,
                    workflow_step=step,
                    performed_by=user,
                    data={},
                )
            )

            SLAService.start_sla_if_configured(
                step_execution=current_step_execution,
            )

        # ---------------------------------------------------------
        # Active workflow must have current step execution
        # ---------------------------------------------------------

        elif current_step_execution is None:

            raise ValidationError(
                "اجرای مرحله فعلی این Workflow پیدا نشد."
            )
        

        # -------------------------------------------------
        # 3. Save normal fields
        # -------------------------------------------------

        for code in editable_codes:
            if code in submitted_data:
                current_data[code] = submitted_data[code]

        # -------------------------------------------------
        # 4. Process repeatable groups
        # -------------------------------------------------

        for section in form.sections.filter(
            is_active=True,
        ):
            for group in section.repeatable_groups.filter(
                is_active=True,
            ):
                
                # -------------------------------------------------
                # Verify repeatable-group access
                # -------------------------------------------------

                group_access_rules = RepeatableGroupAccess.objects.filter(
                    group=group,
                    step=step,
                )

                group_can_edit = False
                group_can_add = False

                user_rule = group_access_rules.filter(
                    user=user,
                ).first()

                if user_rule:
                    group_can_edit = user_rule.can_edit
                    group_can_add = user_rule.can_add

                else:
                    role_rules = group_access_rules.filter(
                        role__in=roles,
                        user__isnull=True,
                    )

                    group_can_edit = role_rules.filter(
                        can_edit=True,
                    ).exists()

                    group_can_add = role_rules.filter(
                        can_add=True,
                    ).exists()

                # -------------------------------------------------
                # Verify submitted repeatable group
                # -------------------------------------------------
                items = DynamicFormService._parse_repeatable_data(
                    submitted_data=submitted_data,
                    group_code=group.code,
                )

                print("========== REPEATABLE VALIDATION DEBUG ==========")
                print("GROUP:", group.code)
                print("GROUP REQUIRED:", group.is_required)
                print("GROUP CAN VIEW:", group_can_view)
                print("PARSED ITEMS:", repr(items))

                for debug_item_index, debug_item in enumerate(items):
                    print(
                        "ITEM",
                        debug_item_index,
                        ":",
                        repr(debug_item),
                    )

                print("=================================================")

                if not items:
                    continue                

                # -------------------------------------------------
                # Existing items require can_edit
                # New items require can_add
                # -------------------------------------------------

                has_new_item = any(
                    not item.get("instance_device_id")
                    for item in items
                )

                has_existing_item = any(
                    item.get("instance_device_id")
                    for item in items
                )

                if has_existing_item and not group_can_edit:
                    raise ValidationError(
                        f"شما اجازه ویرایش گروه «{group.name}» را ندارید."
                    )

                if has_new_item and not group_can_add:
                    raise ValidationError(
                        f"شما اجازه افزودن به گروه «{group.name}» را ندارید."
                    )
                # -------------------------------------------------
                # Process repeatable group
                # -------------------------------------------------   

                # -----------------------------------------
                # Device repeatable group
                # -----------------------------------------

                if group.group_type == FormRepeatableGroup.GroupType.DEVICE:

                    # -------------------------------------------------
                    # Build field-level edit permissions
                    # -------------------------------------------------

                    editable_system_keys = set()
                    field_map = {}

                    for field in group.fields.filter(
                        is_active=True,
                    ):
                        access_rules = field.access_rules.filter(
                            step=step,
                        )

                        user_rule = access_rules.filter(
                            user=user,
                        ).first()

                        if user_rule:
                            can_edit = user_rule.can_edit
                        else:
                            can_edit = access_rules.filter(
                                role__in=roles,
                                user__isnull=True,
                                can_edit=True,
                            ).exists()

                        # code is user-defined.
                        # system_key is the only stable semantic identifier.
                        if field.system_key != FormField.SystemKey.NONE:
                            field_map[field.system_key] = field.code

                            if can_edit:
                                editable_system_keys.add(
                                    field.system_key
                                )
                    imei_code = field_map.get(
                        FormField.SystemKey.IMEI
                    )

                    device_model_code = field_map.get(
                        FormField.SystemKey.DEVICE_MODEL
                    )

                    device_type_code = field_map.get(
                        FormField.SystemKey.DEVICE_TYPE
                    )

                    reported_problem_code = field_map.get(
                        FormField.SystemKey.REPORTED_PROBLEM
                    )

                    description_code = field_map.get(
                        FormField.SystemKey.DESCRIPTION
                    )

                    warranty_status_code = field_map.get(
                        FormField.SystemKey.WARRANTY_STATUS
                    )

                    status_code = field_map.get(
                        FormField.SystemKey.STATUS
                    )
                    # -------------------------------------------------
                    # Process submitted devices
                    # -------------------------------------------------
                    group_access_rules = group.access_rules.filter(
                        step=step,
                    )

                    user_group_rule = group_access_rules.filter(
                        user=user,
                    ).first()

                    if user_group_rule:
                        can_add = user_group_rule.can_add
                    else:
                        can_add = group_access_rules.filter(
                            role__in=roles,
                            user__isnull=True,
                            can_add=True,
                        ).exists()
                    for item in items:
                        if not isinstance(item, dict):
                            raise ValidationError(
                                "اطلاعات هر دستگاه باید به صورت یک شیء باشد."
                            )
                        # تبدیل نام فیلد فرم به نام فیلد مدل
                        if "problem" in item and "reported_problem" not in item:
                            item["reported_problem"] = item["problem"]

                        instance_device_id = item.get("instance_device_id")

                        # -------------------------------------------------
                        # Existing device
                        # -------------------------------------------------

                        if instance_device_id:
                            try:
                                instance_device = InstanceDevice.objects.select_related(
                                    "device",
                                    "device__device_model",
                                    "draft_device_model",
                                ).get(
                                    pk=instance_device_id,
                                    instance=instance,
                                )
                            except InstanceDevice.DoesNotExist:
                                raise ValidationError(
                                    "دستگاه مربوط به این فرآیند پیدا نشد."
                                )

                            # -------------------------------------------------
                            # Existing DRAFT device
                            # -------------------------------------------------

                            if instance_device.device is None:

                                if (
                                    imei_code
                                    and FormField.SystemKey.IMEI in editable_system_keys
                                    and imei_code in item
                                ):
                                    instance_device.draft_imei = str(
                                        item[imei_code]
                                    ).strip()

                                if (
                                    device_model_code
                                    and FormField.SystemKey.DEVICE_MODEL in editable_system_keys
                                    and device_model_code in item
                                ):
                                    try:
                                        draft_model = DeviceModel.objects.get(
                                            pk=item[device_model_code],
                                            is_active=True,
                                        )
                                    except DeviceModel.DoesNotExist:
                                        raise ValidationError(
                                            "مدل دستگاه معتبر نیست."
                                        )

                                    instance_device.draft_device_model = draft_model

                                if (
                                    reported_problem_code
                                    and FormField.SystemKey.REPORTED_PROBLEM in editable_system_keys
                                    and reported_problem_code in item
                                ):
                                    instance_device.reported_problem = item[
                                        reported_problem_code
                                    ]

                                if (
                                    description_code
                                    and FormField.SystemKey.DESCRIPTION in editable_system_keys
                                    and description_code in item
                                ):
                                    instance_device.description = item[
                                        description_code
                                    ]

                                if (
                                    warranty_status_code
                                    and FormField.SystemKey.WARRANTY_STATUS in editable_system_keys
                                    and warranty_status_code in item
                                ):
                                    instance_device.warranty_status = item[
                                        warranty_status_code
                                    ]

                                if (
                                    status_code
                                    and FormField.SystemKey.STATUS in editable_system_keys
                                    and status_code in item
                                ):
                                    instance_device.status = item[
                                        status_code
                                    ]

                                existing_device = (
                                    DeviceService.get_device_by_identifier(
                                        identifier_type=(
                                            DeviceIdentifier
                                            .IdentifierType.IMEI
                                        ),
                                        value=instance_device.draft_imei,
                                    )
                                )

                                if existing_device:
                                    if (
                                        instance_device.draft_device_model_id
                                        != existing_device.device_model_id
                                    ):
                                        raise ValidationError(
                                            "این IMEI قبلاً برای مدل دیگری ثبت شده است."
                                        )

                                    duplicate = (
                                        InstanceDevice.objects
                                        .filter(
                                            instance=instance,
                                            device=existing_device,
                                        )
                                        .exclude(pk=instance_device.pk)
                                        .exists()
                                    )
                                    if duplicate:
                                        raise ValidationError(
                                            "این دستگاه قبلاً به این فرآیند افزوده شده است."
                                        )

                                    instance_device.device = existing_device
                                    instance_device.draft_imei = ""
                                    instance_device.draft_device_model = None

                                instance_device.save()

                                continue

                            # ---------------------------------------------
                            # IMEI
                            # ---------------------------------------------

                            if imei_code and imei_code in item:

                                submitted_imei = str(
                                    item[imei_code]
                                ).strip()

                                current_imei = (
                                    instance_device.device.identifiers
                                    .filter(
                                        identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                                    )
                                    .values_list(
                                        "value",
                                        flat=True,
                                    )
                                    .first()
                                )

                                if submitted_imei != current_imei:
                                    raise ValidationError(
                                        "IMEI دستگاه موجود قابل ویرایش نیست."
                                    )
                            
                            # ---------------------------------------------
                            # Device Type
                            # ---------------------------------------------

                            if (
                                device_type_code
                                and device_type_code in item
                            ):
                                submitted_type_id = item[device_type_code]

                                current_type_id = (
                                    instance_device
                                    .device
                                    .device_model
                                    .device_type_id
                                )

                                if (
                                    str(submitted_type_id)
                                    != str(current_type_id)
                                ):
                                    raise ValidationError(
                                        "نوع دستگاه با مدل فعلی دستگاه مطابقت ندارد."
                                    )
                            # ---------------------------------------------
                            # Device Model
                            # ---------------------------------------------

                            if (
                                device_model_code
                                and device_model_code in item
                            ):
                                submitted_model_id = item[
                                    device_model_code
                                ]

                                current_model_id = (
                                    instance_device.device.device_model_id
                                )

                                if (
                                    FormField.SystemKey.DEVICE_MODEL
                                    not in editable_system_keys
                                    and str(submitted_model_id)
                                    != str(current_model_id)
                                ):
                                    raise ValidationError(
                                        "شما اجازه ویرایش مدل این دستگاه را ندارید."
                                    )

                                if (
                                    FormField.SystemKey.DEVICE_MODEL
                                    in editable_system_keys
                                    and str(submitted_model_id)
                                    != str(current_model_id)
                                ):
                                    try:
                                        new_device_model = DeviceModel.objects.select_related(
                                            "device_type",
                                        ).get(
                                            pk=submitted_model_id,
                                            is_active=True,
                                        )
                                    except DeviceModel.DoesNotExist:
                                        raise ValidationError(
                                            "مدل دستگاه انتخاب‌شده معتبر نیست."
                                        )

                                    if (
                                        device_type_code
                                        and device_type_code in item
                                    ):
                                        submitted_device_type_id = item[
                                            device_type_code
                                        ]

                                        if (
                                            str(new_device_model.device_type_id)
                                            != str(submitted_device_type_id)
                                        ):
                                            raise ValidationError(
                                                "مدل انتخاب‌شده متعلق به نوع دستگاه انتخاب‌شده نیست."
                                            )

                                    instance_device.device.device_model = (
                                        new_device_model
                                    )

                                    instance_device.device.save(
                                        update_fields=[
                                            "device_model",
                                        ]
                                    )

                            # ---------------------------------------------
                            # Device Type
                            # ---------------------------------------------

                            if (
                                device_type_code
                                and device_type_code in item
                            ):
                                submitted_device_type_id = item[
                                    device_type_code
                                ]

                                current_device_type_id = (
                                    instance_device
                                    .device
                                    .device_model
                                    .device_type_id
                                )

                                if (
                                    str(submitted_device_type_id)
                                    != str(current_device_type_id)
                                ):
                                    raise ValidationError(
                                        "نوع دستگاه با مدل فعلی دستگاه مطابقت ندارد."
                                    )

                            # ---------------------------------------------
                            # Reported problem
                            # ---------------------------------------------

                            if (
                                reported_problem_code
                                and reported_problem_code in item
                                and (
                                    FormField.SystemKey.REPORTED_PROBLEM
                                    not in editable_system_keys
                                )
                                and item[reported_problem_code]
                                != instance_device.reported_problem
                            ):
                                raise ValidationError(
                                    "شما اجازه ویرایش شرح مشکل این دستگاه را ندارید."
                                )

                            if (
                                description_code
                                and description_code in item
                                and (
                                    FormField.SystemKey.DESCRIPTION
                                    not in editable_system_keys
                                )
                                and item[description_code]
                                != instance_device.description
                            ):
                                raise ValidationError(
                                    "شما اجازه ویرایش توضیحات تکمیلی این دستگاه را ندارید."
                                )
                            # ---------------------------------------------
                            # Warranty status
                            # ---------------------------------------------

                            if (
                                warranty_status_code
                                and warranty_status_code in item
                                and (
                                    FormField.SystemKey.WARRANTY_STATUS
                                    not in editable_system_keys
                                )
                                and item[warranty_status_code]
                                != instance_device.warranty_status
                            ):
                                raise ValidationError(
                                    "شما اجازه ویرایش وضعیت گارانتی این دستگاه را ندارید."
                                )

                            # ---------------------------------------------
                            # Status
                            # ---------------------------------------------

                            if (
                                status_code
                                and status_code in item
                                and (
                                    FormField.SystemKey.STATUS
                                    not in editable_system_keys
                                )
                                and item[status_code]
                                != instance_device.status
                            ):
                                raise ValidationError(
                                    "شما اجازه ویرایش وضعیت این دستگاه را ندارید."
                                )

                            # ---------------------------------------------
                            # Apply editable fields only
                            # ---------------------------------------------

                            update_fields = []
                            if (
                                reported_problem_code
                                and FormField.SystemKey.REPORTED_PROBLEM
                                in editable_system_keys
                                and reported_problem_code in item
                            ):
                                instance_device.reported_problem = item[
                                    reported_problem_code
                                ]

                                update_fields.append(
                                    "reported_problem"
                                )

                            if (
                                description_code
                                and FormField.SystemKey.DESCRIPTION
                                in editable_system_keys
                                and description_code in item
                            ):
                                instance_device.description = item[
                                    description_code
                                ]

                                update_fields.append(
                                    "description"
                                )

                            if (
                                warranty_status_code
                                and FormField.SystemKey.WARRANTY_STATUS
                                in editable_system_keys
                                and warranty_status_code in item
                            ):
                                instance_device.warranty_status = item[
                                    warranty_status_code
                                ]

                                update_fields.append(
                                    "warranty_status"
                                )
                            if (
                                status_code
                                and FormField.SystemKey.STATUS
                                in editable_system_keys
                                and status_code in item
                            ):
                                instance_device.status = item[
                                    status_code
                                ]

                                update_fields.append(
                                    "status"
                                )
                            if update_fields:
                                update_fields.append("updated_at")

                                instance_device.save(update_fields=update_fields)

                            # Existing device is done.
                            continue

                        # -------------------------------------------------
                        # New device
                        # -------------------------------------------------

                        #-------------------Debug--------------
                        print("========== DEBUG BEFORE NEW DEVICE ==========")
                        print("item:", item)
                        print("instance_device_id:", item.get("instance_device_id"))
                        print("can_add:", can_add)
                        print("editable_system_keys:", editable_system_keys)
                        print("imei_code:", imei_code)
                        print("device_model_code:", device_model_code)
                        print("=============================================")
                        #----------------End-Debug-------------
                        if not can_add:
                            raise ValidationError(
                                "شما اجازه افزودن مورد جدید به این گروه را ندارید."
                            )

                        if FormField.SystemKey.IMEI not in editable_system_keys:
                            raise ValidationError(
                                "شما اجازه ثبت IMEI دستگاه را ندارید."
                            )

                        if (
                            FormField.SystemKey.DEVICE_MODEL
                            not in editable_system_keys
                        ):
                            raise ValidationError(
                                "شما اجازه ثبت مدل دستگاه را ندارید."
                            )

                        if not imei_code:
                            raise ValidationError(
                                "فیلد IMEI در فرم دستگاه تعریف نشده است."
                            )

                        if not device_model_code:
                            raise ValidationError(
                                "فیلد مدل دستگاه در فرم دستگاه تعریف نشده است."
                            )

                        imei = item.get(
                            imei_code,
                        )

                        device_model_id = item.get(
                            device_model_code,
                        )

                        if not imei:
                            raise ValidationError("IMEI دستگاه الزامی است.")

                        if not device_model_id:
                            raise ValidationError("مدل دستگاه الزامی است.")

                        try:
                            device_model = DeviceModel.objects.get(
                                pk=device_model_id,
                                is_active=True,
                            )
                        except DeviceModel.DoesNotExist:
                            raise ValidationError("مدل دستگاه معتبر نیست.")
#--------------------Debug-----------------
                        print("========== DEBUG NEW DEVICE ==========")
                        print("instance.id:", instance.id)
                        print("item:", item)
                        print("imei_code:", imei_code)
                        print("device_model_code:", device_model_code)
                        print("imei:", imei)
                        print("device_model_id:", device_model_id)
                        print("device_model:", device_model)
                        print("can_add:", can_add)
                        print("editable_system_keys:", editable_system_keys)
                        print("======================================")
#-----------------End-Debug----------------
                        existing_device = DeviceService.get_device_by_identifier(
                            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
                            value=imei,
                        )

                        if existing_device:
                            if existing_device.device_model_id != device_model.pk:
                                raise ValidationError(
                                    "این IMEI قبلاً برای مدل دیگری ثبت شده است."
                                )

                            instance_device, created = (
                                InstanceDevice.objects.get_or_create(
                                    instance=instance,
                                    device=existing_device,
                                    defaults={
                                        "reported_problem": "",
                                        "description": "",
                                        "warranty_status": "",
                                        "status": "",
                                    },
                                )
                            )

                            if not created and instance_device.is_active:
                                raise ValidationError(
                                    "این دستگاه قبلاً به این فرآیند افزوده شده است."
                                )

                            instance_device.is_active = True
                            instance_device.draft_imei = ""
                            instance_device.draft_device_model = None
                        else:
                            # A new IMEI remains a draft until the workflow
                            # lifecycle commits it to a persistent Device.
                            instance_device = InstanceDevice(
                                instance=instance,
                                device=None,
                                draft_imei=imei,
                                draft_device_model=device_model,
                            )

                        instance_device.reported_problem = (
                            item.get(reported_problem_code, "")
                            if reported_problem_code
                            else ""
                        )
                        instance_device.description = (
                            item.get(description_code, "")
                            if description_code
                            else ""
                        )
                        instance_device.warranty_status = (
                            item.get(warranty_status_code, "")
                            if warranty_status_code
                            else ""
                        )
                        instance_device.status = (
                            item.get(status_code, "")
                            if status_code
                            else ""
                        )
                        instance_device.save()

                    # Device group is persisted in relational models.
                    # It must not be copied into FormData.
                    continue
                # -------------------------------------------------
                # Persist non-device repeatable groups
                # -------------------------------------------------

                previous_items = current_data.get(
                    group.code,
                    [],
                )

                if not isinstance(previous_items, list):
                    previous_items = []

                # ---------------------------------------------
                # Build field-level permission map
                # ---------------------------------------------

                field_permissions = {}

                for field in group.fields.filter(
                    is_active=True,
                ):

                    access_rules = field.access_rules.filter(
                        step=step,
                    )

                    user_rule = access_rules.filter(
                        user=user,
                    ).first()

                    if user_rule:

                        field_permissions[field.code] = (
                            user_rule.can_edit
                        )

                    else:

                        field_permissions[field.code] = (
                            access_rules
                            .filter(
                                role__in=roles,
                                user__isnull=True,
                                can_edit=True,
                            )
                            .exists()
                        )

                # ---------------------------------------------
                # Existing items are used to preserve fields
                # that the current user cannot edit.
                # ---------------------------------------------

                saved_items = []

                for index, item in enumerate(items):

                    if not isinstance(item, dict):
                        continue

                    previous_item = (
                        previous_items[index]
                        if index < len(previous_items)
                        and isinstance(previous_items[index], dict)
                        else {}
                    )

                    saved_item = {}

                    for field in group.fields.filter(
                        is_active=True,
                    ):

                        field_code = field.code

                        if field_permissions.get(
                            field_code,
                            False,
                        ):

                            saved_item[field_code] = item.get(
                                field_code,
                                "",
                            )

                        else:

                            saved_item[field_code] = previous_item.get(
                                field_code,
                                "",
                            )

                    saved_items.append(
                        saved_item
                    )

                current_data[group.code] = saved_items
        # -------------------------------------------------
        # 5. Persist FormData
        # -------------------------------------------------

        form_data.data = current_data

        form_data.save(
            update_fields=[
                "data",
                "updated_at",
            ],
        )

        return form_data



    @staticmethod
    @transaction.atomic
    def clear_form_for_step(
        *,
        instance,
        user,
    ):
        """
        Clear only fields that the current user
        is authorized to edit in the current step.
        """

        workflow = instance.workflow
        step = instance.current_step

        if step is None:
            raise ValidationError(
                "این Workflow مرحله فعلی ندارد."
            )

        # ---------------------------------------------------------
        # Current step execution
        # ---------------------------------------------------------

        current_step_execution = (
            instance.step_executions
            .filter(
                workflow_step=step,
            )
            .order_by("-performed_at")
            .first()
        )

        if current_step_execution is None:
            raise ValidationError(
                "اجرای مرحله فعلی Workflow پیدا نشد."
            )

        # Current step is submitted -> locked
        if current_step_execution.is_submitted:
            raise PermissionDenied(
                "این مرحله قبلاً ارسال شده و اطلاعات آن قابل حذف نیست."
            )

        form = (
            FormDefinition.objects.filter(
                workflow=workflow,
                is_active=True,
            )
            .prefetch_related(
                "sections__fields__access_rules",
            )
            .first()
        )

        if form is None:
            raise ValidationError(
                "برای این Workflow فرم فعالی تعریف نشده است."
            )

        form_data = (
            FormData.objects
            .filter(
                instance=instance,
            )
            .first()
        )

        if form_data is None:
            return

        roles = set(
            workflow.memberships.filter(
                user=user,
                is_active=True,
            ).values_list(
                "role",
                flat=True,
            )
        )

        current_data = dict(
            form_data.data or {}
        )

        editable_codes = set()

        # ---------------------------------------------------------
        # Collect all fields editable by current user
        # ---------------------------------------------------------

        for section in form.sections.filter(
            is_active=True,
        ):
            for field in section.fields.filter(
                is_active=True,
            ):
                access_rules = field.access_rules.filter(
                    step=step,
                )

                user_rule = access_rules.filter(
                    user=user,
                ).first()

                if user_rule:
                    can_edit = user_rule.can_edit

                else:
                    role_rules = access_rules.filter(
                        role__in=roles,
                        user__isnull=True,
                    )

                    can_edit = role_rules.filter(
                        can_edit=True,
                    ).exists()

                if can_edit:
                    editable_codes.add(
                        field.code
                    )

        # ---------------------------------------------------------
        # User has no editable fields
        # ---------------------------------------------------------

        if not editable_codes:
            raise PermissionDenied(
                "شما اجازه حذف اطلاعات این مرحله را ندارید."
            )
        if not editable_codes:
            raise PermissionDenied(
                "شما اجازه ویرایش هیچ فیلدی از این مرحله را ندارید."
            )
        # ---------------------------------------------------------
        # Remove only editable fields
        # ---------------------------------------------------------

        for code in editable_codes:
            current_data.pop(
                code,
                None,
            )

        form_data.data = current_data

        form_data.save(
            update_fields=[
                "data",
                "updated_at",
            ]
        )
