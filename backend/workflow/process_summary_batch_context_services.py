from collections import defaultdict

from .models import FormData, FormDefinition, FormRepeatableGroup
from .repeatable_row_read_services import RepeatableRowReadService


class ProcessSummaryBatchContextService:
    """Batch-load immutable data shared by per-instance summary rendering."""

    @classmethod
    def build(cls, *, instances):
        instances = list(instances)
        if not instances:
            return {
                "instances": {},
                "forms": {},
                "sections": {},
                "groups": {},
                "form_data": {},
                "rows": {},
            }

        instance_ids = [instance.pk for instance in instances]
        workflow_ids = {instance.workflow_id for instance in instances}

        forms = list(
            FormDefinition.objects
            .filter(workflow_id__in=workflow_ids)
            .prefetch_related("sections__fields")
        )
        forms_by_workflow = {form.workflow_id: form for form in forms}

        sections_by_workflow = defaultdict(list)
        section_ids = []
        for form in forms:
            for section in form.sections.all():
                if not section.is_active:
                    continue
                sections_by_workflow[form.workflow_id].append(section)
                section_ids.append(section.pk)

        groups = list(
            FormRepeatableGroup.objects
            .filter(section_id__in=section_ids, is_active=True)
            .select_related("section", "section__form")
            .prefetch_related("fields__choice_model")
            .order_by("section_id", "order", "id")
        )
        groups_by_workflow = defaultdict(list)
        for group in groups:
            groups_by_workflow[group.section.form.workflow_id].append(group)

        form_data_by_instance = {
            item.instance_id: item.data
            for item in FormData.objects.filter(instance_id__in=instance_ids)
        }

        rows = RepeatableRowReadService.get_rows_by_instance_group_parent(
            instances=instances,
            groups=groups,
        )

        return {
            "instances": {instance.pk: instance for instance in instances},
            "forms": forms_by_workflow,
            "sections": dict(sections_by_workflow),
            "groups": dict(groups_by_workflow),
            "form_data": form_data_by_instance,
            "rows": rows,
        }
