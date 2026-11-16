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
    if saved.get("situations"):
        actions = {entry["result"]["action_id"]: entry for entry in saved["action_log"]}
        for event in saved["event_log"]:
            if event["type"] in {"situation_created", "situation_adjusted", "situation_ended", "action_result"}:
                commands.setdefault(event["day"], []).append(event)
    for day in range(final.day_index + 1):
        if saved.get("situations"):
            from core import situations
            for event in commands.get(day, []):
                kind = event["type"]
                if kind == "situation_created":
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
    return initial


replay_save = replay_saved_actions
