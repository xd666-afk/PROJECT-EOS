"""Real-time pacing is separate from fixed, one-day logical ticks."""
from __future__ import annotations


class GameClock:
    def __init__(self, ticks_per_second: float = 1.0) -> None:
        self.paused = False
        self.ticks_per_second = 1.0
        self.set_speed(ticks_per_second)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def set_speed(self, ticks_per_second: float) -> None:
        if isinstance(ticks_per_second, bool) or not isinstance(ticks_per_second, (int, float)):
            raise ValueError("speed must be a positive finite number")
        if not 0 < float(ticks_per_second) <= 10000:
            raise ValueError("speed must be in (0, 10000]")
        self.ticks_per_second = float(ticks_per_second)

    @property
    def seconds_per_tick(self) -> float:
        return 1.0 / self.ticks_per_second
