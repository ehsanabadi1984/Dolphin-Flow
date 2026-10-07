from django import forms
from django.contrib import admin
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html

from .admin import dolphin_admin_site
from .history_models import HistoryConfiguration, HistoryField, HistoryRecord
from .models import Device, FormField, FormRepeatableGroup


class HistoryFieldChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        parts = [obj.section.name]
        if obj.repeatable_group_id:
            parts.append(obj.repeatable_group.name)
        parts.append(obj.label)
        return " → ".join(parts)


class HistoryGroupChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.section.name} → {obj.label or obj.name}"


class HistoryConfigurationForm(forms.ModelForm):
    history_fields = HistoryFieldChoiceField(
        queryset=FormField.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="فیلدهای ثبت در تاریخچه",
        help_text="فیلدهایی را که باید هنگام ثبت History در snapshot ذخیره شوند انتخاب کنید.",
    )

    class Meta:
        model = HistoryConfiguration
        fields = (
            "form",
            "name",
            "is_active",
            "history_fields",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        form_id = self.instance.form_id if self.instance and self.instance.pk else None
        if form_id:
            fields = (
                FormField.objects
                .filter(
                    section__form_id=form_id,
                    section__is_active=True,
                    is_active=True,
                )
                .select_related("section", "repeatable_group")
                .order_by(
                    "section__order",
                    "repeatable_group__order",
                    "order",
                    "id",
                )
            )
            groups = (
                FormRepeatableGroup.objects
                .filter(
                    section__form_id=form_id,
                    section__is_active=True,
                    is_active=True,
                )
                .select_related("section", "parent_group")
                .order_by(
                    "section__order",
                    "order",
                    "id",
                )
            )
            self.fields["history_groups"].queryset = groups
            self.fields["history_fields"].queryset = fields

            enabled_field_ids = set(
                HistoryField.objects
                .filter(
                    configuration=self.instance,
                    is_enabled=True,
                    form_field__section__form_id=form_id,
                    form_field__section__is_active=True,
                    form_field__is_active=True,
                )
                .values_list("form_field_id", flat=True)
            )
            self.initial["history_fields"] = enabled_field_ids

            group_ids = {group.pk for group in groups}
            group_parent_ids = {
                group.pk: group.parent_group_id
                for group in groups
            }
            group_field_ids = {}
            for form_field in fields:
                if form_field.repeatable_group_id:
                    group_field_ids.setdefault(
                        form_field.repeatable_group_id,
                        set(),
                    ).add(form_field.pk)

            def descendants(group_id):
                result = {group_id}
                changed = True
                while changed:
                    changed = False
                    for candidate_id, parent_id in group_parent_ids.items():
                        if parent_id in result and candidate_id not in result:
                            result.add(candidate_id)
                            changed = True
                return result

            selected_group_ids = []
            for group_id in group_ids:
                descendant_ids = descendants(group_id)
                field_ids = set().union(
                    *(group_field_ids.get(descendant_id, set()) for descendant_id in descendant_ids)
                )
                if field_ids and field_ids.issubset(enabled_field_ids):
                    selected_group_ids.append(group_id)

            self.initial["history_groups"] = selected_group_ids

    def save(self, commit=True):
        return super().save(commit=commit)

    def sync_history_fields(self, configuration):
        selected_ids = {
            field.pk
            for field in self.cleaned_data.get("history_fields", FormField.objects.none())
        }

        selected_group_ids = {
            group.pk
            for group in self.cleaned_data.get(
                "history_groups",
                FormRepeatableGroup.objects.none(),
            )
        }
        groups = list(self.fields["history_groups"].queryset)
        group_parent_ids = {
            group.pk: group.parent_group_id
            for group in groups
        }

        expanded_group_ids = set(selected_group_ids)
        changed = True
        while changed:
            changed = False
            for group_id, parent_id in group_parent_ids.items():
                if parent_id in expanded_group_ids and group_id not in expanded_group_ids:
                    expanded_group_ids.add(group_id)
                    changed = True

        form_fields = list(
            self.fields["history_fields"].queryset
        )
        selected_ids.update(
            field.pk
            for field in form_fields
            if field.repeatable_group_id in expanded_group_ids
        )

        for display_order, form_field in enumerate(form_fields):
            history_field, _ = HistoryField.objects.get_or_create(
                configuration=configuration,
                form_field=form_field,
                defaults={
                    "display_label": form_field.label,
                    "display_order": display_order,
                    "is_enabled": False,
                },
            )

            changed = False
            if not history_field.display_label:
                history_field.display_label = form_field.label
                changed = True
            if history_field.display_order != display_order:
                history_field.display_order = display_order
                changed = True

            enabled = form_field.pk in selected_ids
            if history_field.is_enabled != enabled:
                history_field.is_enabled = enabled
                changed = True

            if changed:
                history_field.save(
                    update_fields=(
                        "display_label",
                        "display_order",
                        "is_enabled",
                    )
                )


@admin.register(
    HistoryConfiguration,
    site=dolphin_admin_site,
)
class HistoryConfigurationAdmin(admin.ModelAdmin):
    admin_category = "forms"
    admin_section = "definition"
    form = HistoryConfigurationForm

    list_display = (
        "form",
        "name",
        "is_active",
        "field_count",
        "updated_at",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "form__name",
        "form__workflow__name",
    )

    autocomplete_fields = (
        "form",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    def get_readonly_fields(self, request, obj=None):
        fields = ["created_at", "updated_at"]
        if obj:
            fields.insert(0, "form")
        return tuple(fields)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        form.sync_history_fields(obj)

    @admin.display(description="تعداد فیلدهای فعال")
    def field_count(self, obj):
        return obj.fields.filter(is_enabled=True).count()


class HistoryDeviceFilter(admin.SimpleListFilter):
    title = "دستگاه"
    parameter_name = "device"

    def lookups(self, request, model_admin):
        devices = (
            Device.objects
            .filter(workflow_instances__isnull=False)
            .select_related("device_model", "device_model__device_type")
            .distinct()
            .order_by("device_model__brand", "device_model__name", "pk")
        )
        return [
            (device.pk, str(device))
            for device in devices
        ]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        return queryset.filter(
            instance__instance_devices__device_id=self.value(),
        ).distinct()


@admin.register(
    HistoryRecord,
    site=dolphin_admin_site,
)
class HistoryRecordAdmin(admin.ModelAdmin):
    """Read-only Admin browser over immutable History snapshots."""

    admin_category = "executions"
    admin_section = "execution"

    @admin.display(description="مشاهده")
    def history_link(self, obj):
        url = reverse(
            "admin:workflow_historyrecord_change",
            args=[obj.pk],
        )
        return format_html(
            '<a class="button" href="{}">مشاهده سابقه</a>',
            url,
        )

    @admin.display(description="فرآیند", ordering="instance__workflow__name")
    def workflow(self, obj):
        return obj.instance.workflow

    list_display = (
        "history_link",
        "workflow",
        "instance",
        "workflow_step",
        "performed_by",
        "submitted_at",
    )

    list_filter = (
        "workflow_step__workflow",
        "workflow_step",
        HistoryDeviceFilter,
        "performed_by",
        "submitted_at",
    )

    search_fields = (
        "instance__pk",
        "instance__workflow__name",
        "instance__workflow__code",
        "workflow_step__name",
        "performed_by__username",
        "performed_by__first_name",
        "performed_by__last_name",
    )

    ordering = (
        "-submitted_at",
        "-pk",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(
                is_submitted=True,
                data__has_key="history",
            )
            .select_related(
                "instance",
                "instance__workflow",
                "workflow_step",
                "performed_by",
            )
        )

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request):
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        execution = get_object_or_404(
            self.get_queryset(request),
            pk=object_id,
        )
        snapshot = execution.data.get("history") if execution.data else None

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": execution,
            "title": f"سابقه {execution.instance.workflow.name} #{execution.instance.pk}",
            "execution": execution,
            "snapshot": snapshot or {},
            "changelist_url": reverse(
                "admin:workflow_historyrecord_changelist",
            ),
        }
        if extra_context:
            context.update(extra_context)

        return TemplateResponse(
            request,
            "admin/workflow/history_record_change.html",
            context,
        )
