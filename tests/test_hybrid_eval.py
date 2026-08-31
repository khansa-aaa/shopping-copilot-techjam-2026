from __future__ import annotations

import unittest
from collections import Counter

from evaluator.local_evaluator import load_jsonl
from evaluation.run_hybrid_eval import (
    BudgetedTimedAgent,
    BudgetGuard,
    build_selection,
    selection_manifest,
)


class HybridSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.samples = load_jsonl("data/public_set.jsonl")

    def test_selection_is_deterministic_disjoint_and_stratified(self) -> None:
        first = build_selection(self.samples)
        second = build_selection(self.samples)
        first_calibration = [item["sample_id"] for item in first.calibration]
        second_calibration = [item["sample_id"] for item in second.calibration]
        first_post_freeze = [item["sample_id"] for item in first.post_freeze_audit]
        second_post_freeze = [item["sample_id"] for item in second.post_freeze_audit]

        self.assertEqual(first_calibration, second_calibration)
        self.assertEqual(first_post_freeze, second_post_freeze)
        self.assertEqual(len(first_calibration), 32)
        self.assertEqual(len(first_post_freeze), 32)
        self.assertTrue(set(first_calibration).isdisjoint(first_post_freeze))
        self.assertTrue(set(first_calibration).issubset(item["sample_id"] for item in first.tuning))
        self.assertTrue(set(first_post_freeze).issubset(item["sample_id"] for item in first.holdout))

        expected = Counter({
            ("buying", "easy"): 13,
            ("browsing", "medium"): 13,
            ("intent_override", "hard"): 5,
            ("boundary", "medium"): 1,
        })
        self.assertEqual(
            Counter((item["scenario_type"], item["difficulty_bucket"]) for item in first.calibration),
            expected,
        )
        self.assertEqual(
            Counter((item["scenario_type"], item["difficulty_bucket"]) for item in first.post_freeze_audit),
            expected,
        )

    def test_manifest_hashes_are_stable(self) -> None:
        first = selection_manifest(build_selection(self.samples))
        second = selection_manifest(build_selection(list(reversed(self.samples))))
        self.assertEqual(first, second)
        self.assertEqual(first["base_split"]["tuning_count"], 160)
        self.assertEqual(first["base_split"]["holdout_count"], 40)
        audit = first["post_freeze_exploratory_audit"]
        self.assertFalse(audit["tuning_authority"])
        self.assertFalse(audit["untouched_holdout_claim"])
        self.assertEqual(audit["source"], "previously_inspected_offline_holdout")
        self.assertNotIn("locked_validation", first)


class BudgetGuardTest(unittest.TestCase):
    def test_cutoff_preserves_operator_and_next_call_reserves(self) -> None:
        guard = BudgetGuard(hard_cap_usd=10.0)
        self.assertTrue(guard.can_authorize_call())

        # $4.75 reported cost leaves exactly $1 + $4.25. Equality is not
        # authorized, so the lane remains strictly below the hard ceiling.
        guard.record_turn(
            {"prompt_tokens": 2_375_000, "completion_tokens": 0},
            {"attempted": True, "applied": True},
        )
        self.assertFalse(guard.can_authorize_call())
        self.assertTrue(guard.cutoff_triggered)
        self.assertEqual(guard.reported_cost_usd, 4.75)

    def test_unreported_attempts_reserve_worst_case_exposure(self) -> None:
        guard = BudgetGuard(hard_cap_usd=10.0)
        guard.record_turn(
            {"prompt_tokens": 0, "completion_tokens": 0},
            {"attempted": True, "applied": False},
        )
        self.assertTrue(guard.can_authorize_call())
        guard.record_turn(
            {"prompt_tokens": 0, "completion_tokens": 0},
            {"attempted": True, "applied": False},
        )
        self.assertFalse(guard.can_authorize_call())
        self.assertEqual(guard.unreported_calls, 2)
        self.assertEqual(guard.unreported_exposure_usd, 8.5)
        self.assertTrue(guard.as_dict()["hard_cap_respected"])

    def test_pre_call_reservation_survives_an_exception(self) -> None:
        class FailingAgent:
            class Enhancer:
                enabled = True

            enhancer = Enhancer()

            def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
                raise RuntimeError("failure after a potentially billable request")

        guard = BudgetGuard(hard_cap_usd=10.0)
        wrapped = BudgetedTimedAgent(FailingAgent(), guard)  # type: ignore[arg-type]
        with self.assertRaises(RuntimeError):
            wrapped.respond("session", "shirts", 1, 3)
        self.assertEqual(guard.unreported_calls, 1)
        self.assertEqual(guard.unreported_exposure_usd, 4.25)

    def test_pre_call_reservation_is_released_when_no_call_was_attempted(self) -> None:
        class OfflineTurnAgent:
            class Enhancer:
                enabled = True

            enhancer = Enhancer()

            def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
                return {"usage": {"prompt_tokens": 0, "completion_tokens": 0}}

            def get_enhancement_status(self, session_id: str) -> dict:
                return {"attempted": False, "applied": False}

        guard = BudgetGuard(hard_cap_usd=10.0)
        wrapped = BudgetedTimedAgent(OfflineTurnAgent(), guard)  # type: ignore[arg-type]
        wrapped.respond("session", "shirts", 1, 3)
        self.assertEqual(guard.unreported_calls, 0)
        self.assertEqual(guard.accounted_exposure_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
