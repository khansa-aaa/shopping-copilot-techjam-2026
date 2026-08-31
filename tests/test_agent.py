from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent as top_level
from shopping_copilot.agent import Agent, AgentConfig
from shopping_copilot.catalog import Product, normalize_price
from shopping_copilot.openai_enhancer import Enhancement, EnhancementAttempt, OpenAIEnhancer
from shopping_copilot.state import SessionState
from starter.agent import Agent as StarterAgent


PRODUCTS = [
    {
        "parent_asin": "A", "title": "Blue cotton running shirt", "features": ["soft cotton", "quick dry"],
        "description": ["athletic top"], "price": 20.0, "categories": ["Clothing", "Men", "Shirts"],
        "details": {"Department": "mens"}, "average_rating": 4.7, "rating_number": 100, "store": "Alpha",
    },
    {
        "parent_asin": "B", "title": "Black leather winter boot", "features": ["warm lining"],
        "description": ["outdoor footwear"], "price": "USD 75.50", "categories": ["Clothing", "Women", "Boots"],
        "details": {"Material": "leather"}, "average_rating": 4.5, "rating_number": 80, "store": "Beta",
    },
    {
        "parent_asin": "C", "title": "Red silk evening dress", "features": ["formal style"],
        "description": [], "price": "malformed", "categories": ["Clothing", "Women", "Dresses"],
        "details": {}, "average_rating": 4.2, "rating_number": 20, "store": "Gamma",
    },
]


class AgentContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.catalog = Path(cls.directory.name) / "catalog.jsonl"
        cls.catalog.write_text("".join(json.dumps(row) + "\n" for row in PRODUCTS), encoding="utf-8")
        cls.agent = Agent(cls.catalog)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def test_both_entrypoints_export_agent(self) -> None:
        self.assertIs(top_level.Agent, StarterAgent)

    def test_reset_is_required(self) -> None:
        with self.assertRaises(RuntimeError):
            self.agent.respond("missing", "shirt", 1, 10)

    def test_schema_unique_valid_and_turn_ten_never_asks(self) -> None:
        self.agent.reset("contract", {"preference_tags": ["comfort"]})
        response = self.agent.respond(
            "contract", "I'm looking for Men Shirts. A key requirement is: soft cotton.", 10, 3
        )
        self.assertIsNone(response["ask_attribute"])
        self.assertEqual(set(response), {"message", "ask_attribute", "recommendations", "usage"})
        identifiers = [item["parent_asin"] for item in response["recommendations"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(set(identifiers).issubset({"A", "B", "C"}))
        status = self.agent.get_enhancement_status("contract")
        self.assertEqual(status["outcome"], "disabled")
        self.assertFalse(status["attempted"])

    def test_all_ten_turn_numbers_and_buying_browsing_routes(self) -> None:
        self.agent.reset("turns", {"preference_tags": []})
        for turn in range(1, 11):
            message = (
                "I'm looking for Men Shirts, but I'm still exploring."
                if turn == 1 else "Those options are not quite right yet."
            )
            response = self.agent.respond("turns", message, turn, 3)
            self.assertLessEqual(len(response["recommendations"]), 3)
            if turn == 1:
                self.assertEqual(response["ask_attribute"], "other")
            if turn == 10:
                self.assertIsNone(response["ask_attribute"])
        self.agent.reset("buying", {"preference_tags": []})
        buying = self.agent.respond(
            "buying", "I'm looking for Men Shirts. A key requirement is: soft cotton.", 1, 3
        )
        self.assertNotEqual(buying["ask_attribute"], "other")

    def test_state_accumulates_and_override_revokes_non_category_evidence(self) -> None:
        self.agent.reset("override", {"preference_tags": []})
        self.agent.respond("override", "I'm looking for Men Shirts. old formal style", 1, 3)
        state = self.agent.sessions["override"]
        state.last_recommendations = ("A",)
        self.agent.respond(
            "override", "Actually, ignore my earlier preference. What I need is: black leather.", 3, 3
        )
        self.assertEqual(state.intent_generation, 1)
        self.assertEqual(state.rejected, set())
        self.assertEqual([item.value for item in state.active_evidence("style")], [])
        self.assertTrue(state.active_evidence("category"))
        self.assertTrue(state.active_evidence("material"))

    def test_override_is_detected_at_turn_three_or_four(self) -> None:
        for override_turn in (3, 4):
            with self.subTest(turn=override_turn):
                state = SessionState(f"override-{override_turn}", {"preference_tags": []})
                state.start_turn("I prefer formal style for this.", 1)
                state.start_turn(
                    "Actually, ignore my earlier preference. What I need is: leather.", override_turn
                )
                self.assertEqual(state.intent_generation, 1)
                self.assertFalse(state.active_evidence("style"))
                self.assertTrue(state.active_evidence("material"))

    def test_boundary_tombstone_and_soft_decay(self) -> None:
        state = SessionState("boundary", {"preference_tags": []})
        state.start_turn("I prefer formal style for the occasion.", 1)
        before = state.active_evidence("style")[0].confidence
        state.start_turn("I don't have a preference for material; please use your judgment.", 2)
        self.assertIn("material", state.no_preferences)
        self.assertLess(state.active_evidence("style")[0].confidence, before)

    def test_deterministic_sessions_and_candidate_rotation(self) -> None:
        for session in ("d1", "d2"):
            self.agent.reset(session, {"preference_tags": ["comfort"]})
        message = "I'm looking for Men Shirts. A key requirement is: soft cotton."
        first = self.agent.respond("d1", message, 1, 3)
        second = self.agent.respond("d2", message, 1, 3)
        self.assertEqual(first["recommendations"], second["recommendations"])
        followup = self.agent.respond("d1", "Those options are not quite right yet.", 2, 3)
        self.assertEqual(len({item["parent_asin"] for item in followup["recommendations"]}), len(followup["recommendations"]))

    def test_runtime_agent_never_imports_public_labels(self) -> None:
        runtime = Path(__import__("shopping_copilot").__file__).parent
        source = "\n".join(path.read_text(encoding="utf-8") for path in runtime.glob("*.py"))
        self.assertNotIn("ground_truth", source)
        self.assertNotIn("public_set", source)

    def test_empty_budget_filter_relaxes_to_nonempty_results(self) -> None:
        self.agent.reset("relax", {"preference_tags": []})
        response = self.agent.respond(
            "relax", "I'm looking for Men Shirts. A key requirement is: budget under $1.", 1, 3
        )
        self.assertTrue(response["recommendations"])

    def test_enhancement_preserves_hard_constraints_and_response_schema(self) -> None:
        config = AgentConfig(openai_enhancement=True, openai_rank_blend=1.0)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
            agent = Agent(self.catalog, config)
        enhancement = Enhancement(
            query_rewrite="winter boots",
            slot_updates=(("style", "winter", 0.7),),
            candidate_order=("B", "NOT-IN-CATALOG", "A"),
            next_attribute="color",
            prompt_tokens=7,
            completion_tokens=3,
        )
        agent.enhancer = mock.Mock()
        agent.enhancer.attempt.return_value = EnhancementAttempt(
            "applied", enhancement=enhancement, attempted=True, latency_ms=12.5,
            prompt_tokens=7, completion_tokens=3,
        )
        agent.reset("hard", {"preference_tags": []})
        response = agent.respond(
            "hard", "I'm looking for Men Shirts. A key requirement is: soft cotton.", 1, 3
        )
        self.assertEqual(set(response), {"message", "ask_attribute", "recommendations", "usage"})
        self.assertEqual(response["recommendations"][0]["parent_asin"], "A")
        submitted_products = agent.enhancer.attempt.call_args.args[2]
        self.assertEqual([product.parent_asin for product in submitted_products], ["A"])
        self.assertEqual(response["usage"], {"prompt_tokens": 7, "completion_tokens": 3})
        status = agent.get_enhancement_status("hard")
        self.assertEqual(status["outcome"], "applied")
        self.assertTrue(status["attempted"])
        self.assertTrue(status["applied"])
        self.assertEqual(status["latency_ms"], 12.5)

    def test_weighted_rank_blend_and_failure_fallback(self) -> None:
        config = AgentConfig(openai_enhancement=True, openai_rank_blend=0.65)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
            enhanced = Agent(self.catalog, config)
        self.assertEqual(enhanced._blend_ranking([0, 1, 2], [2, 1], 0.65), [2, 1, 0])

        enhanced.enhancer = mock.Mock()
        enhanced.enhancer.attempt.return_value = EnhancementAttempt(
            "failed", attempted=True, latency_ms=6.0
        )
        offline = Agent(self.catalog)
        for agent, session in ((enhanced, "failed"), (offline, "offline")):
            agent.reset(session, {"preference_tags": []})
        message = "I'm looking for Men Shirts. A key requirement is: soft cotton."
        fallback = enhanced.respond("failed", message, 1, 3)
        expected = offline.respond("offline", message, 1, 3)
        self.assertEqual(fallback, expected)
        status = enhanced.get_enhancement_status("failed")
        self.assertEqual(status["outcome"], "failed")
        self.assertTrue(status["attempted"])
        self.assertFalse(status["applied"])

    def test_enhancement_cannot_reask_an_active_attribute(self) -> None:
        config = AgentConfig(openai_enhancement=True)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
            agent = Agent(self.catalog, config)
        enhancement = Enhancement(
            query_rewrite="",
            slot_updates=(),
            candidate_order=(),
            next_attribute="category",
            prompt_tokens=0,
            completion_tokens=0,
        )
        agent.enhancer = mock.Mock()
        agent.enhancer.attempt.return_value = EnhancementAttempt(
            "applied", enhancement=enhancement, attempted=True
        )
        agent.reset("known-slot", {"preference_tags": []})
        response = agent.respond("known-slot", "I'm looking for Men Shirts.", 1, 3)
        self.assertNotEqual(response["ask_attribute"], "category")

    def test_failed_model_output_still_reports_response_usage(self) -> None:
        config = AgentConfig(openai_enhancement=True)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
            agent = Agent(self.catalog, config)
        agent.enhancer = mock.Mock()
        agent.enhancer.attempt.return_value = EnhancementAttempt(
            "failed", attempted=True, prompt_tokens=11, completion_tokens=4
        )
        agent.reset("paid-failure", {"preference_tags": []})
        response = agent.respond("paid-failure", "Show me shirts.", 1, 3)
        self.assertEqual(response["usage"], {"prompt_tokens": 11, "completion_tokens": 4})
        status = agent.get_enhancement_status("paid-failure")
        self.assertEqual(status["prompt_tokens"], 11)
        self.assertEqual(status["completion_tokens"], 4)


class NormalizationAndAPITest(unittest.TestCase):
    def test_malformed_catalog_fields(self) -> None:
        raw = dict(PRODUCTS[2])
        raw.update({"features": None, "description": "one", "categories": "Dresses", "details": None})
        product = Product.from_json(raw)
        self.assertIsNone(product.price)
        self.assertEqual(product.features, ())
        self.assertEqual(product.description, ("one",))
        self.assertEqual(normalize_price("$1,249.95"), 1249.95)
        self.assertIsNone(normalize_price("unknown"))

    def test_api_failure_has_no_retry_and_opens_breaker(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test", "SHOPPING_COPILOT_OPENAI": "1"}, clear=False):
            enhancer = OpenAIEnhancer()
        state = SessionState("api", {"preference_tags": []})
        product = Product.from_json(PRODUCTS[0])
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError) as request:
            result = enhancer.enhance(state, "shirt", [product])
        self.assertIsNone(result)
        self.assertEqual(request.call_count, 1)
        self.assertFalse(enhancer.available)

    def test_api_request_uses_bounded_responses_schema(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                output = {
                    "query_rewrite": "blue cotton shirt",
                    "slot_updates": [],
                    "candidate_order": ["A"],
                    "next_attribute": "material",
                }
                return json.dumps({
                    "output_text": json.dumps(output),
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                }).encode()

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test", "SHOPPING_COPILOT_OPENAI": "1"}, clear=False):
            enhancer = OpenAIEnhancer()
        state = SessionState("api-ok", {"preference_tags": []})
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as request:
            result = enhancer.enhance(state, "shirt", [Product.from_json(PRODUCTS[0])])
        self.assertIsNotNone(result)
        submitted = json.loads(request.call_args.args[0].data)
        self.assertEqual(submitted["model"], "gpt-5.6-luna")
        self.assertEqual(submitted["reasoning"], {"effort": "none"})
        self.assertFalse(submitted["store"])
        self.assertEqual(submitted["text"]["format"]["type"], "json_schema")
        self.assertEqual(request.call_args.kwargs["timeout"], 2.5)

    def test_malformed_success_payload_preserves_reported_usage(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "output_text": "{malformed",
                    "usage": {"input_tokens": 13, "output_tokens": 5},
                }).encode()

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
            enhancer = OpenAIEnhancer(enabled=True)
        state = SessionState("malformed-usage", {"preference_tags": []})
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            attempt = enhancer.attempt(state, "shirt", [Product.from_json(PRODUCTS[0])])
        self.assertEqual(attempt.outcome, "failed")
        self.assertEqual(attempt.prompt_tokens, 13)
        self.assertEqual(attempt.completion_tokens, 5)

    def test_http_protocol_failure_falls_back_without_retry(self) -> None:
        import http.client

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
            enhancer = OpenAIEnhancer(enabled=True)
        state = SessionState("protocol-failure", {"preference_tags": []})
        with mock.patch(
            "urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"partial", 10)
        ) as request:
            attempt = enhancer.attempt(state, "shirt", [Product.from_json(PRODUCTS[0])])
        self.assertEqual(attempt.outcome, "failed")
        self.assertEqual(request.call_count, 1)
        self.assertFalse(enhancer.available)

    def test_terra_configuration_call_limit_and_allowed_candidate_ids(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                output = {
                    "query_rewrite": "blue cotton shirt",
                    "slot_updates": [],
                    "candidate_order": ["NOT-ALLOWED", "A", "A"],
                    "next_attribute": None,
                }
                return json.dumps({
                    "output_text": json.dumps(output),
                    "usage": {"input_tokens": 11, "output_tokens": 4},
                }).encode()

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
            enhancer = OpenAIEnhancer(
                enabled=True,
                model="gpt-5.6-terra",
                reasoning_effort="low",
                max_calls=1,
                timeout_seconds=6,
            )
        state = SessionState("terra", {"preference_tags": []})
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as request:
            result = enhancer.enhance(state, "shirt", [Product.from_json(PRODUCTS[0])])
            limited = enhancer.attempt(state, "shirt", [Product.from_json(PRODUCTS[0])])
        self.assertIsNotNone(result)
        self.assertEqual(result.candidate_order, ("A",))
        self.assertEqual(limited.outcome, "call_limit")
        self.assertEqual(request.call_count, 1)
        submitted = json.loads(request.call_args.args[0].data)
        self.assertEqual(submitted["model"], "gpt-5.6-terra")
        self.assertEqual(submitted["reasoning"], {"effort": "low"})
        self.assertEqual(request.call_args.kwargs["timeout"], 6.0)

    def test_agent_config_validates_openai_controls(self) -> None:
        config = AgentConfig(
            openai_model="gpt-5.6-terra",
            openai_reasoning_effort="low",
            openai_max_calls=10,
            openai_timeout_seconds=6,
            openai_rank_blend=0.65,
        )
        self.assertEqual(config.openai_model, "gpt-5.6-terra")
        self.assertEqual(config.openai_max_calls, 10)
        with self.assertRaises(ValueError):
            AgentConfig(openai_reasoning_effort="extreme")
        with self.assertRaises(ValueError):
            AgentConfig(openai_max_calls=11)
        with self.assertRaises(ValueError):
            AgentConfig(openai_timeout_seconds=0)
        with self.assertRaises(ValueError):
            AgentConfig(openai_rank_blend=1.1)

    def test_api_is_off_without_explicit_opt_in(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test", "SHOPPING_COPILOT_OPENAI": "0"}, clear=False):
            enhancer = OpenAIEnhancer()
        self.assertFalse(enhancer.available)


if __name__ == "__main__":
    unittest.main()
