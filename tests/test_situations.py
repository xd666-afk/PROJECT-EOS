from copy import deepcopy
from pathlib import Path
import pytest

from core import situations as sit
from core.rules import RuleEngine
from core.state import GameState, relation_key

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def story_state():
    return GameState.load(ROOT / "examples/civil_networks/save.json")


def advance(state, days=1):
    engine = RuleEngine(state, enable_city_manager=False, enable_frontier_ai=False)
    for _ in range(days):
        assert engine.step_day(force=True)


def create(state, preset="drought", country="A", **params):
    return sit.create(state, {"preset_id": preset, "country_id": country, **params})


@pytest.mark.parametrize("preset", list(sit.PRESETS))
def test_all_presets_have_real_effects_and_expire(story_state, preset):
    state = story_state
    country = state.countries["A"]
    # Research/engineering need actual work to measure their effect.
    country.projects.append(dict(project_id="test-project", tile=list(country.cities[0].center),
                                 building="FARM", total_days=100., remaining_days=100.))
    baseline = deepcopy(state)
    params = {"partner_id": "B"} if sit.PRESETS[preset].get("bilateral") else {}
    item = create(state, preset, duration=2, **params)
    advance(state, 2)
    advance(baseline, 2)
    actual = state.situations[item["id"]]
    kind = next(iter(sit.PRESETS[preset]["effects"]))
    assert actual["status"] == "ended"
    assert abs(actual["totals"].get(kind, 0)) > 0, (preset, actual)
    assert sit.factor(state, "A", kind) == 1.
    if kind == "food":
        assert state.countries["A"].last_economy["food_production"] != baseline.countries["A"].last_economy["food_production"]
    assert actual["chronicle"] and actual["final"]


def test_parallel_focus_independent_and_mutation_keeps_results(story_state):
    state = story_state
    first = create(state, duration=5)
    second = create(state, "harvest", "B", duration=10)
    advance(state)
    totals = deepcopy(state.situations[first["id"]]["totals"])
    sit.update(state, first["id"], {"intensity": 3, "remaining_days": 2})
    assert state.situations[first["id"]]["totals"] == totals
    advance(state, 2)
    assert state.situations[first["id"]]["status"] == "ended"
    assert state.situations[second["id"]]["status"] == "active"
    before = state.countries["B"].food
    sit.end(state, second["id"])
    assert state.countries["B"].food == before


def test_conflicts_pair_order_and_invalid_requests_are_atomic(story_state):
    state = story_state
    create(state)
    before = deepcopy(state.to_dict())
    for payload in ({"preset_id": "harvest", "country_id": "A"},
                    {"preset_id": "unknown", "country_id": "A"},
                    {"preset_id": "commerce", "country_id": "A", "duration": True},
                    {"preset_id": "commerce", "country_id": "A", "intensity": 2.5},
                    {"preset_id": "commerce", "country_id": "A", "text": "custom"},
                    {"preset_id": "friendship", "country_id": "A", "partner_id": "A"},
                    {"preset_id": "commerce", "country_id": "missing"}):
        with pytest.raises(ValueError):
            sit.create(state, payload)
        assert state.to_dict() == before
    item = create(state, "friendship", partner_id="B")
    with pytest.raises(ValueError):
        create(state, "friction", "B", partner_id="A")
    previous = deepcopy(state.situations[item["id"]])
    with pytest.raises(ValueError):
        sit.update(state, item["id"], {"intensity": 3, "remaining_days": -1})
    assert previous == state.situations[item["id"]]


def test_save_load_continuation_and_legacy_defaults(story_state, tmp_path):
    state = story_state
    item = create(state, "confidence", duration=4)
    advance(state, 2)
    saved = state.save(tmp_path / "story.json")
    loaded = GameState.load(saved)
    assert loaded.situations == state.situations
    advance(state, 2)
    advance(loaded, 2)
    assert loaded.situations == state.situations
    assert loaded.countries["A"].stability == state.countries["A"].stability
    assert create(loaded, "commerce")["id"] != item["id"]
    legacy = GameState.load(ROOT / "examples/civil_networks/save.json")
    assert legacy.situations == {} and legacy.next_situation_number == 1


def test_pause_boundaries_and_manual_end(story_state):
    state = story_state
    item = create(state, "confidence", duration=1)
    engine = RuleEngine(state, enable_city_manager=False, enable_frontier_ai=False)
    engine.clock.pause()
    before = state.countries["A"].stability
    assert not engine.step_day()
    assert state.countries["A"].stability == before
    engine.step_day(force=True)
    assert state.situations[item["id"]]["status"] == "ended"
    after = state.countries["A"].stability
    advance(state)
    assert state.countries["A"].stability == after
    with pytest.raises(ValueError):
        sit.update(state, item["id"], {"remaining_days": 2})


def test_log_only_records_events_after_creation_and_separates_statements(story_state):
    state = story_state
    state.record("agent_decision", country_id="A", reason="事前决策")
    item = create(state)
    state.record("agent_decision", country_id="A", reason="先保粮仓")
    state.record("action_result", actor="A", accepted=False, action_type="BUILD", effects={})
    state.record("action_result", actor="A", accepted=True, action_type="SET_POLICY", effects={"policy": "AGRICULTURE"})
    state.record("construction_completed", country_id="B", project_id="foreign")
    sit.capture(state)
    history = state.situations[item["id"]]["history"]
    assert not any("事前决策" in row["text"] for row in history)
    assert len([row for row in history if row["kind"] == "action"]) == 1
    assert len([row for row in history if row["kind"] == "statement"]) == 1
    assert state.situations[item["id"]]["action_count"] == 1
    count = len(history)
    sit.capture(state)
    assert len(history) == count


def test_eliminated_participant_ends_situation_and_relation_is_bounded(story_state):
    state = story_state
    item = create(state, "friendship", partner_id="B", intensity=3)
    state.relations[relation_key("A", "B")] = 99
    advance(state)
    assert state.relations[relation_key("A", "B")] == 100
    del state.countries["B"]
    sit.begin_day(state)
    assert state.situations[item["id"]]["status"] == "ended"


def test_ai_receives_interventions_and_responds_without_taking_player_seat(story_state):
    from agents.scheduler import AgentScheduler, build_observation
    state = story_state
    create(state)
    observation = build_observation(state, "A")
    assert observation["country"]["active_situations"][0]["preset_id"] == "drought"
    scheduler = AgentScheduler()
    engine = RuleEngine(state, planner=scheduler, enable_city_manager=False, enable_frontier_ai=False)
    scheduler.plan(engine, only={"A"})
    assert state.countries["A"].policy == "AGRICULTURE"
    scheduler.set_player_country("B")
    old = deepcopy(state.countries["B"].to_dict())
    create(state, "harvest", "B")
    scheduler.plan(engine, only={"B"})
    assert state.countries["B"].to_dict() == old


def test_limit_rejects_thirteenth_without_corrupting_existing(story_state):
    state = story_state
    for index, key in enumerate(sit.PRESETS):
        target = "A" if index % 2 == 0 else "B"
        params = {"partner_id": "C"} if sit.PRESETS[key].get("bilateral") else {}
        create(state, key, target, **params)
    assert len(sit.active(state)) == 12
    before = deepcopy(state.to_dict())
    with pytest.raises(ValueError, match="12"):
        create(state, "drought", "C")
    assert state.to_dict() == before


def test_replay_includes_interventions_in_same_day_action_order(tmp_path):
    from core.simulation import Simulation
    from core.replay import replay_saved_actions
    simulation = Simulation.new(use_mock_agents=False)
    state = simulation.state
    item = create(state, "confidence", "ELAR", duration=8)
    simulation.engine.apply_action("ELAR", {"type": "SET_POLICY", "priority": "AGRICULTURE"})
    simulation.step(2)
    sit.update(state, item["id"], {"intensity": 3, "remaining_days": 6})
    simulation.step(2)
    sit.end(state, item["id"])
    create(state, "drought", "MARIS", duration=2)
    simulation.step(3)
    path = state.save(tmp_path / "replay-situations.json")
    replayed = replay_saved_actions(path)
    assert replayed.fingerprint() == state.fingerprint()
