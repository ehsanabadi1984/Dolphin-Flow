from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .sla_services import SLAService

from .instance_device_services import InstanceDeviceService
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

        Example:

            devices_0_imei = 123
            devices_0_device_model_id = 5
            devices_1_imei = 456

        becomes:

            [
                {
                    "imei": "123",
                    "device_model_id": "5",
                },
                {
                    "imei": "456",
                },
            ]
        """

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

        now = timezone.now()

        current_step_execution.is_submitted = True
        current_step_execution.submitted_at = now
        current_step_execution.save(
            update_fields=[
                "is_submitted",
                "submitted_at",
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

            print("=== DEBUG MODEL CHOICES ===")
            print("field.code:", field.code)
            print("field.name:", field.name)
            print("choice_model:", field.choice_model)
            print("choice_model_id:", field.choice_model_id)
            print("choice_value_field:", field.choice_value_field)
            print("choice_label_field:", field.choice_label_field)

            if not field.choice_model_id:
                print("MODEL DEBUG: NO choice_model_id")
                return []

            model_class = field.choice_model.model_class()
            print("model_class:", model_class)

            if not model_class:
                print("MODEL DEBUG: NO model_class")
                return []

            queryset = model_class.objects.all()

            print("queryset count:", queryset.count())
            print(
                "queryset objects:",
                list(queryset.values()[:10]),
            )

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

                if not can_view:
                    continue

                if is_submitted:
                    can_edit = False

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

                    if not can_view:
                        continue

                    effective_can_edit = (
                        can_edit
                        and group_can_edit
                    )
                    if effective_can_edit:
                        group_has_editable_fields = True

                    field_data = {
                        "field": field,
                        "can_edit": can_edit,
                        "choices": (
                            DynamicFormService._get_field_choices(field)
                            if field.field_type == field.FieldType.SELECT
                            else []
                        ),
                    }

                    # if (
                    #     field.field_type == field.FieldType.SELECT
                    #     and field.choice_source == field.ChoiceSource.LOOKUP
                    #     and field.choice_lookup_list_id
                    # ):
                    #     field_data["choices"] = list(
                    #         field.choice_lookup_list.items
                    #         .filter(
                    #             is_active=True,
                    #         )
                    #         .order_by(
                    #             "order",
                    #             "id",
                    #         )
                    #         .values_list(
                    #             "value",
                    #             "label",
                    #         )
                    #     )
#-----------------------Debut-------------------------------

                    print(
                        "DEBUG GROUP FIELD:",
                        field.code,
                        field.name,
                        field.field_type,
                        field.choice_source,
                    )

                    if field.code == "device_type":
                        field_data["device_types"] = (
                            DeviceType.objects
                            .filter(is_active=True)
                            .order_by("name")
                        )

#---------------------End-Debug-----------------------------

                    # if field.code == "device_model_id":
                    #     field_data["device_models"] = (
                    #         DeviceModel.objects
                    #         .filter(is_active=True)
                    #         .select_related("device_type")
                    #         .order_by("name")
                    #     )

                    # if field.code == "device_type":
                    #     field_data["device_types"] = (
                    #         DeviceType.objects
                    #         .filter(is_active=True)
                    #         .order_by("name")
                    #     )
#-----------------------------------Debug-------------------------------------------
                    if field.code == "device_type":
                        field_data["device_types"] = (
                            DeviceType.objects
                            .filter(is_active=True)
                            .order_by("name")
                        )

                        print(
                            "DEBUG DEVICE TYPE:",
                            field.code,
                            list(
                                field_data["device_types"].values(
                                    "id",
                                    "name",
                                )
                            ),
                        )

#--------------------------------End-Debug-------------------------------------------


                    group_fields.append(field_data)
                    
                if not group_fields:
                    continue

                # Saved repeatable items.
                #
                # Device groups use InstanceDevice
                # as their source of truth.
                #

                if group.group_type == FormRepeatableGroup.GroupType.DEVICE:
                    instance_devices = (
                        InstanceDeviceService.get_devices_for_instance(
                            instance=instance,
                        )
                    )

                    device_model_choices = [
                        (str(device_model.id), device_model.name)
                        for device_model in DeviceModel.objects.filter(
                            is_active=True,
                        )
                    ]

                    items = []

                    for instance_device in instance_devices:
                        imei = ""

                        for identifier in instance_device.device.identifiers.all():
                            if identifier.identifier_type == "IMEI":
                                imei = identifier.value
                                break

                        device_type = (
                            instance_device
                            .device
                            .device_model
                            .device_type
                        )

                        device_model = (
                            instance_device
                            .device
                            .device_model
                        )

                        device_type = (
                            instance_device
                            .device
                            .device_model
                            .device_type
                        )

                        device_model = (
                            instance_device
                            .device
                            .device_model
                        )

                        values = {
                            "device_type": device_type.id,
                            "device_type_display": device_type.name,

                            "device_model_id": device_model.id,
                            "device_model_id_display": device_model.name,

                            "imei": imei,

                            "problem": instance_device.reported_problem,
                            "description": instance_device.description,
                        }
                        
                        item_fields = []

                        for field_info in group_fields:
                            field = field_info["field"]

                            item_fields.append(
                                {
                                    "field": field,
                                    "can_edit": field_info["can_edit"],
                                    "value": values.get(
                                        field.code,
                                        "",
                                    ),

                                    "display_value": values.get(
                                        f"{field.code}_display",
                                        values.get(field.code, ""),
                                    ),

                                    "choices": (
                                        DynamicFormService._get_field_choices(field)
                                        if field.field_type == field.FieldType.SELECT
                                        else []
                                    ),
                                    "device_types": field_info.get(
                                        "device_types",
                                        [],
                                    ),
                                    "device_models": field_info.get(
                                        "device_models",
                                        [],
                                    ),
                                }
                            )
                        items.append(
                            {
                                "instance_device_id": instance_device.pk,
                                "device_id": instance_device.device.pk,
                                "device_model_id": (
                                    instance_device.device.device_model_id
                                ),
                                "device_type": (
                                    instance_device
                                    .device
                                    .device_model
                                    .device_type
                                    .name
                                ),
                                "device_model": str(
                                    instance_device.device.device_model
                                ),
                                "reported_problem": (
                                    instance_device.reported_problem
                                ),
                                "warranty_status": (
                                    instance_device.warranty_status
                                ),
                                "status": instance_device.status,
                                "identifiers": [
                                    {
                                        "type": identifier.identifier_type,
                                        "value": identifier.value,
                                    }
                                    for identifier
                                    in instance_device.device.identifiers.all()
                                ],
                                "fields": item_fields,
                            }
                        )

                                    
                    if not items:
                        item_fields = []

                        for field_info in group_fields:
                            field = field_info["field"]

                            item_fields.append(
                                {
                                    "field": field,
                                    "can_edit": field_info["can_edit"],
                                    "value": "",
                                    "device_types": field_info.get(
                                        "device_types",
                                        [],
                                    ),
                                    "device_models": field_info.get(
                                        "device_models",
                                        [],
                                    ),
                                }
                            )

                        items.append(
                            {
                                "instance_device_id": "",
                                "device_id": "",
                                "device_model_id": "",
                                "device_type": "",
                                "device_model": "",
                                "reported_problem": "",
                                "warranty_status": "",
                                "status": "",
                                "identifiers": [],
                                "fields": item_fields,
                            }
                        )
                else:
                    raw_items = data.get(
                        group.code,
                        [],
                    )

                    if not isinstance(raw_items, list):
                        raw_items = []

                    if not raw_items:
                        raw_items = [
                            {}
                        ]

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
                                    "can_edit": field_info["can_edit"],
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
        # Activate DRAFT on first real form save
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

        # ---------------------------------------------------------
        # Submitted step is locked
        # ---------------------------------------------------------

        if current_step_execution.is_submitted:
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

        form_data, _ = FormData.objects.get_or_create(
            instance=instance,
            defaults={
                "data": {},
            },
        )

        current_data = dict(form_data.data or {})

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
                    required_errors.append(f"فیلد «{field.label}» الزامی است.")

        if required_errors:
            raise ValidationError(required_errors)

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

                    editable_fields = set()

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

                        if can_edit:
                            editable_fields.add(field.code)

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
                                ).get(
                                    pk=instance_device_id,
                                    instance=instance,
                                )
                            except InstanceDevice.DoesNotExist:
                                raise ValidationError(
                                    "دستگاه مربوط به این فرآیند پیدا نشد."
                                )

                            # ---------------------------------------------
                            # IMEI
                            # ---------------------------------------------

                            if "imei" in item:
                                submitted_imei = str(item["imei"]).strip()

                                current_imei = (
                                    instance_device.device.identifiers.filter(
                                        identifier_type="IMEI",
                                    )
                                    .values_list(
                                        "value",
                                        flat=True,
                                    )
                                    .first()
                                )

                                if (
                                    "imei" not in editable_fields
                                    and submitted_imei != current_imei
                                ):
                                    raise ValidationError(
                                        "شما اجازه ویرایش IMEI این دستگاه را ندارید."
                                    )

                            # ---------------------------------------------
                            # Device model
                            # ---------------------------------------------

                            if "device_model_id" in item:
                                submitted_model_id = item["device_model_id"]

                                current_model_id = (
                                    instance_device.device.device_model_id
                                )

                                if (
                                    "device_model_id" not in editable_fields
                                    and submitted_model_id != current_model_id
                                ):
                                    raise ValidationError(
                                        "شما اجازه ویرایش مدل این دستگاه را ندارید."
                                    )

                            # ---------------------------------------------
                            # Reported problem
                            # ---------------------------------------------

                            if (
                                "reported_problem" in item
                                and "reported_problem" not in editable_fields
                                and item["reported_problem"]
                                != instance_device.reported_problem
                            ):
                                raise ValidationError(
                                    "شما اجازه ویرایش شرح مشکل این دستگاه را ندارید."
                                )

                            if (
                                "description" in item
                                and "description" not in editable_fields
                                and item["description"] != instance_device.description
                            ):
                                raise ValidationError(
                                    "شما اجازه ویرایش توضیحات تکمیلی این دستگاه را ندارید."
                                )

                            # ---------------------------------------------
                            # Warranty status
                            # ---------------------------------------------

                            if (
                                "warranty_status" in item
                                and "warranty_status" not in editable_fields
                                and item["warranty_status"]
                                != instance_device.warranty_status
                            ):
                                raise ValidationError(
                                    "شما اجازه ویرایش وضعیت گارانتی "
                                    "این دستگاه را ندارید."
                                )

                            # ---------------------------------------------
                            # Status
                            # ---------------------------------------------

                            if (
                                "status" in item
                                and "status" not in editable_fields
                                and item["status"] != instance_device.status
                            ):
                                raise ValidationError(
                                    "شما اجازه ویرایش وضعیت این دستگاه را ندارید."
                                )

                            # ---------------------------------------------
                            # Apply editable fields only
                            # ---------------------------------------------

                            update_fields = []
                            if "imei" in editable_fields and "imei" in item:
                                submitted_imei = str(
                                    item["imei"]
                                ).strip()

                                current_imei_identifier = (
                                    instance_device
                                    .device
                                    .identifiers
                                    .filter(
                                        identifier_type="IMEI",
                                    )
                                    .first()
                                )

                                if current_imei_identifier is None:
                                    raise ValidationError(
                                        "IMEI فعلی دستگاه پیدا نشد."
                                    )

                                if submitted_imei != current_imei_identifier.value:
                                    existing_identifier = (
                                        DeviceIdentifier.objects
                                        .filter(
                                            identifier_type="IMEI",
                                            value=submitted_imei,
                                        )
                                        .exclude(
                                            device=instance_device.device,
                                        )
                                        .first()
                                    )

                                    if existing_identifier:
                                        raise ValidationError(
                                            "این IMEI قبلاً برای دستگاه دیگری ثبت شده است."
                                        )

                                    current_imei_identifier.value = submitted_imei
                                    current_imei_identifier.save(
                                        update_fields=["value"],
                                    )

                            if (
                                "reported_problem" in editable_fields
                                and "reported_problem" in item
                            ):
                                instance_device.reported_problem = item[
                                    "reported_problem"
                                ]
                                update_fields.append("reported_problem")

                            if (
                                "description" in editable_fields
                                and "description" in item
                            ):
                                instance_device.description = item[
                                    "description"
                                ]
                                update_fields.append("description")

                            if (
                                "warranty_status" in editable_fields
                                and "warranty_status" in item
                            ):
                                instance_device.warranty_status = item[
                                    "warranty_status"
                                ]
                                update_fields.append("warranty_status")

                            if "status" in editable_fields and "status" in item:
                                instance_device.status = item["status"]
                                update_fields.append("status")

                            if update_fields:
                                update_fields.append("updated_at")

                                instance_device.save(update_fields=update_fields)

                            # Existing device is done.
                            continue

                        # -------------------------------------------------
                        # New device
                        # -------------------------------------------------
                        if not can_add:
                            raise ValidationError(
                                "شما اجازه افزودن مورد جدید به این گروه را ندارید."
                            )
                        if "imei" not in editable_fields:
                            raise ValidationError(
                                "شما اجازه ثبت IMEI دستگاه را ندارید."
                            )

                        if "device_model_id" not in editable_fields:
                            raise ValidationError("شما اجازه ثبت مدل دستگاه را ندارید.")

                        imei = item.get("imei")

                        device_model_id = item.get("device_model_id")

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

                        InstanceDeviceService.add_device_by_imei(
                            instance=instance,
                            imei=imei,
                            device_model=device_model,
                            reported_problem=item.get(
                                "reported_problem",
                                "",
                            ),
                            warranty_status=item.get(
                                "warranty_status",
                                "",
                            ),
                            status=item.get(
                                "status",
                                "",
                            ),
                        )

                    # Device group is persisted in relational models.
                    # It must not be copied into FormData.
                    continue
                # -------------------------------------------------
                # Persist non-device repeatable groups
                # -------------------------------------------------

                current_data[group.code] = items
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