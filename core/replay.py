"""Replay submitted actions against the same static world, rules, and random seed."""
from __future__ import annotations

import json
from pathlib import Path

from core.rules import RuleEngine
from core.state import GameState


def replay_saved_actions(path: str | Path) -> GameState:
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    final = GameState.load(path)
    initial = GameState.new(final.world.path, final.config, final.seed)
    if -799 <= final.start_astronomical_year <= 500:
        initial.configure_starting_era(final.start_astronomical_year)
    engine = RuleEngine(
        initial, enable_city_manager=False, enable_frontier_ai=False
    )
    by_day: dict[int, list[tuple[str, dict]]] = {}
    for entry in saved["action_log"]:
        by_day.setdefault(entry["result"]["applied_day"], []).append(
            (entry["result"]["actor"], entry["action"])
        )
    # Audience commands share ordering with ordinary action receipts on the same day.
    commands = {}
    monthly_game=saved.get('time_unit')=='month'
    command_mode=bool(saved.get('situations')) or monthly_game or any(e['type']=='water_placements_repaired' for e in final.event_log)
    period=None
    if command_mode:
        actions = {entry["result"]["action_id"]: entry for entry in saved["action_log"]}
        for event in final.event_log:
            if event["type"] in {"situation_created", "situation_adjusted", "situation_ended", "action_result",'monthly_time_migrated','monthly_period_started','monthly_settlement','water_placements_repaired'}:
                commands.setdefault(event["day"], []).append(event)
    for day in range(final.day_index + 1):
        if command_mode:
            from core import situations
            from core import monthly
            for event in commands.get(day, []):
                kind = event["type"]
                if kind=='water_placements_repaired':
                    from copy import deepcopy
                    from core.state import CountryState
                    if 'countries_after' in event:
                        initial.countries={cid:CountryState.from_dict(value,initial.config) for cid,value in event['countries_after'].items()}
                        initial.monthly_ledger=deepcopy(event.get('monthly_ledger',{}))
                elif kind=='monthly_time_migrated':
                    # Pre-tree saves can retain inert legacy points which today's kernel
                    # no longer writes. Preserve those compatibility fields at migration.
                    from copy import deepcopy
                    for cid,progress in event.get('legacy_research_progress',{}).items():
                        if cid in initial.countries:initial.countries[cid].research_progress=deepcopy(progress)
                    monthly.enable(initial)
                elif kind=='monthly_period_started':
                    period=monthly.begin_period(initial);engine._monthly_batch=True;engine._monthly_first=False
                elif kind=='monthly_settlement':
                    if period is not None:monthly.finish_period(initial,period)
                    period=None;engine._monthly_batch=False
                elif kind == "situation_created":
                    situations.create(initial, event["event"])
                elif kind == "situation_adjusted":
                    situations.update(initial, event["situation_id"], event["changes"])
                elif kind == "situation_ended" and event.get("reason") == "观众提前结束":
                    situations.end(initial, event["situation_id"])
                elif kind == "action_result":
                    entry = actions[event["action_id"]]
                    engine.apply_action(entry["result"]["actor"], entry["action"])
        else:
            for actor, action in by_day.get(day, []):
                engine.apply_action(actor, action)
        if day < final.day_index:
            engine.step_day(force=True)
            if period is not None:monthly.collect(initial,period)
    return initial


replay_save = replay_saved_actions
