from django import forms
from django.contrib import messages
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import (
    LookupItem,
    LookupList,
    StaticChoiceItem,
    StaticChoiceSet,
)


SOURCE_CONFIG = {
    "static": {
        "title": "Static Choice Sets",
        "label": "گزینه‌های ثابت",
        "set_model": StaticChoiceSet,
        "item_model": StaticChoiceItem,
        "owner_field": "choice_set",
    },
    "lookup": {
        "title": "Lookup Lists",
        "label": "لیست‌های داده‌ای",
        "set_model": LookupList,
        "item_model": LookupItem,
        "owner_field": "lookup_list",
    },
}


def _editable_fields(model, excluded=()):
    excluded = set(excluded)
    return tuple(
        field.name
        for field in model._meta.fields
        if field.editable
        and not field.auto_created
        and not field.primary_key
        and field.name not in excluded
    )


def _build_form(model, *, owner_field=None, owner=None, instance=None, data=None):
    excluded = (owner_field,) if owner_field else ()
    fields = _editable_fields(model, excluded=excluded)
    meta = type("Meta", (), {"model": model, "fields": fields})

    def __init__(self, *args, **kwargs):
        forms.ModelForm.__init__(self, *args, **kwargs)
        if model is LookupItem and "parent" in self.fields and owner:
            queryset = LookupItem.objects.filter(
                lookup_list=owner,
            )
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            self.fields["parent"].queryset = queryset.order_by("name")

    def save(self, commit=True):
        obj = forms.ModelForm.save(self, commit=False)
        if owner_field and owner is not None:
            setattr(obj, owner_field, owner)
        if commit:
            obj.save()
        return obj

    form_class = type(
        "WorkspaceModelForm",
        (forms.ModelForm,),
        {
            "Meta": meta,
            "__init__": __init__,
            "save": save,
        },
    )
    return form_class(data=data, instance=instance)


def _workspace_url(source, *, selected_set=None, selected_item=None):
    url = reverse("data_sources_workspace")
    params = [f"source={source}"]
    if selected_set:
        params.append(f"set={selected_set}")
    if selected_item:
        params.append(f"item={selected_item}")
    return f"{url}?{'&'.join(params)}"


def data_sources_workspace(request):
    source = request.GET.get("source", "static")
    if source not in SOURCE_CONFIG:
        source = "static"

    config = SOURCE_CONFIG[source]
    set_model = config["set_model"]
    item_model = config["item_model"]
    owner_field = config["owner_field"]

    selected_set_id = request.GET.get("set")
    selected_item_id = request.GET.get("item")
    selected_set = get_object_or_404(set_model, pk=selected_set_id) if selected_set_id else None
    selected_item = None

    if selected_item_id:
        selected_item = get_object_or_404(
            item_model,
            pk=selected_item_id,
            **({owner_field: selected_set} if selected_set else {}),
        )
        selected_set = getattr(selected_item, owner_field)

    if request.method == "POST":
        action = request.POST.get("action")
        object_type = request.POST.get("object_type")

        if object_type not in {"set", "item"}:
            messages.error(request, "نوع عملیات نامعتبر است.")
            return redirect(_workspace_url(source))

        if object_type == "set":
            if action == "add":
                form = _build_form(set_model, data=request.POST)
                if form.is_valid():
                    obj = form.save()
                    messages.success(request, f"«{obj}» ایجاد شد.")
                    return redirect(_workspace_url(source, selected_set=obj.pk))
                messages.error(request, "اطلاعات منبع معتبر نیست.")

            elif action == "edit":
                obj = get_object_or_404(set_model, pk=request.POST.get("object_id"))
                form = _build_form(set_model, instance=obj, data=request.POST)
                if form.is_valid():
                    obj = form.save()
                    messages.success(request, f"«{obj}» ذخیره شد.")
                    return redirect(_workspace_url(source, selected_set=obj.pk))
                messages.error(request, "اطلاعات منبع معتبر نیست.")

            elif action == "delete":
                obj = get_object_or_404(set_model, pk=request.POST.get("object_id"))
                name = str(obj)
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, f"«{name}» قابل حذف نیست؛ هنوز در داده‌های وابسته استفاده می‌شود.")
                else:
                    messages.success(request, f"«{name}» حذف شد.")
                return redirect(_workspace_url(source))

        if object_type == "item":
            owner_id = request.POST.get("owner_id")
            owner = get_object_or_404(set_model, pk=owner_id)

            if action == "add":
                form = _build_form(
                    item_model,
                    owner_field=owner_field,
                    owner=owner,
                    data=request.POST,
                )
                if form.is_valid():
                    obj = form.save()
                    messages.success(request, f"«{obj}» اضافه شد.")
                    return redirect(_workspace_url(source, selected_set=owner.pk, selected_item=obj.pk))
                messages.error(request, "اطلاعات آیتم معتبر نیست.")

            elif action == "edit":
                obj = get_object_or_404(item_model, pk=request.POST.get("object_id"), **{owner_field: owner})
                form = _build_form(
                    item_model,
                    owner_field=owner_field,
                    owner=owner,
                    instance=obj,
                    data=request.POST,
                )
                if form.is_valid():
                    obj = form.save()
                    messages.success(request, f"«{obj}» ذخیره شد.")
                    return redirect(_workspace_url(source, selected_set=owner.pk, selected_item=obj.pk))
                messages.error(request, "اطلاعات آیتم معتبر نیست.")

            elif action == "delete":
                obj = get_object_or_404(item_model, pk=request.POST.get("object_id"), **{owner_field: owner})
                name = str(obj)
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, f"«{name}» قابل حذف نیست؛ هنوز در داده‌های وابسته استفاده می‌شود.")
                else:
                    messages.success(request, f"«{name}» حذف شد.")
                return redirect(_workspace_url(source, selected_set=owner.pk))

    sets = set_model.objects.all().order_by("name")
    items = selected_set.items.all().order_by("name") if selected_set else item_model.objects.none()

    set_form = _build_form(
        set_model,
        instance=selected_set if selected_set else None,
    )
    item_form = None
    if selected_set:
        item_form = _build_form(
            item_model,
            owner_field=owner_field,
            owner=selected_set,
            instance=selected_item if selected_item else None,
        )

    return render(
        request,
        "admin/workflow/data_sources_workspace.html",
        {
            "source": source,
            "source_config": config,
            "sets": sets,
            "selected_set": selected_set,
            "items": items,
            "selected_item": selected_item,
            "set_form": set_form,
            "item_form": item_form,
        },
    )
