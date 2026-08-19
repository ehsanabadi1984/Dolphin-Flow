from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .instance_device_services import InstanceDeviceService
from .models import (
    DeviceModel,
    FormData,
    FormDefinition,
    InstanceDevice,
    DeviceIdentifier,
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

        return current_step_execution

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

        has_saved_data = bool(data)

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

                if is_submitted:
                    can_edit = False

                fields.append(
                    {
                        "field": field,
                        "can_edit": can_edit,
                        "value": data.get(
                            field.code,
                            "",
                        ),
                    }
                )

            # -------------------------------------------------
            # Repeatable groups
            # -------------------------------------------------

            repeatable_groups = []

            for group in section.repeatable_groups.filter(
                is_active=True,
            ):
                group_fields = []

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


                    if step_is_submitted:
                        can_edit = False

                    if not can_view:
                        continue

                    group_fields.append(
                        {
                            "field": field,
                            "can_edit": can_edit,
                        }
                    )

                if not group_fields:
                    continue

                # Saved repeatable items.
                #
                # Device groups use InstanceDevice
                # as their source of truth.
                #

                if group.code == "devices":
                    instance_devices = InstanceDeviceService.get_devices_for_instance(
                        instance=instance,
                    )

                    items = [
                        {
                            "instance_device_id": (instance_device.pk),
                            "device_id": (instance_device.device.pk),
                            "device_model_id": (instance_device.device.device_model_id),
                            "device_type": (
                                instance_device.device.device_model.device_type.name
                            ),
                            "device_model": (str(instance_device.device.device_model)),
                            "reported_problem": (instance_device.reported_problem),
                            "warranty_status": (instance_device.warranty_status),
                            "status": (instance_device.status),
                            "identifiers": [
                                {
                                    "type": (identifier.identifier_type),
                                    "value": (identifier.value),
                                }
                                for identifier in instance_device.device.identifiers.all()
                            ],
                        }
                        for instance_device in instance_devices
                    ]

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

        return {
            "form": form,
            "sections": sections,
            "has_saved_data": has_saved_data,
            "is_submitted": step_is_submitted,
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
            raise ValidationError("این Workflow مرحله فعلی ندارد.")
        
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
                "اجرای مرحله فعلی این Workflow پیدا نشد."
            )

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
                # Verify repeatable-group edit access
                # -------------------------------------------------

                group_can_edit = False

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
                        if user_rule.can_edit:
                            group_can_edit = True
                            break

                    else:
                        role_rules = access_rules.filter(
                            role__in=roles,
                            user__isnull=True,
                            can_edit=True,
                        )

                        if role_rules.exists():
                            group_can_edit = True
                            break

                if not group_can_edit:
                    if group.code in submitted_data:
                        raise ValidationError(
                            f"شما اجازه ویرایش گروه «{group.name}» را ندارید."
                        )

                    continue

                # -------------------------------------------------
                # Process repeatable group
                # -------------------------------------------------

                items = DynamicFormService._parse_repeatable_data(
                    submitted_data=submitted_data,
                    group_code=group.code,
                )      

                # -----------------------------------------
                # Device repeatable group
                # -----------------------------------------

                if group.code == "devices":
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

                    for item in items:
                        if not isinstance(item, dict):
                            raise ValidationError(
                                "اطلاعات هر دستگاه باید به صورت یک شیء باشد."
                            )

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
            raise ValidationError("این Workflow مرحله فعلی ندارد.")

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
            raise ValidationError("برای این Workflow فرم فعالی تعریف نشده است.")

        form_data = FormData.objects.filter(instance=instance).first()

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

        current_data = dict(form_data.data or {})

        editable_codes = set()

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
                    editable_codes.add(field.code)

        for code in editable_codes:
            current_data.pop(code, None)

        form_data.data = current_data
        form_data.save(
            update_fields=[
                "data",
                "updated_at",
            ]
        )
