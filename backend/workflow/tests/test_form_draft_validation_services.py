from dataclasses import FrozenInstanceError

from django.test import SimpleTestCase

from workflow.form_draft_validation_services import (
    FormDraftValidationMode,
    FormDraftValidationPolicy,
)


class FormDraftValidationPolicyTests(SimpleTestCase):

    def test_draft_preserves_integrity_validation_but_allows_incomplete_data(self):
        policy = FormDraftValidationPolicy.for_mode(
            FormDraftValidationMode.DRAFT,
        )

        self.assertTrue(policy.validate_structure)
        self.assertTrue(policy.validate_value_integrity)
        self.assertTrue(policy.validate_dependencies)

        self.assertFalse(policy.validate_required_fields)
        self.assertFalse(policy.validate_required_groups)
        self.assertFalse(policy.validate_required_repeatable_fields)

    def test_submit_enforces_integrity_and_completeness(self):
        policy = FormDraftValidationPolicy.for_mode(
            FormDraftValidationMode.SUBMIT,
        )

        self.assertTrue(policy.validate_structure)
        self.assertTrue(policy.validate_value_integrity)
        self.assertTrue(policy.validate_dependencies)

        self.assertTrue(policy.validate_required_fields)
        self.assertTrue(policy.validate_required_groups)
        self.assertTrue(policy.validate_required_repeatable_fields)

    def test_draft_and_submit_share_the_same_integrity_contract(self):
        draft = FormDraftValidationPolicy.for_mode(
            FormDraftValidationMode.DRAFT,
        )
        submit = FormDraftValidationPolicy.for_mode(
            FormDraftValidationMode.SUBMIT,
        )

        self.assertEqual(
            (
                draft.validate_structure,
                draft.validate_value_integrity,
                draft.validate_dependencies,
            ),
            (
                submit.validate_structure,
                submit.validate_value_integrity,
                submit.validate_dependencies,
            ),
        )

    def test_required_rules_are_the_only_mode_dependent_part_of_the_contract(self):
        draft = FormDraftValidationPolicy.for_mode(
            FormDraftValidationMode.DRAFT,
        )
        submit = FormDraftValidationPolicy.for_mode(
            FormDraftValidationMode.SUBMIT,
        )

        self.assertNotEqual(
            (
                draft.validate_required_fields,
                draft.validate_required_groups,
                draft.validate_required_repeatable_fields,
            ),
            (
                submit.validate_required_fields,
                submit.validate_required_groups,
                submit.validate_required_repeatable_fields,
            ),
        )

    def test_policy_is_immutable(self):
        policy = FormDraftValidationPolicy.for_mode(
            FormDraftValidationMode.DRAFT,
        )

        with self.assertRaises(FrozenInstanceError):
            policy.validate_required_fields = True

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            FormDraftValidationPolicy.for_mode("unknown")
