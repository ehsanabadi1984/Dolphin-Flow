from .form_draft_current_state_payload_services import (
    FormDraftCurrentStatePayloadService,
)
from .form_draft_submit_validation_services import (
    FormDraftSubmitValidationService,
)
from .permission_context import PermissionContext
from .form_draft_value_validation_services import (
    FormDraftValueValidationService,
)


class FormDraftSubmitService:
    """
    Stage 12.6: validate the canonical persisted form state for Submit.

    Submit is intentionally payload-free. The current state is reconstructed
    from canonical persistence and then passed through value/dependency
    validation followed by final completeness validation.

    Structural validation is not repeated here because the source is already
    canonical database state rather than an untrusted raw browser payload.
    """

    @classmethod
    def validate(cls, *, instance, form, user):
        permission_context = PermissionContext.build(
            workflow=instance.workflow,
            form=form,
            step=instance.current_step,
            user=user,
        )

        normalized_payload = FormDraftCurrentStatePayloadService.build(
            instance=instance,
            form=form,
        )

        FormDraftValueValidationService.validate_payload(
            instance=instance,
            form=form,
            normalized_payload=normalized_payload,
        )

        FormDraftSubmitValidationService.validate_payload(
            instance=instance,
            form=form,
            normalized_payload=normalized_payload,
            permission_context=permission_context,
        )

        return normalized_payload
