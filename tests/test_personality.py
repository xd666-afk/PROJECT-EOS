import asyncio

from agents.heuristic import HeuristicAgent
from agents.llm_adapter import CallBudget, LLMSettings, OpenAICompatibleAgent
from agents.scheduler import build_observation
from core.city_governance import CityManager
from core.simulation import Simulation
from core.state import GameState
from live_server import LiveSession


def test_personality_persists_in_save_and_observation(tmp_path):
    simulation = Simulation.new()
    simulation.state.countries["ELAR"].personality = "aggressive"
    observation = build_observation(simulation.state, "ELAR")
    assert observation["country"]["personality"] == "aggressive"

    path = tmp_path / "personality_save.json"
    simulation.state.save(path)
    restored = GameState.load(path)
    assert restored.countries["ELAR"].personality == "aggressive"
    assert restored.countries["MARIS"].personality == "neutral"


def test_mock_agents_use_personality_workers_and_reason():
    expectations = {
        "aggressive": ("激进", 0.45, 0.4),
        "conservative": ("保守", 0.6, 0.2),
    }
    for personality, (label, agriculture, mining) in expectations.items():
        simulation = Simulation.new()
        simulation.state.countries["ELAR"].personality = personality
        observation = build_observation(simulation.state, "ELAR")
        decision = asyncio.run(HeuristicAgent("ELAR").decide(observation))
        assert label in decision["reason"]
        workers = next(
            (
                action for action in decision["actions"]
                if action["type"] == "ALLOCATE_WORKERS"
            ),
            None,
        )
        if workers is not None:
            assert workers["agriculture"] == agriculture
            assert workers["mining"] == mining


def test_llm_prompt_contains_personality_guidance():
    simulation = Simulation.new()
    simulation.state.countries["ELAR"].personality = "conservative"
    observation = build_observation(simulation.state, "ELAR")
    settings = LLMSettings(
        provider="test", model="mock", base_url="https://example.test",
        api_key_env="EOS_TEST_KEY",
    )
    agent = OpenAICompatibleAgent("ELAR", settings, CallBudget())
    request = agent._decision_request(observation)
    system = request["messages"][0]["content"]
    assert "保守" in system
    assert "避免远征" in system
    assert "不改变 JSON 结构" in system


def test_live_session_personality_endpoint_and_mock_reconfigure():
    session = LiveSession(speed=1.0, maximum_day=1, paused=True)
    try:
        changed = session.set_personality("ELAR", "conservative")
        assert changed["ok"]
        assert changed["personality_label"] == "保守"
        payload = session.agent_payload()["countries"]["ELAR"]
        assert payload["personality"] == "conservative"
        assert payload["personality_label"] == "保守"
        assert any(
            event["type"] == "agent_personality_changed"
            and event["country_id"] == "ELAR"
            for event in session.simulation.state.event_log
        )

        configured = session.configure_agent(
            "ELAR", {"mode": "mock", "personality": "aggressive"}
        )
        assert configured["ok"]
        assert session.simulation.state.countries["ELAR"].personality == "aggressive"
        assert configured["personality"] == "aggressive"

        invalid = session.set_personality("ELAR", "reckless")
        assert not invalid["ok"]
        assert session.simulation.state.countries["ELAR"].personality == "aggressive"
    finally:
        session._stop.set()
        session.thread.join(timeout=2)


def test_city_manager_personality_changes_focus():
    for personality, expected in (("aggressive", "industry"), ("conservative", "growth")):
        simulation = Simulation.new()
        country = simulation.state.countries["ELAR"]
        country.personality = personality
        city = country.cities[0]
        city.managed_by = "ai"
        city.food_output = 999.0
        city.food_need = 1.0
        CityManager(simulation.state).plan(simulation.engine)
        assert city.focus == expected, personality


def test_aggressive_mock_recruits_earlier_than_conservative():
    for personality, should_recruit in (("aggressive", True), ("conservative", False)):
        simulation = Simulation.new()
        country = simulation.state.countries["ELAR"]
        country.personality = personality
        country.treasury = 110.0
        country.food = 200.0
        country.armies = []
        simulation.state.day_index = 100
        observation = build_observation(simulation.state, "ELAR")
        decision = asyncio.run(HeuristicAgent("ELAR").decide(observation))
        recruit = next(
            (action for action in decision["actions"]
             if action["type"] == "MILITARY" and action["operation"] == "RECRUIT"),
            None,
        )
        assert (recruit is not None) is should_recruit, personality
        if should_recruit:
            # 激进档偏爱突击兵种，但 90 天前只买得起无科技门槛的征召民兵。
            assert recruit["strength"] == 2
            assert recruit["unit"] in simulation.state.config["units"]
