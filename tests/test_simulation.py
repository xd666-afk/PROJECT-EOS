import numpy as np

from core.rules import RuleEngine
from core.simulation import Simulation
from core.society import food_capacity, zone_adjacency
from core.state import GameState, calendar_date


def test_calendar_has_no_year_zero():
    assert calendar_date(0)["label"] == "公元前2000年1月1日"
    assert calendar_date(364)["label"] == "公元前2000年12月31日"
    assert calendar_date(365)["label"] == "公元前1999年1月1日"
    assert calendar_date(1999 * 365)["label"] == "公元前1年1月1日"
    assert calendar_date(2000 * 365)["label"] == "公元1年1月1日"


def test_pause_resume_step_and_fast_forward():
    simulation = Simulation.new(use_mock_agents=False)
    assert simulation.run(5) == 5
    simulation.pause()
    assert simulation.run(10) == 0
    assert simulation.state.day_index == 5
    assert simulation.step(1) == 1
    assert simulation.state.day_index == 6
    simulation.resume()
    assert simulation.run(2) == 2
    simulation.pause()
    assert simulation.fast_forward(3) == 3
    assert simulation.state.day_index == 11


def test_speed_does_not_change_logical_result():
    slow = Simulation.new(use_mock_agents=False)
    fast = Simulation.new(use_mock_agents=False)
    slow.set_speed(1)
    fast.set_speed(1000)
    slow.run(45)
    fast.run(45)
    assert slow.state.fingerprint() == fast.state.fingerprint()


def test_save_load_preserves_midmonth_weather_and_rng(tmp_path):
    continuous = Simulation.new(use_mock_agents=False)
    continuous.run(47)
    save_path = tmp_path / "midmonth.json"
    continuous.state.save(save_path)
    restored = Simulation.load(save_path, use_mock_agents=False)
    assert restored.state.fingerprint() == continuous.state.fingerprint()
    continuous.run(35)
    restored.run(35)
    assert restored.state.fingerprint() == continuous.state.fingerprint()


def test_static_world_hash_is_checked(tmp_path):
    state = GameState.new()
    path = tmp_path / "save.json"
    state.save(path)
    regenerated = state.world.path.parents[1] / "output_regenerated" / "world_2000BCE.json"
    if regenerated.exists():
        # Semantically identical but a different byte hash must not be silently accepted.
        try:
            GameState.load(path, regenerated)
        except ValueError as exc:
            assert "SHA-256" in str(exc)
        else:
            raise AssertionError("wrong static-world bytes were accepted")


def test_daily_economy_uses_real_country_tiles_and_stays_nonnegative():
    simulation = Simulation.new(use_mock_agents=False)
    simulation.run(60)
    for country_id, country in simulation.state.countries.items():
        assert country.last_economy["food_production"] > 0
        assert country.last_economy["treasury_income"] > 0
        assert country.food >= 0
        assert country.treasury >= 0
        assert country.population > 0
        assert len(country.tiles) == len(simulation.state.world.polities[country_id]["initial_tiles"])


def test_start_year_sets_era_and_technology_baseline(tmp_path):
    state = GameState.new()
    era = state.configure_starting_era(-799)  # 800 BCE
    assert state.start_era_index == 2
    assert era["name"] == "青铜时代盛期"
    assert all(level >= 2 for level in state.countries["ELAR"].technology.values())
    assert state.date["label"].startswith("公元前800年")

    late = state.configure_starting_era(300)  # AD 300
    assert late["name"] == "帝国时代"
    assert all(level >= 5 for level in state.countries["VAYR"].technology.values())
    path = tmp_path / "late.json"
    state.save(path)
    restored = GameState.load(path)
    assert restored.start_astronomical_year == 300
    assert restored.start_era_index == 5
    assert restored.date["label"].startswith("公元300年")


def test_tech_tree_has_six_levels_per_branch(state):
    for branch in state.config["tech_tree"].values():
        assert len(branch["levels"]) == 6
    assert state.config["research_max_level"] == 6


def test_composite_scores_and_ranking_are_complete():
    simulation = Simulation.new(use_mock_agents=False)
    summary = simulation.state.summary()
    assert len(summary["ranking"]) == 4
    assert summary["leader"] == summary["ranking"][0]["country_id"]
    for entry in summary["ranking"]:
        assert entry["total"] > 0
        assert entry["victory_path"] in {"prosperity", "knowledge", "dominion", "harmony", "balanced"}
        assert set(entry["breakdown"]) == {"prosperity", "knowledge", "dominion", "harmony"}
        country = summary["countries"][entry["country_id"]]
        assert country["total"] == entry["total"]


def test_city_society_metrics_exist_from_real_world():
    simulation = Simulation.new(use_mock_agents=False)
    summary = simulation.state.summary()
    elar = summary["countries"]["ELAR"]
    assert elar["city_tier"] == "都城"
    assert elar["housing"] > 37
    assert 0 < elar["stability"] <= 100
    assert 0.72 <= elar["stability_factor"] <= 1.15
    assert summary["era"]["index"] == 1


def test_social_events_affect_real_resources(engine, monkeypatch):
    country = engine.state.countries["ELAR"]
    country.treasury = 1000
    country.stability = 70
    country.food = food_capacity(country, engine.state.config)
    population = country.population
    monkeypatch.setattr(engine.state.weather, "random", lambda: 0.0)
    engine.economy.apply_social_events()
    events = [e for e in engine.state.event_log if e["type"] == "social_event"]
    assert {e["event"] for e in events} == {
        "court_corruption", "harvest_festival", "craftsmen_migration"
    }
    assert country.treasury < 1000
    assert country.population > population


def test_city_adjacency_and_livability_are_meaningful():
    from core.society import city_livability_target, zone_adjacency

    state = GameState.new()
    country = state.countries["ELAR"]
    city = country.cities[0]
    pair = next(
        (left, right)
        for left in city.tiles for right in city.tiles
        if left != right and any(
            abs(left[0] - right[0]) + abs(left[1] - right[1]) == 1
            for _ in [0]
        )
    )
    city.zones[pair[0]] = "industry"
    city.zones[pair[1]] = "industry"
    assert zone_adjacency(city, pair[0])["mining"] > 1.0
    baseline = city_livability_target(city, country, state.config)
    for coord in city.tiles:
        city.zones[coord] = "industry"
    polluted = city_livability_target(city, country, state.config)
    assert polluted < baseline


def test_weather_changes_agriculture_factor(state):
    engine = RuleEngine(state)
    tile = state.world.tile((13, 10))
    cold_dry = engine.economy.tile_weather_factor(tile, 0.0, -5.0, 0)
    warm_wet = engine.economy.tile_weather_factor(tile, 8.0, 22.0, 0)
    assert warm_wet[2] > cold_dry[2]


def test_hazard_has_actual_food_effect(engine, monkeypatch):
    country = engine.state.countries["ELAR"]
    country.food = 100.0
    monkeypatch.setattr(engine.state.weather, "random", lambda: 0.0)
    monkeypatch.setattr(engine.state.weather, "uniform", lambda low, high: 0.5)
    monthly = {"countries": {"ELAR": {"rain_anomaly_ratio": 2.0}}}
    engine._apply_hazards(monthly)
    assert country.food < 100.0
    event = next(event for event in engine.state.event_log if event["type"] == "hazard_impact")
    assert event["food_loss"] > 0
    assert "不是年发生概率" in event["note"]


def test_victory_conditions_report_progress_and_winner(state):
    country = state.countries["ELAR"]
    status = state.victory_status()
    assert status["winner"] is None
    progress = status["countries"]["ELAR"]
    assert set(progress["conditions"]) == {
        "knowledge", "prosperity", "dominion", "harmony"
    }
    assert all(
        0.0 <= value["progress"] <= 1.0
        for value in progress["conditions"].values()
    )

    target = state.config["victory_conditions"]["knowledge"]["min_tech_level"]
    country.technology = {field: target for field in country.technology}
    status = state.victory_status()
    assert status["winner"] == "ELAR"
    assert status["condition"] == "knowledge"
    assert status["countries"]["ELAR"]["achieved"] == ["knowledge"]

    assert not state.victory_announced()
    state.record("victory", country_id="ELAR", condition="knowledge", label="知识胜利")
    assert state.victory_announced()


def test_prosperity_victory_requires_all_three_targets(state):
    country = state.countries["ELAR"]
    settings = state.config["victory_conditions"]["prosperity"]
    country.population = settings["population"]
    country.treasury = settings["treasury"]
    country.food = food_capacity(country, state.config) * settings["food_ratio"]
    assert state.victory_status()["countries"]["ELAR"]["conditions"]["prosperity"]["achieved"]
    country.treasury = settings["treasury"] * 0.5
    assert not state.victory_status()["countries"]["ELAR"]["conditions"]["prosperity"]["achieved"]


def test_city_service_targets_react_to_buildings_budget_and_pollution(state):
    from core.society import city_service_targets

    country = state.countries["ELAR"]
    city = country.cities[0]
    base = city_service_targets(city, country, state.config)
    assert 5 <= base["security"] <= 95
    assert 5 <= base["health"] <= 95

    country.buildings[city.center] = "TEMPLE"
    templed = city_service_targets(city, country, state.config)
    assert templed["security"] > base["security"]
    assert templed["health"] > base["health"]

    country.buildings[city.center] = "GRANARY"
    granaried = city_service_targets(city, country, state.config)
    assert granaried["health"] > base["health"]

    for coord in city.tiles:
        city.zones[coord] = "industry"
    polluted = city_service_targets(city, country, state.config)
    assert polluted["security"] < templed["security"]
    assert polluted["health"] < granaried["health"]

    city.budget = "investment"
    invested = city_service_targets(city, country, state.config)
    assert invested["security"] > polluted["security"]
    city.budget = "austerity"
    austere = city_service_targets(city, country, state.config)
    assert austere["security"] < invested["security"]


def test_low_security_reduces_tax_and_services_converge_monthly(engine):
    country = engine.state.countries["ELAR"]
    city = country.cities[0]
    weather = {"rain": np.full((54, 72), 3.0), "temperature": np.full((54, 72), 18.0)}
    city.security = 10.0
    low_tax = engine.economy.settle_country(country, weather)["tax_income"]
    city.security = 90.0
    high_tax = engine.economy.settle_country(country, weather)["tax_income"]
    assert high_tax > low_tax

    city.security = 90.0
    city.health = 90.0
    for coord in city.tiles:
        city.zones[coord] = "industry"
    engine.economy.update_city_services_monthly()
    assert city.security < 90.0
    assert city.health < 90.0


def test_city_unrest_and_epidemic_apply_real_losses(engine, monkeypatch):
    country = engine.state.countries["ELAR"]
    city = country.cities[0]
    city.population = 10_000
    country.population = 10_000
    city.security = 5.0
    city.health = 5.0
    country.treasury = 100.0
    country.stability = 50.0
    country.food = 0.0
    monkeypatch.setattr(engine.state.weather, "random", lambda: 0.0)
    engine.economy.apply_social_events()
    types = {event["type"] for event in engine.state.event_log}
    assert "city_unrest" in types
    assert "city_epidemic" in types
    assert country.treasury < 100.0
    assert country.stability < 50.0
    assert city.population < 10_000
    assert sum(item.population for item in country.cities) == country.population


def test_three_tech_lines_use_technology_politics_economy(state):
    tree = state.config["tech_tree"]
    assert tree["bronze_metallurgy"]["label"] == "科技"
    assert tree["writing"]["label"] == "政治"
    assert tree["agriculture"]["label"] == "经济"
    assert tree["bronze_metallurgy"]["levels"][1]["name"] == "青铜冶炼"
    assert "哲学" in tree["writing"]["levels"][1]["name"]
    assert state.config["research_fields"] == [
        "bronze_metallurgy", "writing", "agriculture"
    ]
    assert state.config["politics_stability_per_level"] > 0
    assert state.config["economy_tax_bonus_per_level"] > 0


def test_old_save_gets_current_tech_content(tmp_path, state):
    state.config["tech_tree"]["bronze_metallurgy"]["label"] = "旧科技"
    path = tmp_path / "old_rules.json"
    state.save(path)
    restored = GameState.load(path)
    assert restored.config["tech_tree"]["bronze_metallurgy"]["label"] == "科技"
    assert restored.config["tech_tree"]["writing"]["label"] == "政治"


def test_commerce_zone_gets_center_adjacency_bonus():
    state = GameState.new(seed=2000)
    city = state.countries["ELAR"].cities[0]
    neighbor = next(state.world.neighbors(*city.center))
    city.zones[neighbor] = "commerce"
    bonus = zone_adjacency(city, neighbor, state.world)
    assert bonus["tax"] > 1.0
