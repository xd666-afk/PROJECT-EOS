"""High-level run, pause, step, speed, save, and JSONL logging controls."""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from agents.scheduler import AgentScheduler
from core.clock import GameClock
from core.rules import RuleEngine
from core.state import DEFAULT_RULES, DEFAULT_WORLD, GameState


class Simulation:
    def __init__(self, state: GameState, use_mock_agents: bool = True) -> None:
        self.state = state
        self.clock = GameClock()
        self.scheduler = AgentScheduler() if use_mock_agents else None
        self.engine = RuleEngine(state, self.clock, self.scheduler)
        self._log_handle = None

    @classmethod
    def new(
        cls,
        world_path: str | Path = DEFAULT_WORLD,
        config_path: str | Path = DEFAULT_RULES,
        seed: int = 2000,
        use_mock_agents: bool = True,
    ) -> "Simulation":
        return cls(GameState.new(world_path, config_path, seed), use_mock_agents)

    @classmethod
    def load(
        cls,
        path: str | Path,
        world_path: str | Path | None = None,
        use_mock_agents: bool = True,
    ) -> "Simulation":
        return cls(GameState.load(path, world_path), use_mock_agents)

    def attach_jsonl(self, path: str | Path, append: bool = False) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = destination.open("a" if append else "w", encoding="utf-8")
        if not append:
            for event in self.state.event_log:
                self._write_event(event)
        self.state.add_listener(self._write_event)

    def _write_event(self, event: dict[str, Any]) -> None:
        if self._log_handle is not None:
            self._log_handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._log_handle.flush()

    def close(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def pause(self) -> None:
        self.clock.pause()

    def resume(self) -> None:
        self.clock.resume()

    def set_speed(self, ticks_per_second: float) -> None:
        self.clock.set_speed(ticks_per_second)

    def run(
        self,
        days: int,
        real_time: bool = False,
        force: bool = False,
        autosave_path: str | Path | None = None,
    ) -> int:
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            raise ValueError("days must be a non-negative integer")
        completed = 0
        target = self.state.day_index + days
        while self.state.day_index < target:
            started = time.perf_counter()
            if not self.engine.step_day(force=force):
                break
            completed += 1
            if autosave_path is not None and self.state.day_index % 30 == 0:
                self.state.save(autosave_path)
            if real_time:
                remaining = self.clock.seconds_per_tick - (time.perf_counter() - started)
                if remaining > 0:
                    time.sleep(remaining)
        return completed

    def step(self, days: int = 1) -> int:
        return self.run(days, real_time=False, force=True)

    def fast_forward(self, days: int) -> int:
        return self.run(days, real_time=False, force=True)
