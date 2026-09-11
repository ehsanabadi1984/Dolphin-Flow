from django import forms
from django.contrib import messages
from django.core.exceptions import ProtectedError, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    LookupList,
    StaticChoiceSet,
    Workflow,
)


class FormDefinitionWorkspaceForm(forms.ModelForm):
    class Meta:
        model = FormDefinition
        fields = ("name", "is_active")


class FormSectionWorkspaceForm(forms.ModelForm):
    class Meta:
        model = FormSection
        fields = ("name", "code", "description", "is_active")

    def __init__(self, *args, form_definition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.form_definition = form_definition

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code:
            raise forms.ValidationError("کد Section الزامی است.")
        return code


class FormRepeatableGroupWorkspaceForm(forms.ModelForm):
    class Meta:
        model = FormRepeatableGroup
        fields = (
            "name",
            "code",
            "group_type",
            "display_type",
            "description",
            "is_required",
            "is_active",
        )

    def __init__(self, *args, section=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.section = section

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code:
            raise forms.ValidationError("کد گروه الزامی است.")
        return code


class FormFieldWorkspaceForm(forms.ModelForm):
    class Meta:
        model = FormField
        fields = (
            "section",
            "repeatable_group",
            "name",
            "code",
            "label",
            "field_type",
            "system_key",
            "help_text",
            "is_required",
            "is_history_enabled",
            "is_active",
            "choice_source",
            "choice_model",
            "choice_static_set",
            "choice_lookup_list",
            "choice_label_field",
            "choice_value_field",
            "choice_parent_field",
            "choice_filter_field",
        )

    def __init__(self, *args, form_definition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.form_definition = form_definition

        self.fields["section"].queryset = (
            FormSection.objects
            .filter(form=form_definition)
            .order_by("order", "name")
            if form_definition
            else FormSection.objects.none()
        )
        self.fields["repeatable_group"].queryset = (
            FormRepeatableGroup.objects
            .filter(section__form=form_definition)
            .select_related("section")
            .order_by("section__order", "order", "name")
            if form_definition
            else FormRepeatableGroup.objects.none()
        )
        self.fields["choice_static_set"].queryset = (
            StaticChoiceSet.objects.filter(is_active=True).order_by("name")
        )
        self.fields["choice_lookup_list"].queryset = (
            LookupList.objects.filter(is_active=True).order_by("name")
        )

        if form_definition:
            parent_qs = FormField.objects.filter(
                section__form=form_definition,
                field_type=FormField.FieldType.SELECT,
                is_active=True,
            ).order_by("section__order", "order", "label")
            if self.instance.pk:
                parent_qs = parent_qs.exclude(pk=self.instance.pk)
            self.fields["choice_parent_field"].queryset = parent_qs
        else:
            self.fields["choice_parent_field"].queryset = FormField.objects.none()

        # A system key is meaningful only when the runtime already knows
        # how to persist it. We expose the existing model choices, without
        # inventing new runtime mappings in the workspace.

    def clean(self):
        cleaned = super().clean()
        section = cleaned.get("section")
        group = cleaned.get("repeatable_group")

        if section and section.form_id != self.form_definition.id:
            raise forms.ValidationError("Section انتخاب‌شده متعلق به این Form نیست.")

        if group:
            if group.section_id != section.id:
                raise forms.ValidationError(
                    "گروه تکرارشونده باید متعلق به همان Section فیلد باشد."
                )

        return cleaned


def _redirect_designer(workflow, *, section=None, field=None, group=None):
    url = reverse("form_workspace", args=[workflow.pk])
    params = []
    if section:
        params.append(f"section={section.pk}")
    if group:
        params.append(f"group={group.pk}")
    if field:
        params.append(f"field={field.pk}")
    if params:
        url += "?" + "&".join(params)
    return redirect(url)


def _form_for_workflow(workflow):
    form, _ = FormDefinition.objects.get_or_create(
        workflow=workflow,
        defaults={
            "name": f"فرم {workflow.name}",
            "is_active": True,
        },
    )
    return form


def form_workspace(request, workflow_id):
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    form_definition = _form_for_workflow(workflow)

    selected_section = None
    selected_group = None
    selected_field = None

    if request.GET.get("section"):
        selected_section = get_object_or_404(
            FormSection,
            pk=request.GET["section"],
            form=form_definition,
        )
    if request.GET.get("group"):
        selected_group = get_object_or_404(
            FormRepeatableGroup,
            pk=request.GET["group"],
            section__form=form_definition,
        )
        selected_section = selected_section or selected_group.section
    if request.GET.get("field"):
        selected_field = get_object_or_404(
            FormField,
            pk=request.GET["field"],
            section__form=form_definition,
        )
        selected_section = selected_section or selected_field.section
        selected_group = selected_group or selected_field.repeatable_group

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "save_form":
            bound = FormDefinitionWorkspaceForm(request.POST, instance=form_definition)
            if bound.is_valid():
                bound.save()
                messages.success(request, "تنظیمات Form ذخیره شد.")
                return _redirect_designer(workflow, section=selected_section)
            messages.error(request, "اطلاعات Form معتبر نیست.")

        elif action == "add_section":
            bound = FormSectionWorkspaceForm(request.POST, form_definition=form_definition)
            if bound.is_valid():
                with transaction.atomic():
                    obj = bound.save(commit=False)
                    obj.form = form_definition
                    obj.order = (FormSection.objects.filter(form=form_definition).count() + 1)
                    obj.save()
                messages.success(request, "Section اضافه شد.")
                return _redirect_designer(workflow, section=obj)
            messages.error(request, "اطلاعات Section معتبر نیست.")

        elif action == "edit_section":
            obj = get_object_or_404(FormSection, pk=request.POST.get("section_id"), form=form_definition)
            bound = FormSectionWorkspaceForm(request.POST, instance=obj, form_definition=form_definition)
            if bound.is_valid():
                bound.save()
                messages.success(request, "Section ذخیره شد.")
                return _redirect_designer(workflow, section=obj)
            messages.error(request, "اطلاعات Section معتبر نیست.")

        elif action == "delete_section":
            obj = get_object_or_404(FormSection, pk=request.POST.get("section_id"), form=form_definition)
            try:
                obj.delete()
                messages.success(request, "Section حذف شد.")
                return _redirect_designer(workflow)
            except ProtectedError:
                messages.error(request, "این Section به داده‌های وابسته متصل است و قابل حذف نیست.")
                return _redirect_designer(workflow, section=obj)

        elif action == "add_group":
            section = get_object_or_404(FormSection, pk=request.POST.get("section_id"), form=form_definition)
            bound = FormRepeatableGroupWorkspaceForm(request.POST, section=section)
            if bound.is_valid():
                obj = bound.save(commit=False)
                obj.section = section
                obj.order = FormRepeatableGroup.objects.filter(section=section).count() + 1
                obj.save()
                messages.success(request, "گروه تکرارشونده اضافه شد.")
                return _redirect_designer(workflow, section=section, group=obj)
            messages.error(request, "اطلاعات گروه معتبر نیست.")

        elif action == "edit_group":
            obj = get_object_or_404(
                FormRepeatableGroup,
                pk=request.POST.get("group_id"),
                section__form=form_definition,
            )
            bound = FormRepeatableGroupWorkspaceForm(request.POST, instance=obj, section=obj.section)
            if bound.is_valid():
                bound.save()
                messages.success(request, "گروه تکرارشونده ذخیره شد.")
                return _redirect_designer(workflow, section=obj.section, group=obj)
            messages.error(request, "اطلاعات گروه معتبر نیست.")

        elif action == "delete_group":
            obj = get_object_or_404(
                FormRepeatableGroup,
                pk=request.POST.get("group_id"),
                section__form=form_definition,
            )
            section = obj.section
            try:
                obj.delete()
                messages.success(request, "گروه تکرارشونده حذف شد.")
                return _redirect_designer(workflow, section=section)
            except ProtectedError:
                messages.error(request, "این گروه دارای داده یا وابستگی محافظت‌شده است و قابل حذف نیست.")
                return _redirect_designer(workflow, section=section, group=obj)

        elif action == "add_field":
            bound = FormFieldWorkspaceForm(request.POST, form_definition=form_definition)
            if bound.is_valid():
                section = bound.cleaned_data["section"]
                group = bound.cleaned_data.get("repeatable_group")
                with transaction.atomic():
                    obj = bound.save(commit=False)
                    obj.order = (
                        FormField.objects.filter(repeatable_group=group).count() + 1
                        if group
                        else FormField.objects.filter(section=section, repeatable_group__isnull=True).count() + 1
                    )
                    obj.save()
                    obj.full_clean()
                    obj.save()
                messages.success(request, "Field اضافه شد.")
                return _redirect_designer(workflow, section=section, group=group, field=obj)
            messages.error(request, "اطلاعات Field معتبر نیست.")

        elif action == "edit_field":
            obj = get_object_or_404(FormField, pk=request.POST.get("field_id"), section__form=form_definition)
            bound = FormFieldWorkspaceForm(request.POST, instance=obj, form_definition=form_definition)
            if bound.is_valid():
                section = bound.cleaned_data["section"]
                group = bound.cleaned_data.get("repeatable_group")
                obj = bound.save(commit=False)
                obj.full_clean()
                obj.save()
                messages.success(request, "Field ذخیره شد.")
                return _redirect_designer(workflow, section=section, group=group, field=obj)
            messages.error(request, "اطلاعات Field معتبر نیست.")

        elif action == "delete_field":
            obj = get_object_or_404(FormField, pk=request.POST.get("field_id"), section__form=form_definition)
            section = obj.section
            group = obj.repeatable_group
            try:
                obj.delete()
                messages.success(request, "Field حذف شد.")
                return _redirect_designer(workflow, section=section, group=group)
            except ProtectedError:
                messages.error(request, "این Field به داده یا تنظیمات وابسته متصل است و قابل حذف نیست.")
                return _redirect_designer(workflow, section=section, group=group, field=obj)

        return _redirect_designer(workflow, section=selected_section, group=selected_group, field=selected_field)

    sections = list(
        form_definition.sections
        .filter(is_active=True)
        .prefetch_related("fields", "repeatable_groups__fields")
        .order_by("order", "id")
    )

    for section in sections:
        section.top_level_fields = [
            field for field in section.fields.all()
            if field.repeatable_group_id is None and field.is_active
        ]
        section.active_groups = [
            group for group in section.repeatable_groups.all()
            if group.is_active
        ]

    context = {
        "title": f"طراحی فرم · {workflow.name}",
        "workflow": workflow,
        "form_definition": form_definition,
        "sections": sections,
        "selected_section": selected_section,
        "selected_group": selected_group,
        "selected_field": selected_field,
        "form_form": FormDefinitionWorkspaceForm(instance=form_definition),
        "section_form": FormSectionWorkspaceForm(form_definition=form_definition),
        "group_form": FormRepeatableGroupWorkspaceForm(section=selected_section),
        "field_form": FormFieldWorkspaceForm(form_definition=form_definition),
    }

    if selected_section:
        context["selected_section_form"] = FormSectionWorkspaceForm(
            instance=selected_section,
            form_definition=form_definition,
        )
        context["group_form"] = FormRepeatableGroupWorkspaceForm(
            section=selected_section,
        )

    if selected_group:
        context["selected_group_form"] = FormRepeatableGroupWorkspaceForm(
            instance=selected_group,
            section=selected_group.section,
        )

    if selected_field:
        context["selected_field_form"] = FormFieldWorkspaceForm(
            instance=selected_field,
            form_definition=form_definition,
        )

    return render(request, "admin/workflow/form_workspace.html", context)
