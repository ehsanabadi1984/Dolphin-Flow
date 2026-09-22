from .form_draft_diff_services import FormDraftDiff
from .models import FormData


class FormDraftNormalFieldApplyService:
    """
    Apply changed normal-field values to the legacy FormData store.

    Permission and value validation are intentionally handled by the
    surrounding draft-save pipeline. This service only persists the normal
    field portion of an already-authorized diff.
    """

    @staticmethod
    def apply(*, instance, diff: FormDraftDiff):
        changes = [change for change in diff.normal_fields if change.changed]
        if not changes:
            return FormData.objects.filter(instance=instance).first()

        form_data, _ = FormData.objects.get_or_create(instance=instance)
        data = form_data.data if isinstance(form_data.data, dict) else {}

        for change in changes:
            data[change.field.code] = change.submitted_value

        form_data.data = data
        form_data.save(update_fields=["data", "updated_at"])
        return form_data
