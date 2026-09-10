from django import forms
from django.contrib import admin

from .admin import dolphin_admin_site
from .history_models import HistoryConfiguration, HistoryField
from .models import FormField


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
