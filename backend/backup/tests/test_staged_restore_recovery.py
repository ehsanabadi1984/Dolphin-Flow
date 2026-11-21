from unittest import TestCase

from backup.restore_services import RestoreError
from backup.staged_restore_recovery import StagedRestoreRecovery


class StagedRestoreRecoveryClassificationTests(TestCase):
    def test_classifies_database_states_from_atomic_rename_protocol(self):
        cases = (
            ({"live": True, "previous": False, "staging": True}, "NOT_SWAPPED"),
            ({"live": False, "previous": True, "staging": True}, "OLD_MOVED"),
            ({"live": True, "previous": True, "staging": False}, "NEW_PROMOTED"),
        )
        for state, expected in cases:
            with self.subTest(state=state):
                self.assertEqual(
                    StagedRestoreRecovery._classify_resource(state, "database"),
                    expected,
                )

    def test_rejects_ambiguous_or_incomplete_database_states(self):
        cases = (
            {"live": False, "previous": False, "staging": True},
            {"live": True, "previous": True, "staging": True},
            {"live": False, "previous": True, "staging": False},
            {"live": False, "previous": False, "staging": False},
        )
        for state in cases:
            with self.subTest(state=state):
                with self.assertRaises(RestoreError):
                    StagedRestoreRecovery._classify_resource(state, "database")

    def test_classification_is_independent_of_journal_flags(self):
        # Recovery must use observed resource names, not potentially stale
        # booleans written immediately before/after a process crash.
        observed = {"live": True, "previous": True, "staging": False}
        self.assertEqual(
            StagedRestoreRecovery._classify_resource(observed, "database"),
            "NEW_PROMOTED",
        )
