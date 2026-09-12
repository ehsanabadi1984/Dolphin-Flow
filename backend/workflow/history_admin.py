from django import forms
from django.contrib import admin
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html

from .admin import dolphin_admin_site
from .history_models import HistoryConfiguration, HistoryField
from .models import FormField, WorkflowStepExecution


class HistoryFieldInlineForm(forms.ModelForm):
    class Meta:
        model = HistoryField
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        configuration = self.instance.configuration if self.instance and self.instance.pk else None
        if configuration:
            self.fields["form_field"].queryset = (
                FormField.objects
                .filter(section__form_id=configuration.form_id)
                .select_related("section", "repeatable_group")
                .order_by("section__order", "order", "id")
            )
        else:
            self.fields["form_field"].queryset = FormField.objects.none()


class HistoryFieldInline(admin.TabularInline):
    model = HistoryField
    form = HistoryFieldInlineForm
    extra = 0
    fields = (
        "form_field",
        "display_label",
        "display_order",
        "is_enabled",
    )
    ordering = ("display_order", "id")

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)

        if obj:
            queryset = (
                FormField.objects
                .filter(section__form_id=obj.form_id)
                .select_related("section", "repeatable_group")
                .order_by("section__order", "order", "id")
            )
            formset.form.base_fields["form_field"].queryset = queryset

        return formset


@admin.register(
    HistoryConfiguration,
    site=dolphin_admin_site,
)
class HistoryConfigurationAdmin(admin.ModelAdmin):
    admin_category = "forms"
    admin_section = "definition"

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

    inlines = (
        HistoryFieldInline,
    )

    @admin.display(description="تعداد فیلدها")
    def field_count(self, obj):
        return obj.fields.count()


class HistoryRecord(WorkflowStepExecution):
    class Meta:
        proxy = True
        verbose_name = "سابقه"
        verbose_name_plural = "سوابق"


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

    def has_delete_permission(self, request, obj=None):
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
