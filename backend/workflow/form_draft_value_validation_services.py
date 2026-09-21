from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.forms.utils import from_current_timezone

from .form_draft_payloads import NormalizedFormPayload, NormalizedRow
from .models import (
    FormData,
    FormField,
    FormRepeatableGroup,
    LookupItem,
    RepeatableRow,
    StaticChoiceItem,
)
from .repeatable_row_read_services import RepeatableRowReadService


class FormDraftValueValidationService:
    """
    Stage 12.3: validate submitted value integrity and SELECT dependencies.

    This service accepts incomplete data: omitted/empty values are not
    completeness errors. It validates only values that participate in the
    current save. Omitted non-editable values remain untouched and are not
    revalidated here.

    Repeatable persisted values are read through RepeatableRowReadService;
    legacy FormData is used only for top-level normal fields, which are still
    stored there during the migration.
    """

    EMPTY_VALUES = (None, "")

    @classmethod
    def validate_payload(
        cls,
        *,
        instance,
        form,
        normalized_payload: NormalizedFormPayload,
    ):
        cls._validate_normal_fields(
            instance=instance,
            form=form,
            values=normalized_payload.normal_fields,
        )

        groups_by_code = cls._root_groups_by_code(form=form)
        for group_code, rows in normalized_payload.repeatable_groups.items():
            group = groups_by_code.get(group_code)
            if group is None:
                raise ValidationError(
                    f"گروه تکرارشونده «{group_code}» در فرم فعال نیست."
                )

            cls._validate_rows(
                instance=instance,
                form=form,
                group=group,
                rows=rows,
                normalized_payload=normalized_payload,
            )

    @classmethod
    def _validate_normal_fields(cls, *, instance, form, values):
        fields_by_code = cls._normal_fields_by_code(form=form)

        for code, value in values.items():
            field = fields_by_code.get(code)
            if field is None:
                raise ValidationError(
                    f"فیلد «{code}» در فرم فعال نیست."
                )

            cls._validate_field_value(
                field=field,
                value=value,
            )

        cls._validate_dependencies(
            instance=instance,
            form=form,
            fields_by_code=fields_by_code,
            submitted_values=values,
            persisted_form_data=None,
        )

    @classmethod
    def _validate_rows(
        cls,
        *,
        instance,
        form,
        group,
        rows,
        normalized_payload,
    ):
        for row in rows:
            persisted_values = cls._persisted_row_values(row_id=row.row_id)
            fields_by_code = {
                field.code: field
                for field in group.fields.filter(is_active=True)
            }

            for code, value in row.fields.items():
                field = fields_by_code.get(code)
                if field is None:
                    raise ValidationError(
                        f"فیلد «{code}» در گروه «{group.name}» فعال نیست."
                    )

                cls._validate_field_value(
                    field=field,
                    value=value,
                )

            cls._validate_dependencies(
                instance=instance,
                form=form,
                fields_by_code=fields_by_code,
                submitted_values=row.fields,
                persisted_values=persisted_values,
            )

            for child_group_code, child_rows in row.child_groups.items():
                child_group = group.child_groups.filter(
                    code=child_group_code,
                    is_active=True,
                ).first()
                if child_group is None:
                    raise ValidationError(
                        f"گروه فرزند «{child_group_code}» در گروه «{group.name}» فعال نیست."
                    )

                cls._validate_rows(
                    instance=instance,
                    form=form,
                    group=child_group,
                    rows=child_rows,
                    normalized_payload=normalized_payload,
                )

    @classmethod
    def _validate_field_value(cls, *, field, value):
        if cls._is_empty(value):
            return

        if field.system_key != FormField.SystemKey.NONE:
            # System fields are validated by their owning domain/apply service.
            return

        field_type = field.field_type

        if field_type in (
            FormField.FieldType.TEXT,
            FormField.FieldType.TEXTAREA,
        ):
            if not isinstance(value, str):
                raise ValidationError(
                    f"مقدار فیلد «{field.label}» باید متنی باشد."
                )
            return

        if field_type == FormField.FieldType.NUMBER:
            cls._validate_number(field=field, value=value)
            return

        if field_type == FormField.FieldType.DATE:
            cls._validate_date(field=field, value=value)
            return

        if field_type == FormField.FieldType.DATETIME:
            cls._validate_datetime(field=field, value=value)
            return

        if field_type == FormField.FieldType.BOOLEAN:
            cls._validate_boolean(field=field, value=value)
            return

        if field_type == FormField.FieldType.SELECT:
            cls._validate_select(field=field, value=value)
            return

        raise ValidationError(
            f"نوع فیلد «{field.field_type}» برای اعتبارسنجی پشتیبانی نمی‌شود."
        )

    @staticmethod
    def _validate_number(*, field, value):
        try:
            decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError(
                f"مقدار فیلد «{field.label}» باید یک عدد معتبر باشد."
            )

        if not decimal_value.is_finite():
            raise ValidationError(
                f"مقدار فیلد «{field.label}» باید یک عدد معتبر باشد."
            )

    @staticmethod
    def _validate_date(*, field, value):
        if isinstance(value, datetime):
            raise ValidationError(
                f"مقدار فیلد «{field.label}» باید تاریخ باشد."
            )

        if isinstance(value, date):
            return

        if not isinstance(value, str):
            raise ValidationError(
                f"مقدار فیلد «{field.label}» باید تاریخ معتبر باشد."
            )

        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValidationError(
                f"مقدار فیلد «{field.label}» باید تاریخ معتبر باشد."
            )

    @staticmethod
    def _validate_datetime(*, field, value):
        if isinstance(value, datetime):
            return

        if not isinstance(value, str):
            raise ValidationError(
                f"مقدار فیلد «{field.label}» باید تاریخ و زمان معتبر باشد."
            )

        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise ValidationError(
                f"مقدار فیلد «{field.label}» باید تاریخ و زمان معتبر باشد."
            )

    @staticmethod
    def _validate_boolean(*, field, value):
        if isinstance(value, bool):
            return

        if isinstance(value, str) and value.strip().lower() in {
            "true",
            "false",
            "1",
            "0",
            "on",
            "off",
            "yes",
            "no",
        }:
            return

        if isinstance(value, int) and value in {0, 1}:
            return

        raise ValidationError(
            f"مقدار فیلد «{field.label}» باید بله/خیر معتبر باشد."
        )

    @classmethod
    def _validate_select(cls, *, field, value):
        if field.choice_source == FormField.ChoiceSource.STATIC:
            if not field.choice_static_set_id:
                raise ValidationError(
                    f"منبع گزینه‌های فیلد «{field.label}» تنظیم نشده است."
                )

            if not StaticChoiceItem.objects.filter(
                choice_set_id=field.choice_static_set_id,
                value=str(value),
                is_active=True,
            ).exists():
                raise ValidationError(
                    f"گزینه انتخاب‌شده برای فیلد «{field.label}» معتبر نیست."
                )
            return

        if field.choice_source == FormField.ChoiceSource.LOOKUP:
            if not field.choice_lookup_list_id:
                raise ValidationError(
                    f"منبع گزینه‌های فیلد «{field.label}» تنظیم نشده است."
                )

            if not LookupItem.objects.filter(
                lookup_list_id=field.choice_lookup_list_id,
                value=str(value),
                is_active=True,
            ).exists():
                raise ValidationError(
                    f"گزینه انتخاب‌شده برای فیلد «{field.label}» معتبر نیست."
                )
            return

        if field.choice_source == FormField.ChoiceSource.MODEL:
            cls._validate_model_select(field=field, value=value)
            return

        raise ValidationError(
            f"منبع گزینه‌های فیلد «{field.label}» معتبر نیست."
        )

    @staticmethod
    def _validate_model_select(*, field, value):
        if not field.choice_model_id or not field.choice_value_field:
            raise ValidationError(
                f"تنظیمات منبع مدل فیلد «{field.label}» ناقص است."
            )

        model_class = field.choice_model.model_class()
        if model_class is None:
            raise ValidationError(
                f"مدل مقصد فیلد «{field.label}» معتبر نیست."
            )

        try:
            model_field = model_class._meta.get_field(
                field.choice_value_field
            )
        except Exception:
            raise ValidationError(
                f"فیلد مقدار مدل مقصد برای «{field.label}» معتبر نیست."
            )

        if not getattr(model_field, "concrete", False):
            raise ValidationError(
                f"فیلد مقدار مدل مقصد برای «{field.label}» معتبر نیست."
            )

        if not model_class.objects.filter(
            **{field.choice_value_field: str(value)}
        ).exists():
            raise ValidationError(
                f"مقدار انتخاب‌شده برای فیلد «{field.label}» در مدل مقصد وجود ندارد."
            )

    @classmethod
    def _validate_dependencies(
        cls,
        *,
        instance,
        form,
        fields_by_code,
        submitted_values,
        persisted_values,
    ):
        for field in fields_by_code.values():
            if (
                not field.is_active
                or field.field_type != FormField.FieldType.SELECT
                or field.choice_parent_field_id is None
                or field.code not in submitted_values
            ):
                continue

            child_value = submitted_values.get(field.code)
            if cls._is_empty(child_value):
                continue

            parent_field = field.choice_parent_field

            if parent_field.repeatable_group_id:
                if parent_field.repeatable_group_id != field.repeatable_group_id:
                    # Cross-repeatable-group dependency is not representable
                    # by the current payload model.
                    continue

                parent_value = cls._value_for_field(
                    field=parent_field,
                    submitted_values=submitted_values,
                    persisted_values=persisted_values,
                )
            elif field.repeatable_group_id:
                parent_value = cls._top_level_persisted_or_submitted_value(
                    field=parent_field,
                    instance=instance,
                    submitted_values=None,
                )
            else:
                parent_value = cls._top_level_persisted_or_submitted_value(
                    field=parent_field,
                    instance=instance,
                    submitted_values=submitted_values,
                )

            if cls._is_empty(parent_value):
                raise ValidationError(
                    f"ابتدا گزینه فیلد «{parent_field.label}» را انتخاب کنید."
                )

            allowed_values = cls._dependent_allowed_values(
                field=field,
                parent_value=parent_value,
            )

            if str(child_value).strip() not in allowed_values:
                raise ValidationError(
                    f"گزینه انتخاب‌شده برای فیلد «{field.label}» با فیلد والد سازگار نیست."
                )

    @classmethod
    def _top_level_persisted_or_submitted_value(
        cls,
        *,
        field,
        instance,
        submitted_values,
    ):
        if submitted_values is not None and field.code in submitted_values:
            return submitted_values.get(field.code)

        form_data = (
            FormData.objects
            .filter(instance=instance)
            .first()
        )
        if form_data:
            return (form_data.data or {}).get(field.code, "")

        return ""

    @classmethod
    def _value_for_field(
        cls,
        *,
        field,
        submitted_values,
        persisted_values,
    ):
        if field.code in submitted_values:
            return submitted_values.get(field.code)

        return (persisted_values or {}).get(field.code, "")

    @classmethod
    def _persisted_row_values(cls, *, row_id):
        if row_id is None:
            return {}

        row = RepeatableRow.objects.filter(pk=row_id).first()
        if row is None:
            return {}

        reconstructed = RepeatableRowReadService.reconstruct_row(row=row)
        return {
            item["code"]: item["value"]
            for item in reconstructed["fields"]
        }

    @staticmethod
    def _dependent_allowed_values(*, field, parent_value):
        parent_value = str(parent_value)

        if field.choice_source == FormField.ChoiceSource.LOOKUP:
            return {
                str(item.value)
                for item in LookupItem.objects.filter(
                    lookup_list_id=field.choice_lookup_list_id,
                    parent__value=parent_value,
                    parent__lookup_list_id=field.choice_lookup_list_id,
                    is_active=True,
                )
            }

        if field.choice_source == FormField.ChoiceSource.MODEL:
            parent_field = field.choice_parent_field
            parent_model = parent_field.choice_model.model_class()
            child_model = field.choice_model.model_class()

            if parent_model is None or child_model is None:
                return set()

            try:
                parent_obj = parent_model.objects.filter(
                    **{
                        parent_field.choice_value_field: parent_value,
                    }
                ).first()
            except Exception:
                return set()

            if parent_obj is None:
                return set()

            try:
                queryset = child_model.objects.filter(
                    **{
                        field.choice_filter_field: parent_obj,
                    }
                )
            except Exception:
                return set()

            return {
                str(getattr(obj, field.choice_value_field))
                for obj in queryset
            }

        return set()

    @staticmethod
    def _normal_fields_by_code(*, form):
        return {
            field.code: field
            for section in form.sections.filter(is_active=True)
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            )
        }

    @staticmethod
    def _root_groups_by_code(*, form):
        return {
            group.code: group
            for section in form.sections.filter(is_active=True)
            for group in section.repeatable_groups.filter(
                is_active=True,
                parent_group__isnull=True,
            )
        }

    @staticmethod
    def _is_empty(value):
        return value is None or (
            isinstance(value, str) and not value.strip()
        )
