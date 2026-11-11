"""Minimal strategic armies: recruitment, movement, border battles, upkeep, exhaustion."""
from __future__ import annotations

from collections import deque
from typing import Any

from core.actions import ActionRejected
from core.society import stability_factor
from core.state import GameState
from worldgen import hex_distance, neighbors


class Military:
    def __init__(self, state: GameState) -> None:
        self.state = state
        self.config = state.config["military"]

    def _owner_of(self, coord: tuple[int, int]) -> str | None:
        return next(
            (country.country_id for country in self.state.countries.values()
             if coord in country.tiles),
            None,
        )

    def recruit(self, actor: str, amount: int) -> dict:
        if not 1 <= amount <= 4:
            raise ActionRejected("INVALID_STRENGTH", "单次招募规模为 1–4")
        country = self.state.countries[actor]
        if country.army_strength + amount > self.config["maximum_strength"]:
            raise ActionRejected("ARMY_LIMIT", "军队规模达到上限")
        treasury_cost = amount * self.config["recruit_cost_treasury"]
        food_cost = amount * self.config["recruit_food_cost"]
        if country.treasury + 1e-9 < treasury_cost:
            raise ActionRejected("INSUFFICIENT_TREASURY", "财政不足以招募")
        if country.food + 1e-9 < food_cost:
            raise ActionRejected("INSUFFICIENT_FOOD", "粮食不足以供养新兵")
        country.treasury -= treasury_cost
        country.food -= food_cost
        country.army_strength += amount
        if country.army_position is None:
            capital = self.state.world.polities[actor]["capital"]
            country.army_position = (capital["col"], capital["row"])
        self.state.record(
            "army_recruited", country_id=actor, amount=amount,
            strength=country.army_strength, treasury_cost=treasury_cost,
        )
        return {"strength": country.army_strength, "cost": treasury_cost}

    def _march_path(self, actor: str, target: tuple[int, int]) -> list[tuple[int, int]]:
        country = self.state.countries[actor]
        start = country.army_position
        if start is None or country.army_strength <= 0:
            raise ActionRejected("NO_ARMY", "没有可移动的军队")
        if not self.state.world.tile(target)["land"]:
            raise ActionRejected("INVALID_TERRAIN", "军队不能进入海域")
        limit = self.config["march_range"]
        if hex_distance(start, target) > limit:
            raise ActionRejected("MARCH_TOO_FAR", f"单次行军最多 {limit} 格")
        queue = deque([start])
        previous = {start: None}
        while queue:
            current = queue.popleft()
            if current == target:
                break
            for neighbor in self.state.world.neighbors(*current):
                if neighbor in previous or not self.state.world.tile(neighbor)["land"]:
                    continue
                owner = self._owner_of(neighbor)
                if owner is not None and owner != actor:
                    continue
                previous[neighbor] = current
                queue.append(neighbor)
        if target not in previous:
            raise ActionRejected("NO_PATH", "没有可通行的己方或中立陆地路线")
        path = []
        current = target
        while current is not None:
            path.append(current)
            current = previous[current]
        return list(reversed(path))

    def march(self, actor: str, target: tuple[int, int]) -> dict:
        country = self.state.countries[actor]
        path = self._march_path(actor, target)
        country.army_position = target
        self.state.record(
            "army_marched", country_id=actor,
            tile={"col": target[0], "row": target[1]}, distance=len(path) - 1,
        )
        return {"position": {"col": target[0], "row": target[1]}, "distance": len(path) - 1}

    def attack(self, actor: str, target_id: str) -> dict:
        attacker = self.state.countries[actor]
        if target_id not in self.state.countries or target_id == actor:
            raise ActionRejected("UNKNOWN_COUNTRY", "目标国家无效")
        if target_id not in attacker.at_war_with:
            raise ActionRejected("NOT_AT_WAR", "必须先宣战")
        if attacker.army_strength <= 0 or attacker.army_position is None:
            raise ActionRejected("NO_ARMY", "没有可作战的军队")
        defender = self.state.countries[target_id]
        city_centers = {city.center for city in defender.cities}
        border = [
            coord for coord in defender.tiles
            if hex_distance(attacker.army_position, coord) == 1
            and coord not in city_centers
        ]
        expedition = False
        if border:
            target_tile = sorted(border, key=lambda coord: (coord[1], coord[0]))[0]
        else:
            # Gameplay-first expedition rule: armies can strike a land-connected
            # hostile realm without first painting a continuous border. It is slower
            # to add a full operational movement layer, so the attack receives a penalty.
            target_tile = self._nearest_connected_enemy_tile(
                attacker.army_position, defender, city_centers
            )
            if target_tile is None:
                raise ActionRejected("NO_PATH", "军队与目标国家之间没有可用的陆上远征路线")
            expedition = True
        attack_power = (
            attacker.army_strength
            * (1 + attacker.technology.get("bronze_metallurgy", 1) * 0.04)
            * stability_factor(attacker.stability, self.state.config)
            * self.state.weather.uniform(0.85, 1.15)
            * (0.78 if expedition else 1.0)
        )
        defense_power = (
            defender.army_strength
            * (1 + defender.technology.get("bronze_metallurgy", 1) * 0.04)
            * stability_factor(defender.stability, self.state.config)
            + 1.5
        )
        attacker_loss = max(
            1, int(attacker.army_strength * self.config["attacker_loss_rate"])
        )
        defender_loss = max(
            1, int(defender.army_strength * self.config["defender_loss_rate"]))
        attacker.army_strength = max(0, attacker.army_strength - attacker_loss)
        defender.army_strength = max(0, defender.army_strength - defender_loss)
        captured = False
        if attack_power > defense_power:
            defender.tiles.remove(target_tile)
            attacker.tiles.append(target_tile)
            if target_tile in defender.outposts:
                defender.outposts.remove(target_tile)
            if target_tile in defender.buildings:
                defender.buildings.pop(target_tile, None)
            defender.projects = [
                project for project in defender.projects if tuple(project["tile"]) != target_tile
            ]
            loser_city = next(
                (city for city in defender.cities if target_tile in city.tiles), None
            )
            if loser_city is not None:
                loser_city.tiles.remove(target_tile)
                loser_city.zones.pop(target_tile, None)
            new_city = min(
                attacker.cities,
                key=lambda city: hex_distance(city.center, target_tile),
            )
            if target_tile not in new_city.tiles:
                new_city.tiles.append(target_tile)
                new_city.zones[target_tile] = "unzoned"
            defender.stability = max(0, defender.stability - self.config["capture_stability_loss"])
            captured = True
        attacker.war_exhaustion += 1.0
        defender.war_exhaustion += 1.0
        self.state.record(
            "battle", attacker=actor, defender=target_id,
            attacker_power=round(attack_power, 3), defender_power=round(defense_power, 3),
            attacker_loss=attacker_loss, defender_loss=defender_loss,
            captured=captured, expedition=expedition,
            tile={"col": target_tile[0], "row": target_tile[1]},
        )
        return {
            "battle": True, "captured": captured,
            "attacker_loss": attacker_loss, "defender_loss": defender_loss,
            "tile": {"col": target_tile[0], "row": target_tile[1]},
        }

    def _nearest_connected_enemy_tile(
        self, start: tuple[int, int], defender, city_centers: set[tuple[int, int]]
    ) -> tuple[int, int] | None:
        hostiles = [coord for coord in defender.tiles if coord not in city_centers]
        if not hostiles:
            return None
        queue = deque([start])
        visited = {start}
        while queue and len(visited) < 700:
            current = queue.popleft()
            nearby = [coord for coord in hostiles if hex_distance(current, coord) == 1]
            if nearby:
                return min(nearby, key=lambda coord: hex_distance(start, coord))
            for neighbor in self.state.world.neighbors(*current):
                if neighbor in visited or not self.state.world.tile(neighbor)["land"]:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
        return None

    def upkeep_daily(self) -> None:
        for country in self.state.countries.values():
            strength = country.army_strength
            if strength <= 0:
                continue
            cost = strength * self.config["upkeep_per_strength_per_day"]
            paid = min(country.treasury, cost)
            country.treasury -= paid
            if paid + 1e-9 < cost:
                country.army_strength = max(0, country.army_strength - 1)
                self.state.record(
                    "army_desertion", country_id=country.country_id,
                    strength=country.army_strength,
                )

    def update_monthly(self) -> None:
        for country in self.state.countries.values():
            if country.at_war_with:
                country.war_exhaustion += self.config["war_exhaustion_per_month"]
                country.stability = max(
                    0.0, country.stability
                    - self.config["war_stability_penalty_per_exhaustion"],
                )
            else:
                country.war_exhaustion = max(0.0, country.war_exhaustion - 0.4)