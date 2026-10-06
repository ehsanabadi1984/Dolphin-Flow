from collections import defaultdict

from .form_services import DynamicFormService
from .models import FormField, LookupItem, StaticChoiceItem


class FormFieldValueResolver:
    """
    Resolve normal FormField values for presentation without changing the
    broader DynamicFormService contract.

    SELECT values are resolved in batches because DynamicFormService's
    legacy display helper materializes the complete choice set/model.
    """

    @staticmethod
    def build_display_cache(*, fields, data):
        fields = list(fields)
        data = data or {}

        cache = {}
        static_references = defaultdict(set)
        lookup_references = defaultdict(set)
        model_references = defaultdict(set)
        model_fields = {}

        for field in fields:
            if field.field_type != FormField.FieldType.SELECT:
                continue

            value = data.get(field.code)
            if value in ("", None, []):
                continue

            if field.choice_source == FormField.ChoiceSource.STATIC:
                if field.choice_static_set_id:
                    static_references[field.choice_static_set_id].add(str(value))
                continue

            if field.choice_source == FormField.ChoiceSource.LOOKUP:
                if field.choice_lookup_list_id:
                    lookup_references[field.choice_lookup_list_id].add(str(value))
                continue

            if (
                field.choice_source == FormField.ChoiceSource.MODEL
                and field.choice_model_id
            ):
                config = (
                    field.choice_model_id,
                    field.choice_value_field,
                    field.choice_label_field,
                )
                model_references[config].add(str(value))
                model_fields[config] = field

        if static_references:
            items = StaticChoiceItem.objects.filter(
                choice_set_id__in=static_references.keys(),
                value__in={
                    value
                    for values in static_references.values()
                    for value in values
                },
                is_active=True,
            ).values("choice_set_id", "value", "label")

            for item in items:
                cache[("STATIC", item["choice_set_id"], str(item["value"]))] = (
                    item["label"]
                )

        if lookup_references:
            items = LookupItem.objects.filter(
                lookup_list_id__in=lookup_references.keys(),
                value__in={
                    value
                    for values in lookup_references.values()
                    for value in values
                },
                is_active=True,
            ).values("lookup_list_id", "value", "label")

            for item in items:
                cache[("LOOKUP", item["lookup_list_id"], str(item["value"]))] = (
                    item["label"]
                )

        for config, reference_ids in model_references.items():
            field = model_fields[config]
            model_class = field.choice_model.model_class()
            if model_class is None:
                continue

            objects = (
                model_class.objects
                .filter(**{f"{field.choice_value_field}__in": reference_ids})
                .order_by("pk")
                .values(field.choice_value_field, field.choice_label_field)
            )

            for obj in objects:
                cache[
                    (
                        "MODEL",
                        field.pk,
                        str(obj[field.choice_value_field]),
                    )
                ] = str(obj[field.choice_label_field])

        return cache

    @staticmethod
    def get_display_value(*, field, value, display_cache):
        if value in ("", None, []):
            return ""

        if field.field_type != FormField.FieldType.SELECT:
            return DynamicFormService._get_display_value(
                field=field,
                value=value,
            )

        if field.choice_source == FormField.ChoiceSource.STATIC:
            label = display_cache.get(
                ("STATIC", field.choice_static_set_id, str(value))
            )
            return label if label is not None else str(value)

        if field.choice_source == FormField.ChoiceSource.LOOKUP:
            label = display_cache.get(
                ("LOOKUP", field.choice_lookup_list_id, str(value))
            )
            return label if label is not None else str(value)

        if field.choice_source == FormField.ChoiceSource.MODEL:
            label = display_cache.get(
                ("MODEL", field.pk, str(value))
            )
            return label if label is not None else str(value)

        return str(value)
