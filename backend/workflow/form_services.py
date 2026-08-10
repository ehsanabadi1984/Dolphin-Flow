from django.core.exceptions import ValidationError
from django.db import transaction

from .models import FormData, FormDefinition


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

            for field in section.fields.filter(
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

            if fields:
                sections.append(
                    {
                        "section": section,
                        "fields": fields,
                    }
                )

        return {
            "form": form,
            "sections": sections,
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
        Save only fields that the current user
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
                    editable_codes.add(
                        field.code
                    )

        for code in editable_codes:
            if code in submitted_data:
                current_data[code] = submitted_data[code]

        form_data.data = current_data

        form_data.save(
            update_fields=[
                "data",
                "updated_at",
            ],
        )

        return form_data
