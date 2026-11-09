import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agents.llm_adapter import (
    BudgetExceeded,
    CallBudget,
    LLMError,
    LLMSettings,
    OpenAICompatibleAgent,
    load_agents,
)
from agents.scheduler import AgentScheduler, build_observation
from core.rules import RuleEngine
from core.simulation import Simulation
from core.state import GameState
from live_server import LiveSession


class ProviderHandler(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(length)),
        })
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        status, payload = self.responses[index]
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, *args):
        pass


@pytest.fixture
def provider():
    ProviderHandler.responses = []
    ProviderHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", ProviderHandler
    server.shutdown()
    server.server_close()
    thread.join()


def valid_response(observation, usage=None):
    return 200, {
        "choices": [{"message": {"content": json.dumps({
            "country_id": observation["country_id"],
            "world_day": observation["world_day"],
            "actions": [{"type": "SET_TAX", "rate": 0.12}],
            "reason": "local test provider",
        })}}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50},
    }


def settings(url, retries=0):
    return LLMSettings(
        provider="local-test", model="mock-cheap-model", base_url=url,
        api_key_env="EOS_TEST_API_KEY", timeout_seconds=2, retries=retries,
        input_price_per_million_usd=0.1, output_price_per_million_usd=0.2,
    )


def test_local_provider_json_action_passes_real_rule_engine(provider, monkeypatch):
    url, handler = provider
    monkeypatch.setenv("EOS_TEST_API_KEY", "not-a-real-secret")
    state = GameState.new()
    observation = build_observation(state, "ELAR")
    handler.responses = [valid_response(observation)]
    budget = CallBudget(max_calls=1, max_cost_usd=0.01)
    agent = OpenAICompatibleAgent("ELAR", settings(url), budget)
    decision = asyncio.run(agent.decide(observation))
    result = RuleEngine(state).apply_decision("ELAR", decision)[0]
    assert result.accepted
    assert state.countries["ELAR"].tax_rate == 0.12
    assert handler.requests[0]["path"] == "/v1/chat/completions"
    assert handler.requests[0]["body"]["max_tokens"] == 700
    summary = budget.summary()
    assert summary["http_attempts"] == 1
    assert summary["input_tokens_known_total"] == 100
    assert summary["output_tokens_known_total"] == 50
    assert summary["known_estimated_cost_usd"] == pytest.approx(0.00002)
    assert "not-a-real-secret" not in json.dumps(agent.drain_usage_events())


def test_invalid_json_retries_then_succeeds(provider, monkeypatch):
    url, handler = provider
    monkeypatch.setenv("EOS_TEST_API_KEY", "dummy")
    state = GameState.new()
    observation = build_observation(state, "ELAR")
    handler.responses = [
        (200, {"choices": [{"message": {"content": "not json"}}]}),
        valid_response(observation),
    ]
    budget = CallBudget(max_calls=2, max_cost_usd=0.01)
    agent = OpenAICompatibleAgent("ELAR", settings(url, retries=1), budget)
    decision = asyncio.run(agent.decide(observation))
    assert decision["actions"][0]["type"] == "SET_TAX"
    assert len(handler.requests) == 2
    assert [event["status"] for event in agent.drain_usage_events()] == ["error", "success"]


def test_http_400_does_not_retry(provider, monkeypatch):
    url, handler = provider
    monkeypatch.setenv("EOS_TEST_API_KEY", "dummy")
    handler.responses = [(400, {"error": "bad request"})]
    budget = CallBudget(max_calls=3, max_cost_usd=0.01)
    agent = OpenAICompatibleAgent("ELAR", settings(url, retries=3), budget)
    with pytest.raises(LLMError):
        asyncio.run(agent.decide({"country_id": "ELAR", "world_day": 0}))
    assert len(handler.requests) == 1
    assert budget.summary()["http_attempts"] == 1


def test_unconfigured_budget_denies_paid_call(monkeypatch):
    monkeypatch.setenv("EOS_TEST_API_KEY", "dummy")
    budget = CallBudget()
    agent = OpenAICompatibleAgent(
        "ELAR", settings("http://127.0.0.1:1/v1"), budget
    )
    with pytest.raises(LLMError):
        asyncio.run(agent.decide({"country_id": "ELAR", "world_day": 0}))
    assert budget.summary()["http_attempts"] == 0


def test_missing_usage_and_price_are_unknown_not_zero(provider, monkeypatch):
    url, handler = provider
    monkeypatch.setenv("EOS_TEST_API_KEY", "dummy")
    state = GameState.new()
    observation = build_observation(state, "ELAR")
    status, payload = valid_response(observation)
    del payload["usage"]
    handler.responses = [(status, payload)]
    budget = CallBudget(max_calls=1, max_cost_usd=0.01)
    configured = settings(url)
    configured = LLMSettings(
        provider=configured.provider, model=configured.model, base_url=configured.base_url,
        api_key_env=configured.api_key_env, timeout_seconds=2, retries=0,
    )
    agent = OpenAICompatibleAgent("ELAR", configured, budget)
    asyncio.run(agent.decide(observation))
    summary = budget.summary()
    assert summary["unknown_usage_calls"] == 1
    assert summary["unknown_cost_calls"] == 1
    assert summary["known_estimated_cost_usd"] == 0
    assert agent.drain_usage_events()[0]["estimated_cost_usd"] == "unknown"


def test_mixed_model_config_loads_mock_and_llm(tmp_path):
    config = tmp_path / "models.json"
    config.write_text(json.dumps({"countries": {
        "ELAR": {"mode": "mock"},
        "MARIS": {
            "mode": "openai_compatible", "provider": "local", "model": "cheap",
            "base_url": "http://127.0.0.1:1/v1", "api_key_env": "EOS_TEST_API_KEY",
        },
    }}), encoding="utf-8")
    agents = load_agents(config, CallBudget(max_calls=1, max_cost_usd=0.01))
    assert len(agents) == 2
    assert type(agents["ELAR"]).__name__ == "HeuristicAgent"
    assert type(agents["MARIS"]).__name__ == "OpenAICompatibleAgent"


def test_scheduler_mixes_llm_and_mock_and_records_usage(provider, monkeypatch):
    url, handler = provider
    monkeypatch.setenv("EOS_TEST_API_KEY", "dummy")
    simulation = Simulation.new()
    observation = build_observation(simulation.state, "ELAR")
    handler.responses = [valid_response(observation)]
    budget = CallBudget(max_calls=1, max_cost_usd=0.01)
    llm = OpenAICompatibleAgent("ELAR", settings(url), budget)
    simulation.engine.planner = AgentScheduler({"ELAR": llm})
    simulation.run(1)
    assert simulation.state.countries["ELAR"].tax_rate == 0.12
    assert any(event["type"] == "llm_decision" for event in simulation.state.event_log)
    assert any(event["type"] == "llm_call" and event["status"] == "success" for event in simulation.state.event_log)
    assert sum(event["type"] == "agent_decision" for event in simulation.state.event_log) == 4


def test_scheduler_llm_failure_falls_back_without_crashing(provider, monkeypatch):
    url, handler = provider
    monkeypatch.setenv("EOS_TEST_API_KEY", "dummy")
    simulation = Simulation.new()
    handler.responses = [(200, {"choices": [{"message": {"content": "invalid"}}]})]
    budget = CallBudget(max_calls=1, max_cost_usd=0.01)
    llm = OpenAICompatibleAgent("ELAR", settings(url), budget)
    simulation.engine.planner = AgentScheduler({"ELAR": llm})
    assert simulation.run(1) == 1
    assert any(event["type"] == "agent_fallback" for event in simulation.state.event_log)
    elar_actions = [
        entry for entry in simulation.state.action_log if entry["result"]["actor"] == "ELAR"
    ]
    assert elar_actions[0]["result"]["action_type"] == "NO_OP"


def test_scheduler_records_llm_diary_only_for_model_country(provider, monkeypatch):
    url, handler = provider
    monkeypatch.setenv("EOS_TEST_API_KEY", "dummy")
    simulation = Simulation.new()
    observation = build_observation(simulation.state, "ELAR")
    decision = {
        "country_id": observation["country_id"],
        "world_day": observation["world_day"],
        "actions": [{"type": "SET_TAX", "rate": 0.12}],
        "reason": "需要增加国库收入",
        "diary": {
            "title": "先稳住国库",
            "mood": "谨慎",
            "text": "今年的粮食还算充足，但国库太薄。我把税率稍微提高，暂缓扩张，等财政稳定后再考虑新的前哨。",
        },
    }
    handler.responses = [(200, {
        "choices": [{"message": {"content": json.dumps(decision, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    })]
    budget = CallBudget(max_calls=1, max_cost_usd=0.01)
    llm = OpenAICompatibleAgent("ELAR", settings(url), budget)
    simulation.engine.planner = AgentScheduler({"ELAR": llm})
    simulation.run(1)
    diaries = [e for e in simulation.state.event_log if e["type"] == "llm_diary"]
    assert len(diaries) == 1
    entry = diaries[0]
    assert entry["country_id"] == "ELAR"
    assert entry["title"] == "先稳住国库"
    assert entry["mood"] == "谨慎"
    assert "税率" in entry["text"]
    assert entry["synthetic"] is False
    assert entry["actions"][0]["type"] == "SET_TAX"
    assert "dummy" not in json.dumps(entry, ensure_ascii=False)
    assert not any(
        e["type"] == "llm_diary" and e["country_id"] != "ELAR"
        for e in simulation.state.event_log
    )


def test_live_session_connection_test(provider, monkeypatch):
    import os
    url, handler = provider
    handler.responses = [(200, {"choices": [{"message": {"content": "OK"}}]})]
    monkeypatch.setenv("EOS_TEST_API_KEY", "dummy")
    session = LiveSession(speed=1.0, maximum_day=1, paused=True)
    try:
        result = session.configure_agent("ELAR", {
            "mode": "openai_compatible",
            "provider": "local-test",
            "model": "mock-cheap-model",
            "base_url": url,
            "api_key_env": "EOS_TEST_API_KEY",
            "timeout_seconds": 2,
            "retries": 0,
            "max_output_tokens": 8,
        })
        assert result["ok"]
        tested = session.test_agent("ELAR")
        assert tested["ok"]
        assert tested["model"] == "mock-cheap-model"
        assert tested["latency_ms"] >= 0
        payload = session.agent_payload()["countries"]["ELAR"]
        assert payload["last_test"]["ok"] is True
        assert "dummy" not in json.dumps(payload)
        handler.responses = [(401, {"error": {"message": "invalid key"}})]
        failed = session.test_agent("ELAR")
        assert failed["ok"] is False
        assert failed["status_code"] == 401
    finally:
        session._stop.set()
        session.thread.join(timeout=2)
        monkeypatch.delenv("EOS_TEST_API_KEY", raising=False)
