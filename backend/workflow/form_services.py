from django.core.exceptions import ValidationError
from django.db import transaction

from .instance_device_services import InstanceDeviceService
from .models import (
    DeviceModel,
    FormData,
    FormDefinition,
)


class DynamicFormService:
    """
    Build and persist the dynamic form structure
    for a specific workflow instance and step.
    """

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

        form = (
            FormDefinition.objects
            .filter(
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

        form_data = (
            FormData.objects
            .filter(
                instance=instance,
            )
            .first()
        )

        data = (
            form_data.data
            if form_data
            else {}
        )

        has_saved_data = bool(data)

        roles = set(
            workflow.memberships
            .filter(
                user=user,
                is_active=True,
            )
            .values_list(
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

                user_rule = (
                    access_rules
                    .filter(
                        user=user,
                    )
                    .first()
                )

                if user_rule:
                    can_view = user_rule.can_view
                    can_edit = user_rule.can_edit

                else:
                    role_rules = access_rules.filter(
                        role__in=roles,
                        user__isnull=True,
                    )

                    can_view = (
                        role_rules
                        .filter(
                            can_view=True,
                        )
                        .exists()
                    )

                    can_edit = (
                        role_rules
                        .filter(
                            can_edit=True,
                        )
                        .exists()
                    )

                if not can_view:
                    continue

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

                    user_rule = (
                        access_rules
                        .filter(
                            user=user,
                        )
                        .first()
                    )

                    if user_rule:
                        can_view = user_rule.can_view
                        can_edit = user_rule.can_edit

                    else:
                        role_rules = access_rules.filter(
                            role__in=roles,
                            user__isnull=True,
                        )

                        can_view = (
                            role_rules
                            .filter(
                                can_view=True,
                            )
                            .exists()
                        )

                        can_edit = (
                            role_rules
                            .filter(
                                can_edit=True,
                            )
                            .exists()
                        )

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
                    instance_devices = (
                        InstanceDeviceService
                        .get_devices_for_instance(
                            instance=instance,
                        )
                    )

                    items = [
                        {
                            "instance_device_id": (
                                instance_device.pk
                            ),
                            "device_id": (
                                instance_device.device.pk
                            ),
                            "device_model_id": (
                                instance_device
                                .device
                                .device_model_id
                            ),
                            "device_type": (
                                instance_device
                                .device
                                .device_model
                                .device_type
                                .name
                            ),
                            "device_model": (
                                str(
                                    instance_device
                                    .device
                                    .device_model
                                )
                            ),
                            "reported_problem": (
                                instance_device
                                .reported_problem
                            ),
                            "warranty_status": (
                                instance_device
                                .warranty_status
                            ),
                            "status": (
                                instance_device.status
                            ),
                            "identifiers": [
                                {
                                    "type": (
                                        identifier
                                        .identifier_type
                                    ),
                                    "value": (
                                        identifier.value
                                    ),
                                }
                                for identifier
                                in instance_device
                                .device
                                .identifiers
                                .all()
                            ],
                        }
                        for instance_device
                        in instance_devices
                    ]

                else:
                    items = data.get(
                        group.code,
                        [],
                    )

                    if not isinstance(items, list):
                        items = []

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

        form = (
            FormDefinition.objects
            .filter(
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
            raise ValidationError(
                "برای این Workflow فرمی تعریف نشده است."
            )

        roles = set(
            workflow.memberships
            .filter(
                user=user,
                is_active=True,
            )
            .values_list(
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

        current_data = dict(
            form_data.data or {}
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

                user_rule = (
                    access_rules
                    .filter(
                        user=user,
                    )
                    .first()
                )

                if user_rule:
                    can_edit = user_rule.can_edit

                else:
                    role_rules = access_rules.filter(
                        role__in=roles,
                        user__isnull=True,
                    )

                    can_edit = (
                        role_rules
                        .filter(
                            can_edit=True,
                        )
                        .exists()
                    )

                if can_edit:
                    editable_codes.add(
                        field.code
                    )

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
                        f"فیلد «{field.label}» الزامی است."
                    )

        if required_errors:
            raise ValidationError(
                required_errors
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
                # Verify repeatable-group edit access
                # -------------------------------------------------

                group_can_edit = False

                for field in group.fields.filter(
                    is_active=True,
                ):
                    access_rules = field.access_rules.filter(
                        step=step,
                    )

                    user_rule = (
                        access_rules
                        .filter(
                            user=user,
                        )
                        .first()
                    )

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


                items = submitted_data.get(
                    group.code,
                    [],
                )

                if not isinstance(items, list):
                    raise ValidationError(
                        f"اطلاعات گروه «{group.name}» "
                        "باید به صورت لیست ارسال شود."
                    )

                # -----------------------------------------
                # Device repeatable group
                # -----------------------------------------

                if group.code == "devices":

                    for item in items:

                        if not isinstance(item, dict):
                            raise ValidationError(
                                "اطلاعات هر دستگاه باید "
                                "به صورت یک شیء باشد."
                            )

                        imei = item.get("imei")

                        device_model_id = item.get(
                            "device_model_id"
                        )

                        reported_problem = item.get(
                            "reported_problem",
                            "",
                        )

                        if not imei:
                            raise ValidationError(
                                "IMEI دستگاه الزامی است."
                            )

                        if not device_model_id:
                            raise ValidationError(
                                "مدل دستگاه الزامی است."
                            )

                        
                        try:
                            device_model = (
                                DeviceModel.objects.get(
                                    pk=device_model_id,
                                    is_active=True,
                                )
                            )
                        except DeviceModel.DoesNotExist:
                            raise ValidationError(
                                "مدل دستگاه معتبر نیست."
                            )

                        InstanceDeviceService.add_device_by_imei(
                            instance=instance,
                            imei=imei,
                            device_model=device_model,
                            reported_problem=reported_problem,
                            warranty_status=item.get(
                                "warranty_status",
                                "",
                            ),
                            status=item.get(
                                "status",
                                "",
                            ),
                        )

                else:
                    # Other repeatable groups are still kept
                    # in FormData until their dedicated
                    # persistence service is implemented.
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

        form = (
            FormDefinition.objects
            .filter(
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
            .filter(instance=instance)
            .first()
        )

        if form_data is None:
            return

        roles = set(
            workflow.memberships
            .filter(
                user=user,
                is_active=True,
            )
            .values_list(
                "role",
                flat=True,
            )
        )

        current_data = dict(
            form_data.data or {}
        )

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

                user_rule = (
                    access_rules
                    .filter(
                        user=user,
                    )
                    .first()
                )

                if user_rule:
                    can_edit = user_rule.can_edit

                else:
                    role_rules = access_rules.filter(
                        role__in=roles,
                        user__isnull=True,
                    )

                    can_edit = (
                        role_rules
                        .filter(
                            can_edit=True,
                        )
                        .exists()
                    )

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
        