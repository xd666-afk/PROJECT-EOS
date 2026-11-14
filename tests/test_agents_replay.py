import asyncio

from agents.heuristic import HeuristicAgent
from agents.scheduler import AgentScheduler, build_observation
from core.replay import replay_saved_actions
from core.simulation import Simulation


def test_observation_is_limited_to_country_and_action_protocol():
    simulation = Simulation.new()
    observation = build_observation(simulation.state, "ELAR")
    assert len(observation["tiles"]) == 19
    assert "monthly_temp_c" not in observation["tiles"][0]
    assert set(observation["rules"]["allowed_actions"]) == {
        "BUILD", "ALLOCATE_WORKERS", "SET_TAX", "SET_RESEARCH", "TRADE", "SET_POLICY",
        "SETTLE", "DIPLOMACY", "MILITARY", "SET_CITY_FOCUS", "SET_CITY_ZONE",
        "SET_CITY_GOVERNANCE", "SET_CITY_BUDGET",
    }
    assert len(observation["country"]["cities"]) == 1
    city = observation["country"]["cities"][0]
    assert city["city_id"] and "managed_by" in city and city["tiles_detail"]
    assert len(observation) <= 16
    assert observation["incoming_threats"] == []


def test_ai_rejects_unfair_incoming_trade():
    simulation = Simulation.new(use_mock_agents=False)
    engine = simulation.engine
    proposal = engine.apply_action("ELAR", {
        "type": "TRADE", "target": "MARIS", "offer_food": 0.01,
        "request_treasury": 90,
    })
    assert proposal.accepted
    observation = build_observation(simulation.state, "MARIS")
    decision = asyncio.run(HeuristicAgent("MARIS").decide(observation))
    trade_actions = [a for a in decision["actions"] if a["type"] == "TRADE"]
    assert trade_actions and trade_actions[0]["operation"] == "REJECT"
    assert "MARIS" in engine.state.countries and engine.state.countries["MARIS"].treasury == 100


def test_ai_research_targets_lowest_technology_to_advance_era():
    agent = HeuristicAgent("ELAR")
    country = {
        "technology": {"agriculture": 5, "bronze_metallurgy": 2, "writing": 2},
    }
    choice = agent._research_choice(country)
    assert choice in {"bronze_metallurgy", "writing"}


def test_player_controlled_country_is_skipped_by_ai_planning():
    simulation = Simulation.new()
    simulation.scheduler.set_player_country("ELAR")
    results = simulation.scheduler.plan(simulation.engine)
    assert "ELAR" not in results
    assert set(results) == {"MARIS", "VAYR", "SAHAR"}
    assert not any(
        entry["result"]["actor"] == "ELAR" for entry in simulation.state.action_log
    )
    simulation.scheduler.set_player_country(None)
    resumed = simulation.scheduler.plan(simulation.engine)
    assert set(resumed) == {"ELAR", "MARIS", "VAYR", "SAHAR"}


def test_agent_observation_cannot_mutate_live_state():
    class MutatingAgent:
        async def decide(self, observation):
            observation["country"]["workers"]["agriculture"] = 0.0
            observation["pending_incoming_trades"][0]["offer_food"] = 999999.0
            observation["rules"]["buildings"]["FARM"]["cost"] = 0.0
            observation["recent_action_feedback"].clear()
            return {
                "country_id": "MARIS", "world_day": 0,
                "actions": [{"type": "NO_OP"}], "reason": "mutation attempt",
            }

    simulation = Simulation.new(use_mock_agents=False)
    proposal = simulation.engine.apply_action("ELAR", {
        "type": "TRADE", "target": "MARIS", "offer_food": 5, "request_treasury": 3,
    })
    trade = simulation.state.trades[proposal.effects["proposal_id"]]
    original_workers = dict(simulation.state.countries["MARIS"].workers)
    scheduler = AgentScheduler({"MARIS": MutatingAgent()})
    scheduler.plan(simulation.engine)
    assert trade["offer_food"] == 5 and trade["status"] == "PENDING"
    assert simulation.state.countries["MARIS"].workers == original_workers
    assert simulation.state.config["buildings"]["FARM"]["cost"] == 18
    assert len(simulation.state.action_log) > 1


def test_four_mock_agents_run_365_days_and_change_real_state(tmp_path):
    simulation = Simulation.new()
    assert simulation.run(365) == 365
    assert len(simulation.state.countries) == 4
    assert len(simulation.state.action_log) >= 16
    for country in simulation.state.countries.values():
        assert country.food >= 0 and country.treasury >= 0
        assert country.population > 0
        assert country.technology[country.research_field] >= 1
        assert country.last_economy["food_production"] > 0
        assert country.policy != "BALANCED"
        assert sum(city.population for city in country.cities) == country.population
        assert len(country.cities) >= 1
        assert country.buildings or country.projects
    save = tmp_path / "year.json"
    simulation.state.save(save)
    restored = Simulation.load(save)
    assert restored.state.fingerprint() == simulation.state.fingerprint()


def test_action_log_replay_reproduces_dynamic_state(tmp_path):
    original = Simulation.new()
    original.run(100)
    path = tmp_path / "replay.json"
    original.state.save(path)
    replayed = replay_saved_actions(path)
    assert replayed.fingerprint() == original.state.fingerprint()


def test_replay_respects_custom_start_year(tmp_path):
    simulation = Simulation.new()
    simulation.state.configure_starting_era(-799)
    simulation.run(100)
    path = tmp_path / "iron_age_replay.json"
    simulation.state.save(path)
    replayed = replay_saved_actions(path)
    assert replayed.start_astronomical_year == -799
    assert replayed.fingerprint() == simulation.state.fingerprint()


def test_resume_with_agents_matches_uninterrupted_run(tmp_path):
    continuous = Simulation.new()
    continuous.run(120)
    interrupted = Simulation.new()
    interrupted.run(77)
    path = tmp_path / "resume.json"
    interrupted.state.save(path)
    restored = Simulation.load(path)
    restored.run(43)
    assert restored.state.fingerprint() == continuous.state.fingerprint()
