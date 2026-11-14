"""占领贡金：夺下敌国有建筑的格子，此后按缴付方的收入抽一小笔。

玩家要的是「攻占对方的建筑应换到对方财政的一小份收入」，所以结算给的是一份小额年金而不是一次性掠夺：
每夺一栋建筑，按 `capture_tribute_share` 抽取**缴付方自己**的当日总收入（税+矿），持续
`capture_tribute_days` 天，同一对手合计封顶 `capture_tribute_cap`。面板、AI、日结算都读
`core.state.tribute_transfers` 这一份账，所以印在格子上的比例就是当天真的划走的钱。
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from agents.heuristic import HeuristicAgent
from agents.personality import PERSONALITIES, personality_definition
from agents.scheduler import build_observation
from core.content import ContentError, validate_content
from core.messages import _messages_for_event
from core.military import Military
from core.rules import RuleEngine
from core.state import GameState, tribute_base, tribute_transfers

ROOT = Path(__file__).resolve().parents[1]
ACTOR, RIVAL = "ELAR", "MARIS"


def engine_of(seed=2000):
    """A bare settlement: no planners, so nothing but these actions touches the state."""
    return RuleEngine(
        GameState.new(seed=seed), planner=None,
        enable_city_manager=False, enable_frontier_ai=False,
    )


def last_event(state, kind):
    return next(event for event in reversed(state.event_log) if event["type"] == kind)


def staged(engine, building=None):
    """Put `building` on a rival tile and stand one army right beside it.

    The attacker has to be in the ring already: an immediate battle keeps the levy, the
    capture and the ledger inside one call, so nothing about the march schedule can blur
    what these tests are reading.
    """
    state = engine.state
    attacker, defender = state.countries[ACTOR], state.countries[RIVAL]
    attacker.armies = []
    attacker.army_serial = 0
    defender.armies = []
    defender.army_serial = 0
    centers = {city.center for city in defender.cities}
    tile = next(coord for coord in defender.tiles if coord not in centers)
    staging = next(
        coord for coord in state.world.neighbors(*tile)
        if coord not in defender.tiles and state.world.tile(coord)["land"]
    )
    if building is not None:
        defender.buildings[tile] = building
    army = attacker.new_army(tile=staging, units={"MILITIA": 8})
    engine.apply_action(ACTOR, {
        "type": "DIPLOMACY", "operation": "DECLARE_WAR", "target": RIVAL,
    })
    engine.step_day()
    return attacker, defender, army, tile


def seize(engine, building="FARM"):
    """Take that tile through the player's own action, and hand back what the ledger says."""
    attacker, defender, army, tile = staged(engine, building)
    result = engine.apply_action(ACTOR, {
        "type": "MILITARY", "operation": "ATTACK", "target": RIVAL, "army_id": army.army_id,
        "tile": {"col": tile[0], "row": tile[1]},
    })
    assert result.accepted, result.reason_text
    assert result.effects["captured"], "the fixture lost its own battle"
    return attacker, defender, tile, result.effects["tribute"]


def shares(engine, payer):
    """The one line the settlement, the panel and the AI all read."""
    return tribute_transfers(payer, engine.state.countries, engine.state.config)


# --- the ledger is written where the tile changes hands ---------------------------------

def test_a_captured_building_levies_an_annuity_on_the_loser():
    engine = engine_of()
    military = engine.state.config["military"]
    _attacker, defender, tile, tribute = seize(engine)
    base = tribute_base(defender)
    assert base > 0.0, "the payer had no settled income to be measured against"
    assert tribute == {
        "from": RIVAL, "to": ACTOR, "building": "FARM",
        "label": engine.state.config["buildings"]["FARM"]["label"],
        "share": pytest.approx(military["capture_tribute_share"]),
        "days": military["capture_tribute_days"],
        "daily": pytest.approx(round(base * military["capture_tribute_share"], 4)),
    }
    assert defender.levies == [{
        "to": ACTOR, "building": "FARM",
        "share": military["capture_tribute_share"],
        "days_left": military["capture_tribute_days"],
    }]
    assert tile in engine.state.countries[ACTOR].tiles, "the tile did not change hands"


def test_an_empty_tile_changes_hands_and_levies_nothing():
    engine = engine_of()
    _attacker, defender, _tile, tribute = seize(engine, building=None)
    assert tribute is None
    assert defender.levies == []


def test_a_captured_road_earns_nothing_because_pavement_was_never_exclusive():
    """The exempt list is settlement data, so a road is free to hold and free to take."""
    engine = engine_of()
    assert "ROAD" in engine.state.config["military"]["capture_tribute_exempt"]
    _attacker, defender, _tile, tribute = seize(engine, building="ROAD")
    assert tribute is None and defender.levies == []


def test_the_same_building_is_only_ever_levied_once_per_capture():
    """A rival that takes the tile back and loses it again owes again: the count is the loot."""
    engine = engine_of()
    attacker, defender, tile, _tribute = seize(engine)
    attacker.levies.append({"to": RIVAL, "building": "MINE", "share": 0.02, "days_left": 30})
    assert shares(engine, defender)[0]["buildings"] == ["FARM"]
    assert shares(engine, attacker)[0]["buildings"] == ["MINE"]


# --- the daily transfer is the share the table promised ---------------------------------

def test_the_daily_cut_moves_exactly_the_promised_share_and_nothing_more():
    engine = engine_of()
    attacker, defender, _tile, tribute = seize(engine)
    before = (attacker.treasury, defender.treasury)
    engine.military.tribute_daily()
    gained = round(attacker.treasury - before[0], 6)
    lost = round(before[1] - defender.treasury, 6)
    assert lost == pytest.approx(tribute["daily"], abs=1e-4)
    assert gained == pytest.approx(lost, abs=1e-9), "tribute was printed out of thin air"
    assert shares(engine, defender)[0]["days_left"] == tribute["days"] - 1


def test_the_step_clock_collects_tribute_every_day_it_is_owed():
    """`step_day` is the only scheduler: if the hook is missing, nothing below moves."""
    engine = engine_of()
    attacker, defender, _tile, tribute = seize(engine)
    engine.step_day()
    assert defender.levies[0]["days_left"] == tribute["days"] - 1
    assert tribute_base(defender) > 0.0
    assert any(
        event["type"] == "economy_daily" and event["country_id"] == ACTOR
        for event in engine.state.event_log[-12:]
    ), "the day never settled"


def test_an_unpaid_balance_is_borrowed_from_nothing():
    engine = engine_of()
    attacker, defender, _tile, _tribute = seize(engine)
    attacker.treasury = 0.0
    defender.treasury = 0.0
    engine.military.tribute_daily()
    assert attacker.treasury == 0.0 and defender.treasury == 0.0
    assert defender.levies, "an empty treasury cancelled the debt instead of deferring it"


def test_shares_stack_per_building_and_stop_at_the_cap():
    engine = engine_of()
    military = engine.state.config["military"]
    attacker, defender, _tile, _tribute = seize(engine)
    for index in range(6):
        defender.levies.append({
            "to": ACTOR, "building": "MINE", "share": military["capture_tribute_share"],
            "days_left": military["capture_tribute_days"] - index,
        })
    line = shares(engine, defender)[0]
    stacked = 7 * military["capture_tribute_share"]
    assert line["share"] == pytest.approx(min(stacked, military["capture_tribute_cap"]))
    assert line["capped"] == pytest.approx(
        max(0.0, stacked - military["capture_tribute_cap"]))
    assert line["days_left"] == military["capture_tribute_days"], "the longest bill sets the clock"
    assert line["daily"] == pytest.approx(
        round(tribute_base(defender) * line["share"], 4))
    assert line["buildings"].count("FARM") == 1


def test_a_levy_expires_and_never_bills_again():
    engine = engine_of()
    military = engine.state.config["military"]
    attacker, defender, _tile, _tribute = seize(engine)
    defender.levies[0]["days_left"] = 2
    before = attacker.treasury
    engine.military.tribute_daily()
    engine.military.tribute_daily()
    assert defender.levies == []
    balance = attacker.treasury
    engine.military.tribute_daily()
    assert attacker.treasury == balance, "an expired levy kept collecting"
    assert balance > before


def test_the_ledger_survives_the_save_round_trip(tmp_path):
    engine = engine_of()
    _attacker, defender, _tile, tribute = seize(engine)
    engine.military.tribute_daily()
    path = tmp_path / "tribute_save.json"
    engine.state.save(path)
    restored = GameState.load(path)
    assert restored.countries[RIVAL].levies == defender.levies
    assert restored.countries[RIVAL].levies[0]["days_left"] == tribute["days"] - 1
    assert shares(engine, restored.countries[RIVAL])[0]["daily"] == pytest.approx(
        tribute["daily"], abs=1e-4)


# --- the panel and the AI read the same numbers as the transfer -------------------------

def test_the_tile_price_and_the_battle_agree_on_the_annuity():
    engine = engine_of()
    military = engine.state.config["military"]
    attacker, defender, army, tile = staged(engine, "MARKET")
    quote = Military(engine.state).tile_strikes(ACTOR, tile)["tribute"]
    base = tribute_base(defender)
    assert base > 0.0, "the payer had no settled income to be measured against"
    assert quote == {
        "label": engine.state.config["buildings"]["MARKET"]["label"],
        "share": pytest.approx(military["capture_tribute_share"]),
        "days": military["capture_tribute_days"],
        "daily": pytest.approx(round(base * military["capture_tribute_share"], 4)),
        "cap": military["capture_tribute_cap"],
        "owed": 0.0,
    }
    result = engine.apply_action(ACTOR, {
        "type": "MILITARY", "operation": "ATTACK", "target": RIVAL, "army_id": army.army_id,
        "tile": {"col": tile[0], "row": tile[1]},
    })
    assert result.accepted and result.effects["captured"], "the fixture lost its own battle"
    assert result.effects["tribute"]["daily"] == pytest.approx(quote["daily"], abs=1e-9)
    assert defender.levies[0]["share"] == pytest.approx(quote["share"])
    assert defender.levies[0]["days_left"] == quote["days"]
    assert tile in attacker.tiles, "the tile did not change hands"
    again = Military(engine.state).tile_strikes(ACTOR, tile)
    assert again["building"] is None and again["tribute"] is None


def test_the_battle_tells_both_courts_what_was_levied():
    engine = engine_of()
    _attacker, defender, _tile, tribute = seize(engine)
    event = last_event(engine.state, "battle")
    assert event["tribute"] == tribute
    text = {
        message["country_id"]: message["text"]
        for message in _messages_for_event(engine.state, event)
    }
    label = tribute["label"]
    assert label in text[ACTOR] and f"{tribute['share'] * 100:.0f}%" in text[ACTOR]
    assert label in text[RIVAL] and f"{tribute['days']} 天" in text[RIVAL]


def test_the_observation_hands_the_agent_the_same_ledger_the_panel_prints():
    engine = engine_of()
    seize(engine)
    observation = build_observation(engine.state, RIVAL)
    tribute = observation["country"]["tribute"]
    assert set(tribute) >= {"paid", "collected", "daily_paid", "daily_collected", "base_income"}
    assert tribute["paid"][0]["to"] == ACTOR
    assert tribute["daily_paid"] == pytest.approx(tribute_base(engine.state.countries[RIVAL])
                                                 * tribute["paid"][0]["share"], abs=1e-4)
    for key in ("capture_tribute_share", "capture_tribute_days",
                "capture_tribute_cap", "capture_tribute_resolve", "capture_tribute_exempt"):
        assert key in observation["rules"]["military"], key


def test_the_ai_sues_for_peace_sooner_while_it_pays_and_fights_on_while_it_collects():
    rules = engine_of().state.config
    gate = HeuristicAgent._peace_gate
    profile = PERSONALITIES["neutral"]["mock"]
    base = profile["peace_exhaustion"]
    weight = rules["military"]["capture_tribute_resolve"]
    empty = {"base_income": 10.0, "daily_paid": 0.0, "daily_collected": 0.0}
    assert gate(profile, {"tribute": {}}, rules) == base
    assert gate(profile, {"tribute": empty}, rules) == pytest.approx(base)
    paying = {"base_income": 10.0, "daily_paid": 0.2, "daily_collected": 0.0}
    collecting = {"base_income": 10.0, "daily_paid": 0.0, "daily_collected": 0.2}
    assert gate(profile, {"tribute": paying}, rules) == pytest.approx(base - 0.02 * weight)
    assert gate(profile, {"tribute": collecting}, rules) == pytest.approx(base + 0.02 * weight)


def test_a_tribute_burden_is_what_makes_the_payer_ask_for_peace():
    """Same war weariness, two ledgers: only the realm paying a cut gives up on the war."""
    engine = engine_of()
    _attacker, defender, _tile, _tribute = seize(engine)
    rules = engine.state.config
    profile = personality_definition(defender.personality)["mock"]
    ledger = build_observation(engine.state, RIVAL)["country"]["tribute"]
    assert ledger["base_income"] > 0.0 and ledger["daily_paid"] > 0.0
    assert ledger["daily_collected"] == 0.0, "this fixture should only ever pay"
    ratio = ledger["daily_paid"] / ledger["base_income"]
    weight = rules["military"]["capture_tribute_resolve"]
    # Weariness parked between the two gates: clean books keep fighting, a levy sues for peace.
    exhausted = profile["peace_exhaustion"] - ratio * weight / 2.0
    paying_gate = profile["peace_exhaustion"] - ratio * weight
    assert paying_gate < exhausted < profile["peace_exhaustion"], "the two gates never split"
    assert ACTOR in defender.at_war_with, "nobody to sue for peace with"

    def proposes(daily_paid: float) -> bool:
        observation = build_observation(engine.state, RIVAL)
        observation["country"]["war_exhaustion"] = exhausted
        observation["country"]["tribute"]["daily_paid"] = daily_paid
        actions = asyncio.run(HeuristicAgent(RIVAL).decide(observation))["actions"]
        return any(action.get("operation") == "PROPOSE_PEACE" for action in actions)

    assert not proposes(0.0)
    assert proposes(ledger["daily_paid"])


# --- the content table is the only place these numbers live -----------------------------

def test_the_content_gate_refuses_a_tribute_that_is_not_a_small_share():
    config = engine_of().state.config
    for key in ("capture_tribute_share", "capture_tribute_cap",
                "capture_tribute_days", "capture_tribute_resolve"):
        missing = deepcopy(config)
        del missing["military"][key]
        with pytest.raises(ContentError):
            validate_content(missing)
    for key, value in (
        ("capture_tribute_share", 0.0),
        ("capture_tribute_share", 0.3),
        ("capture_tribute_cap", 0.3),
        ("capture_tribute_cap", 0.01),
        ("capture_tribute_days", 0),
        ("capture_tribute_resolve", -1.0),
    ):
        weak = deepcopy(config)
        weak["military"][key] = value
        with pytest.raises(ContentError):
            validate_content(weak)
    unknown = deepcopy(config)
    unknown["military"]["capture_tribute_exempt"] = ["GATE"]
    with pytest.raises(ContentError):
        validate_content(unknown)


def test_the_command_console_and_the_panel_read_the_engine_ledger():
    server = (ROOT / "live_server.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    for contract in ("def tile_strikes", "military.tile_strikes"):
        assert contract in server, contract
    for contract in (
        "function tributeLedger", "function tributeNetNote", "function tileTributeNote",
        "占领贡金", "攻占此格可得贡金", "收取自", "缴给",
        "capture_tribute_cap", "capture_tribute_share", "capture_tribute_days",
        "capture_tribute_resolve", "capture_tribute_exempt",
    ):
        assert contract in dashboard, contract
    for source in ("core/military.py", "core/state.py"):
        module = (ROOT / source).read_text(encoding="utf-8")
        assert "capture_tribute" in module, source
