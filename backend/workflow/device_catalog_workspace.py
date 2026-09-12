from django import forms
from django.contrib import messages
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Device, DeviceIdentifier, DeviceModel, DeviceType


ENTITY_CONFIG = {
    "types": {
        "title": "Device Types",
        "label": "انواع دستگاه",
        "model": DeviceType,
    },
    "models": {
        "title": "Device Models",
        "label": "مدل‌های دستگاه",
        "model": DeviceModel,
    },
    "devices": {
        "title": "Devices",
        "label": "دستگاه‌ها",
        "model": Device,
    },
    "identifiers": {
        "title": "Device Identifiers",
        "label": "شناسه‌های دستگاه",
        "model": DeviceIdentifier,
    },
}


def _workspace_url(entity="types", object_id=None):
    url = reverse("device_catalog_workspace")
    params = [f"entity={entity}"]
    if object_id:
        params.append(f"edit={object_id}")
    return f"{url}?{'&'.join(params)}"


class DeviceTypeWorkspaceForm(forms.ModelForm):
    class Meta:
        model = DeviceType
        fields = ("name", "code", "description", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        if self.instance.pk:
            self.fields["code"].disabled = True


class DeviceModelWorkspaceForm(forms.ModelForm):
    class Meta:
        model = DeviceModel
        fields = ("device_type", "brand", "name", "code", "description", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        if self.instance.pk:
            self.fields["code"].disabled = True


class DeviceWorkspaceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ("device_model", "description")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }


class DeviceIdentifierWorkspaceForm(forms.ModelForm):
    class Meta:
        model = DeviceIdentifier
        fields = ("device", "identifier_type", "value")


def _form_for(entity, *args, **kwargs):
    return {
        "types": DeviceTypeWorkspaceForm,
        "models": DeviceModelWorkspaceForm,
        "devices": DeviceWorkspaceForm,
        "identifiers": DeviceIdentifierWorkspaceForm,
    }[entity](*args, **kwargs)


def _queryset(entity, query=""):
    model = ENTITY_CONFIG[entity]["model"]
    qs = model.objects.all()

    if entity == "types":
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(description__icontains=query))
        return qs.order_by("name")

    if entity == "models":
        if query:
            qs = qs.filter(
                Q(name__icontains=query)
                | Q(brand__icontains=query)
                | Q(code__icontains=query)
                | Q(device_type__name__icontains=query)
            )
        return qs.select_related("device_type").order_by("brand", "name")

    if entity == "devices":
        if query:
            qs = qs.filter(
                Q(device_model__brand__icontains=query)
                | Q(device_model__name__icontains=query)
                | Q(description__icontains=query)
                | Q(identifiers__value__icontains=query)
            )
        return qs.select_related("device_model", "device_model__device_type").distinct().order_by("-created_at")

    if query:
        qs = qs.filter(
            Q(value__icontains=query)
            | Q(device__device_model__brand__icontains=query)
            | Q(device__device_model__name__icontains=query)
            | Q(identifier_type__icontains=query)
        )
    return qs.select_related("device", "device__device_model").order_by("identifier_type", "value")


def device_catalog_workspace(request):
    entity = request.GET.get("entity", "types")
    if entity not in ENTITY_CONFIG:
        entity = "types"

    query = request.GET.get("q", "").strip()
    selected_id = request.GET.get("edit")
    model = ENTITY_CONFIG[entity]["model"]
    selected = get_object_or_404(model, pk=selected_id) if selected_id else None

    if request.method == "POST":
        action = request.POST.get("action")
        object_id = request.POST.get("object_id")

        if action == "delete":
            obj = get_object_or_404(model, pk=object_id)
            name = str(obj)
            try:
                obj.delete()
            except ProtectedError:
                messages.error(request, f"«{name}» قابل حذف نیست؛ هنوز در داده‌های وابسته استفاده می‌شود.")
            else:
                messages.success(request, f"«{name}» حذف شد.")
            return redirect(_workspace_url(entity))

        if action in {"add", "edit"}:
            instance = get_object_or_404(model, pk=object_id) if action == "edit" else None
            form = _form_for(entity, data=request.POST, instance=instance)
            if form.is_valid():
                obj = form.save()
                messages.success(request, f"«{obj}» {'ذخیره شد' if instance else 'ایجاد شد'}.")
                return redirect(_workspace_url(entity, obj.pk))
            selected = instance
        else:
            messages.error(request, "نوع عملیات نامعتبر است.")

    objects = _queryset(entity, query)
    form = _form_for(entity, instance=selected)

    return render(
        request,
        "admin/workflow/device_catalog_workspace.html",
        {
            "entity": entity,
            "entity_config": ENTITY_CONFIG[entity],
            "objects": objects,
            "selected": selected,
            "form": form,
            "query": query,
        },
    )
