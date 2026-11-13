"""Weighted marching costs shared by battle settlement, the AI and the map editor.

One cost model, two consumers: the engine reads the live world plus every built road,
the editor reads a draft tile table. Both go through `Movement`, so a march time shown
while painting is the number the settlement will use once that map is in play.
"""
from __future__ import annotations

import heapq
import math
from typing import Any, Callable

Coord = tuple[int, int]


def march_days(cost: float, daily_budget: float) -> int:
    """Whole days needed to pay for `cost` movement at `daily_budget` per day."""
    if cost <= 1e-9:
        return 0
    return max(1, int(math.ceil(cost / daily_budget - 1e-9)))


class Movement:
    def __init__(self, config: dict[str, Any], state_of: Callable[[Coord], dict | None],
                 neighbors_of: Callable[[Coord], list[Coord]]) -> None:
        table = config["movement"]
        self.daily_budget = float(table["daily_budget"])
        self.road_cost = float(table["road_cost"])
        # A tile another realm holds is marched on at a discount of speed: no border is a
        # wall any more, but no general pretends a hostile province marches like home. The
        # editor's draft table carries no owners, so a missing key prices a neutral world.
        self.hostile_cost = float(table.get("hostile_cost", 0.0))
        self.maximum_order_cost = float(table["maximum_order_cost"])
        self.biome_cost = {biome: float(cost) for biome, cost in table["biome_cost"].items()}
        self._state_of = state_of
        self._neighbors_of = neighbors_of

    def cost(self, coord: Coord) -> float | None:
        """Cost of entering `coord`; None means the tile cannot be marched onto.

        Terrain sets the price, a road pays it down whatever lies under it, and ground the
        marching realm does not hold adds a surcharge on top of both — so the cheapest road
        across a hostile country can still beat a friendly forest, while the same road at
        home stays cheaper still. `state_of` answers the ownership question for its own
        actor and hands over the boolean; a caller without an actor (the map editor) leaves
        the key out and marches over pure geography.
        """
        state = self._state_of(coord)
        if state is None or not state.get("land"):
            return None
        total = self.road_cost if state.get("road") else self.biome_cost[state["biome"]]
        if state.get("hostile"):
            total += self.hostile_cost
        return total

    def search(self, start: Coord, allowed: Callable[[Coord], bool] | None = None,
               targets: set[Coord] | None = None,
               cap: float | None = None) -> tuple[dict[Coord, float], dict[Coord, Coord]]:
        """Weighted distances from `start`; returns (costs, previous) for reached tiles.

        Ties break on (cost, row, col) so a march ordered from an action log replays
        onto the same route. Costs beyond `maximum_order_cost` are never expanded — unless
        a caller passes its own `cap`, which is how the settlement proves that a hex too
        dear for one order is still the same road, and not a wall.
        """
        passable = allowed or (lambda coord: True)
        ceiling = self.maximum_order_cost if cap is None else cap
        wanted = set(targets or ())
        costs = {start: 0.0}
        previous: dict[Coord, Coord] = {}
        settled: set[Coord] = set()
        queue: list[tuple[float, int, int, Coord]] = [(0.0, start[1], start[0], start)]
        while queue:
            total, _, _, current = heapq.heappop(queue)
            if current in settled:
                continue
            settled.add(current)
            if wanted and wanted <= settled:
                break
            for neighbor in self._neighbors_of(current):
                if neighbor in settled or not passable(neighbor):
                    continue
                step = self.cost(neighbor)
                if step is None:
                    continue
                candidate = total + step
                if candidate > ceiling + 1e-9:
                    continue
                if candidate < costs.get(neighbor, math.inf) - 1e-12:
                    costs[neighbor] = candidate
                    previous[neighbor] = current
                    heapq.heappush(queue, (candidate, neighbor[1], neighbor[0], neighbor))
        return costs, previous

    def route(self, previous: dict[Coord, Coord], start: Coord, target: Coord) -> list[Coord]:
        walk = [target]
        while walk[-1] != start:
            walk.append(previous[walk[-1]])
        return list(reversed(walk))

    def path(self, start: Coord, target: Coord,
             allowed: Callable[[Coord], bool] | None = None) -> list[Coord] | None:
        """Cheapest route under entry costs; None when the target is out of reach."""
        if self.cost(target) is None or (allowed is not None and not allowed(target)):
            return None
        _, previous = self.search(start, allowed, {target})
        if target not in previous and target != start:
            return None
        return self.route(previous, start, target)

    def cumulative(self, route: list[Coord]) -> list[float]:
        """Running cost at each index; index 0 is the departure tile and costs nothing."""
        totals = [0.0]
        for coord in route[1:]:
            totals.append(totals[-1] + float(self.cost(coord)))
        return totals

    def days(self, cost: float) -> int:
        return march_days(cost, self.daily_budget)

    def progress(self, cumulative: list[float], spent: float) -> int:
        """Furthest route index paid for by `spent` movement budget."""
        index = 0
        while index + 1 < len(cumulative) and cumulative[index + 1] <= spent + 1e-9:
            index += 1
        return index

    def plan(self, start: Coord, target: Coord,
             allowed: Callable[[Coord], bool] | None = None) -> dict[str, Any] | None:
        route = self.path(start, target, allowed)
        if route is None:
            return None
        totals = self.cumulative(route)
        return {
            "route": route,
            "cumulative": totals,
            "cost": round(totals[-1], 3),
            "days": self.days(totals[-1]),
        }
