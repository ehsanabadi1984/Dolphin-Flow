from dataclasses import dataclass
from enum import StrEnum


class FormDraftValidationMode(StrEnum):
    DRAFT = "draft"
    SUBMIT = "submit"


@dataclass(frozen=True)
class FormDraftValidationPolicy:
    """
    Stage 12 validation contract.

    Draft validation guarantees that submitted data is structurally and
    semantically valid, but it does not require the form to be complete.

    Submit validation keeps the same integrity guarantees and additionally
    enforces completeness rules such as required fields and required
    repeatable groups/fields.

    This policy is intentionally declarative. It does not perform validation
    and does not contain permissions or persistence behavior.
    """

    validate_structure: bool
    validate_value_integrity: bool
    validate_dependencies: bool
    validate_required_fields: bool
    validate_required_groups: bool
    validate_required_repeatable_fields: bool

    @classmethod
    def for_mode(cls, mode: FormDraftValidationMode):
        if mode == FormDraftValidationMode.DRAFT:
            return cls(
                validate_structure=True,
                validate_value_integrity=True,
                validate_dependencies=True,
                validate_required_fields=False,
                validate_required_groups=False,
                validate_required_repeatable_fields=False,
            )

        if mode == FormDraftValidationMode.SUBMIT:
            return cls(
                validate_structure=True,
                validate_value_integrity=True,
                validate_dependencies=True,
                validate_required_fields=True,
                validate_required_groups=True,
                validate_required_repeatable_fields=True,
            )

        raise ValueError(f"Unsupported validation mode: {mode!r}")
