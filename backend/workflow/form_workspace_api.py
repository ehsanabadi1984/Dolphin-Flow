from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.http import JsonResponse


def workspace_model_fields(request):
    content_type_id = request.GET.get("content_type")

    if not content_type_id:
        return JsonResponse({"fields": []}, status=400)

    try:
        content_type = ContentType.objects.get(pk=content_type_id)
    except (ContentType.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"fields": []}, status=404)

    model_class = content_type.model_class()
    if not model_class:
        return JsonResponse({"fields": []}, status=404)

    fields = []
    for field in model_class._meta.get_fields():
        if not getattr(field, "concrete", False):
            continue
        if getattr(field, "auto_created", False):
            continue
        if not getattr(field, "editable", True):
            continue

        related_model = None
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            related_model = field.remote_field.model._meta.verbose_name

        fields.append(
            {
                "name": field.name,
                "label": str(field.verbose_name),
                "is_foreign_key": isinstance(field, models.ForeignKey),
                "related_model": str(related_model) if related_model else "",
            }
        )

    return JsonResponse({"fields": fields})
