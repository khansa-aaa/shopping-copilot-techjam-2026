from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from demo.api.app import MAX_BODY_BYTES, create_app
from demo.api.service import MAX_TURNS, ServiceError, ShoppingService
from shopping_copilot.agent import Agent
from shopping_copilot.state import SessionState


def _catalog_rows() -> list[dict]:
    specifications = (
        ("Blue cotton running shirt", "Alpha", "Shirts", "cotton", "quick dry"),
        ("Black leather winter boots", "Beta", "Boots", "leather", "warm lining"),
        ("Red silk evening dress", "Gamma", "Dresses", "silk", "formal style"),
        ("Green nylon hiking backpack", "Delta", "Backpacks", "nylon", "water resistant"),
        ("White wool classic scarf", "Epsilon", "Scarves", "wool", "soft knit"),
        ("Brown leather travel wallet", "Zeta", "Wallets", "leather", "RFID pockets"),
        ("Grey polyester gym shorts", "Eta", "Shorts", "polyester", "breathable"),
        ("Pink cotton casual cap", "Theta", "Hats", "cotton", "adjustable"),
        ("Silver steel sport watch", "Iota", "Watches", "steel", "water resistant"),
        ("Purple velvet cushion cover", "Kappa", "Covers", "velvet", "zip closure"),
        ("Orange rubber yoga mat", "Lambda", "Mats", "rubber", "non slip"),
        ("Beige linen work trousers", "Mu", "Trousers", "linen", "straight fit"),
        ("Navy canvas laptop sleeve", "Nu", "Sleeves", "canvas", "padded"),
        ("Gold metal reading lamp", "Xi", "Lamps", "metal", "adjustable arm"),
    )
    rows: list[dict] = []
    for index, (title, store, category, material, feature) in enumerate(specifications, 1):
        rows.append(
            {
                "parent_asin": f"TEST{index:04d}",
                "title": title,
                "features": [feature, f"{material} construction"],
                "description": [f"Catalog fixture for {category.lower()}"],
                "price": None if index == 14 else float(10 + index * 4),
                "categories": ["Test catalog", "Products", category],
                "details": {"Material": material, "Fixture": {"index": index}},
                "average_rating": 4.0 + (index % 8) / 10,
                "rating_number": index * 17,
                "store": store,
            }
        )
    return rows


class FastAPIProductAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.environment = mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False)
        cls.environment.start()
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.catalog_path = cls.root / "catalog.jsonl"
        cls.catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in _catalog_rows()),
            encoding="utf-8",
        )
        cls.service = ShoppingService(cls.catalog_path)
        cls.service.initialize()
        if cls.service.status != "ready":
            raise RuntimeError(f"test service failed to initialize: {cls.service.startup_error}")
        app = create_app(
            service=cls.service,
            static_directory=cls.root / "missing-static-directory",
            initialize_in_background=False,
        )
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        index = Agent._indexes.pop(cls.catalog_path.resolve(), None)
        if index is not None:
            index.connection.close()
        cls.directory.cleanup()
        cls.environment.stop()

    def _create_session(
        self,
        *,
        mode: str = "offline",
        marketplace: str = "SG",
        preference_tags: list[str] | None = None,
        request_id: str | None = None,
    ) -> tuple[dict, dict]:
        payload = {
            "request_id": request_id or str(uuid.uuid4()),
            "mode": mode,
            "marketplace": marketplace,
            "preference_tags": preference_tags or [],
        }
        response = self.client.post("/api/sessions", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), payload

    def _send(
        self,
        session_id: str,
        *,
        message: str,
        expected_turn: int,
        request_id: str | None = None,
    ):
        return self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={
                "request_id": request_id or str(uuid.uuid4()),
                "message": message,
                "expected_turn": expected_turn,
            },
        )

    def test_health_reports_loaded_capabilities_without_leaking_credentials(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["catalog_count"], len(_catalog_rows()))
        self.assertEqual(payload["max_turns"], 10)
        self.assertEqual(payload["agent_contract"], "reset/respond-v1")
        self.assertEqual(payload["hybrid_model"], "gpt-5.6-terra")
        self.assertFalse(payload["hybrid_available"])
        self.assertIn({"code": "SG", "label": "Singapore", "domain": "www.amazon.sg"}, payload["marketplaces"])
        serialized = response.text.casefold()
        self.assertNotIn("openai_api_key", serialized)
        self.assertNotIn("authorization", serialized)

        # A key added after initialization cannot activate the already-created
        # enhancer; health must continue to describe the loaded process.
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "added-too-late"}, clear=False):
            self.assertFalse(self.client.get("/api/health").json()["hybrid_available"])

    def test_hybrid_capability_stays_consent_gated_while_circuit_is_open(self) -> None:
        enhancer = self.service.hybrid_agent.enhancer
        previous_enabled = enhancer.enabled
        previous_breaker = enhancer._circuit_open_until
        try:
            enhancer.enabled = True
            enhancer._circuit_open_until = float("inf")
            self.assertFalse(enhancer.available)
            self.assertTrue(self.client.get("/api/health").json()["hybrid_available"])
        finally:
            enhancer.enabled = previous_enabled
            enhancer._circuit_open_until = previous_breaker

    def test_session_creation_is_idempotent_and_normalizes_inputs(self) -> None:
        request_id = str(uuid.uuid4())
        payload = {
            "request_id": request_id,
            "mode": "offline",
            "marketplace": " sg ",
            "preference_tags": [" Comfort ", "comfort", " lightweight  gear "],
        }
        first = self.client.post("/api/sessions", json=payload)
        replay = self.client.post("/api/sessions", json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), first.json())
        body = first.json()
        self.assertRegex(body["session_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(body["turn"], 0)
        self.assertEqual(body["mode"], "offline")
        self.assertEqual(body["marketplace"], "SG")
        state = self.service.offline_agent.sessions[body["session_id"]]
        self.assertEqual(state.profile_priors, ("comfort", "lightweight gear"))

        conflict = self.client.post(
            "/api/sessions",
            json={**payload, "mode": "hybrid"},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_official_agent_response_is_nested_unchanged_and_products_keep_order(self) -> None:
        session, _ = self._create_session(marketplace="SG")
        response = self._send(
            session["session_id"],
            message="I'm still exploring and would like to see a broad range.",
            expected_turn=1,
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            set(body),
            {"session_id", "turn", "max_turns", "status", "agent_response", "products", "experience", "expert_state", "meta"},
        )
        official = body["agent_response"]
        self.assertEqual(set(official), {"message", "ask_attribute", "recommendations", "usage"})
        self.assertLessEqual(len(official["recommendations"]), 10)
        self.assertTrue(official["recommendations"])
        self.assertTrue(all(set(item) == {"parent_asin"} for item in official["recommendations"]))
        identifiers = [item["parent_asin"] for item in official["recommendations"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(set(identifiers).issubset({row["parent_asin"] for row in _catalog_rows()}))
        self.assertEqual([item["parent_asin"] for item in body["products"]], identifiers)
        self.assertEqual([item["rank"] for item in body["products"]], list(range(1, len(identifiers) + 1)))
        for product in body["products"]:
            self.assertEqual(product["data_source"], "techjam_catalog_snapshot")
            self.assertFalse(product["is_live"])
            self.assertIn("amazon.sg/s?k=TEST", product["amazon_url"])
            self.assertLessEqual(len(product["match_reasons"]), 2)
        self.assertEqual(body["meta"]["used_mode"], "offline")
        self.assertEqual(body["meta"]["estimated_cost_usd"], 0.0)
        self.assertFalse(body["meta"]["idempotency_replay"])
        self.assertIn("not live Amazon inventory", body["experience"]["snapshot_disclosure"])

    def test_message_idempotency_does_not_advance_agent_state_twice(self) -> None:
        session, _ = self._create_session()
        session_id = session["session_id"]
        request_id = str(uuid.uuid4())
        first = self._send(
            session_id,
            request_id=request_id,
            message="I'm looking for Shirts. A key requirement is: cotton.",
            expected_turn=1,
        )
        replay = self._send(
            session_id,
            request_id=request_id,
            message="  I'm looking for Shirts.   A key requirement is: cotton.  ",
            expected_turn=1,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        expected = copy.deepcopy(first.json())
        expected["meta"]["idempotency_replay"] = True
        self.assertEqual(replay.json(), expected)
        self.assertEqual(self.service.sessions[session_id].turn, 1)
        self.assertEqual(self.service.offline_agent.sessions[session_id].turn, 1)

        conflict = self._send(
            session_id,
            request_id=request_id,
            message="A different message",
            expected_turn=1,
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_turn_conflicts_are_explicit_and_concurrent_turns_are_serialized(self) -> None:
        session, _ = self._create_session()
        session_id = session["session_id"]
        premature = self._send(session_id, message="cotton", expected_turn=2)
        self.assertEqual(premature.status_code, 409)
        self.assertEqual(
            premature.json(),
            {
                "error": {
                    "code": "TURN_CONFLICT",
                    "message": "The next message must be turn 1.",
                    "expected_next_turn": 1,
                }
            },
        )

        barrier = threading.Barrier(2)

        def submit(request_id: str):
            barrier.wait()
            try:
                result = self.service.respond(
                    session_id,
                    request_id=request_id,
                    message="Show me a broad selection.",
                    expected_turn=1,
                )
                return "ok", result
            except ServiceError as exc:
                return "error", exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(submit, [uuid.uuid4().hex, uuid.uuid4().hex]))
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1)
        errors = [value for kind, value in outcomes if kind == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].code, "TURN_CONFLICT")
        self.assertEqual(errors[0].expected_next_turn, 2)
        self.assertEqual(self.service.sessions[session_id].turn, 1)

    def test_turn_ten_completes_and_never_asks_another_question(self) -> None:
        session, _ = self._create_session()
        session_id = session["session_id"]
        body: dict = {}
        for turn in range(1, MAX_TURNS + 1):
            response = self._send(
                session_id,
                message="Show me other options that fit the request.",
                expected_turn=turn,
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
        self.assertEqual(body["turn"], 10)
        self.assertEqual(body["status"], "complete")
        self.assertIsNone(body["agent_response"]["ask_attribute"])
        self.assertEqual(body["experience"]["quick_replies"], [])

        overflow = self._send(
            session_id,
            message="One more turn",
            expected_turn=10,
        )
        self.assertEqual(overflow.status_code, 409)
        self.assertEqual(overflow.json()["error"]["code"], "TURN_LIMIT_REACHED")

    def test_hybrid_mode_fails_closed_to_offline_without_a_key(self) -> None:
        session, _ = self._create_session(mode="hybrid", preference_tags=["comfort"])
        with mock.patch.object(urllib.request, "urlopen") as network:
            response = self._send(
                session["session_id"],
                message="I'm looking for Shirts. A key requirement is: cotton.",
                expected_turn=1,
            )
        self.assertEqual(response.status_code, 200, response.text)
        network.assert_not_called()
        body = response.json()
        self.assertEqual(body["meta"]["requested_mode"], "hybrid")
        self.assertEqual(body["meta"]["used_mode"], "offline_fallback")
        self.assertEqual(body["meta"]["fallback_reason"], "unavailable")
        self.assertEqual(body["agent_response"]["usage"], {"prompt_tokens": 0, "completion_tokens": 0})
        self.assertEqual(body["meta"]["estimated_cost_usd"], 0.0)
        enhancement = body["expert_state"]["enhancement"]
        self.assertEqual(enhancement["model"], "gpt-5.6-terra")
        self.assertEqual(enhancement["reasoning_effort"], "low")
        self.assertTrue(enhancement["requested"])
        self.assertFalse(enhancement["enabled"])
        self.assertFalse(enhancement["attempted"])
        self.assertFalse(enhancement["applied"])

    def test_category_quick_reply_is_parsed_as_category_evidence(self) -> None:
        reply = self.service._quick_replies("category", [{"category": "Shirts"}])[0]
        state = SessionState("quick-reply", {"preference_tags": []})
        state.start_turn(reply["message"], 1)
        categories = state.active_evidence("category")
        self.assertEqual([item.value for item in categories], ["Shirts"])
        self.assertTrue(categories[0].hard)

    def test_agent_failures_roll_back_and_allow_a_safe_retry(self) -> None:
        session, _ = self._create_session()
        session_id = session["session_id"]
        agent = self.service.offline_agent
        with mock.patch.object(agent, "respond", side_effect=RuntimeError("synthetic failure")):
            failed = self._send(
                session_id,
                message="Show me shirts.",
                expected_turn=1,
            )
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["error"]["code"], "AGENT_FAILURE_RESET_REQUIRED")
        self.assertNotIn("synthetic failure", failed.text)
        self.assertEqual(self.service.sessions[session_id].turn, 0)
        self.assertEqual(agent.sessions[session_id].turn, 0)

        retried = self._send(
            session_id,
            message="Show me shirts.",
            expected_turn=1,
        )
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["turn"], 1)

    def test_delete_is_idempotent_and_removes_agent_state(self) -> None:
        request_id = str(uuid.uuid4())
        session, creation_payload = self._create_session(request_id=request_id)
        session_id = session["session_id"]
        first = self.client.delete(f"/api/sessions/{session_id}")
        second = self.client.delete(f"/api/sessions/{session_id}")
        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        self.assertNotIn(session_id, self.service.sessions)
        self.assertNotIn(session_id, self.service.offline_agent.sessions)
        missing = self._send(session_id, message="hello", expected_turn=1)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "SESSION_NOT_FOUND")

        recreated = self.client.post("/api/sessions", json=creation_payload)
        self.assertEqual(recreated.status_code, 201)
        self.assertNotEqual(recreated.json()["session_id"], session_id)
        self.assertIn(recreated.json()["session_id"], self.service.sessions)

    def test_adapter_failure_preserves_agent_result_and_retries_without_reranking(self) -> None:
        session, _ = self._create_session(mode="hybrid")
        session_id = session["session_id"]
        request_id = str(uuid.uuid4())
        agent = self.service.hybrid_agent
        with mock.patch.object(agent, "respond", wraps=agent.respond) as respond, mock.patch.object(
            agent.enhancer, "attempt", wraps=agent.enhancer.attempt
        ) as enhancement_attempt:
            with mock.patch.object(self.service, "_display_products", side_effect=RuntimeError("synthetic enrichment failure")):
                failed = self._send(
                    session_id,
                    request_id=request_id,
                    message="Show me shirts.",
                    expected_turn=1,
                )
            web_turn_after_failure = self.service.sessions[session_id].turn
            agent_turn_after_failure = agent.sessions[session_id].turn
            blocked = self._send(
                session_id,
                request_id=str(uuid.uuid4()),
                message="Try a different turn.",
                expected_turn=1,
            )
            retried = self._send(
                session_id,
                request_id=request_id,
                message="Show me shirts.",
                expected_turn=1,
            )
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["error"]["code"], "ADAPTER_FAILURE_RETRYABLE")
        self.assertNotIn("synthetic enrichment failure", failed.text)
        self.assertEqual(web_turn_after_failure, 0)
        self.assertEqual(agent_turn_after_failure, 1)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "PENDING_REQUEST_RETRY_REQUIRED")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["turn"], 1)
        self.assertTrue(retried.json()["meta"]["idempotency_replay"])
        self.assertEqual(respond.call_count, 1)
        self.assertEqual(enhancement_attempt.call_count, 1)

    def test_validation_body_limit_host_filter_and_security_headers(self) -> None:
        cases = (
            ({"request_id": "not-a-uuid", "mode": "offline", "marketplace": "SG"}, "request_id"),
            ({"request_id": str(uuid.uuid4()), "mode": "online", "marketplace": "SG"}, "mode"),
            ({"request_id": str(uuid.uuid4()), "mode": "offline", "marketplace": "ZZ"}, "marketplace"),
            (
                {
                    "request_id": str(uuid.uuid4()),
                    "mode": "offline",
                    "marketplace": "SG",
                    "preference_tags": [str(index) for index in range(9)],
                },
                "preference_tags",
            ),
        )
        for payload, field in cases:
            with self.subTest(field=field):
                response = self.client.post("/api/sessions", json=payload)
                self.assertEqual(response.status_code, 422)
                error = response.json()["error"]
                self.assertEqual(error["code"], "VALIDATION_ERROR")
                self.assertIn(field, {item["field"] for item in error["fields"]})

        oversized = self.client.post(
            "/api/sessions",
            content=b"x" * (MAX_BODY_BYTES + 1),
            headers={"content-type": "application/json", "content-length": "invalid"},
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.json()["error"]["code"], "REQUEST_TOO_LARGE")

        hostile = self.client.get("/api/health", headers={"host": "example.invalid"})
        self.assertEqual(hostile.status_code, 400)

        for response in (self.client.get("/api/health"), oversized, hostile):
            with self.subTest(status=response.status_code):
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                self.assertEqual(response.headers["x-frame-options"], "DENY")
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
                self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
                self.assertIn("camera=()", response.headers["permissions-policy"])

    def test_not_ready_response_is_structured_and_retryable(self) -> None:
        service = ShoppingService(self.catalog_path)
        app = create_app(
            service=service,
            static_directory=self.root / "missing-static-directory",
            initialize_in_background=False,
        )
        with TestClient(app) as client:
            health = client.get("/api/health")
            self.assertEqual(health.json()["status"], "starting")
            response = client.post(
                "/api/sessions",
                json={"request_id": str(uuid.uuid4()), "mode": "offline", "marketplace": "SG"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["retry-after"], "2")
        self.assertEqual(response.json()["error"]["code"], "ENGINE_NOT_READY")


if __name__ == "__main__":
    unittest.main()
