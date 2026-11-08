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
    engine = RuleEngine(initial, enable_city_manager=False)
    by_day: dict[int, list[tuple[str, dict]]] = {}
    for entry in saved["action_log"]:
        by_day.setdefault(entry["result"]["applied_day"], []).append(
            (entry["result"]["actor"], entry["action"])
        )
    for day in range(final.day_index + 1):
        for actor, action in by_day.get(day, []):
            engine.apply_action(actor, action)
        if day < final.day_index:
            engine.step_day(force=True)
    return initial


replay_save = replay_saved_actions
