"""Ninety-day synchronous planning boundary with isolated per-country observations."""
from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from typing import Any

from worldgen import hex_distance, neighbors

from agents.heuristic import HeuristicAgent
from core.actions import PUBLIC_ACTIONS
from core.construction import Construction
from core.society import (
    city_static_metrics,
    city_tier,
    food_capacity,
    housing_capacity,
    specialization,
)
from core.state import relation_key


def _campaign_options(state, country) -> dict[str, dict[str, Any]]:
    if country.army_position is None or country.army_strength <= 0:
        return {}
    owner_by_coord = {
        coord: entity.country_id
        for entity in state.countries.values() for coord in entity.tiles
    }
    start = country.army_position
    distance = {start: 0}
    parent = {start: None}
    queue = deque([start])
    staging = {}
    while queue and len(distance) < 700:
        current = queue.popleft()
        for neighbor in neighbors(*current):
            tile = state.world.tile(neighbor)
            if not tile["land"] or neighbor in distance:
                continue
            owner = owner_by_coord.get(neighbor)
            if owner is None or owner == country.country_id:
                distance[neighbor] = distance[current] + 1
                parent[neighbor] = current
                queue.append(neighbor)
    for target_id, target in state.countries.items():
        if target_id == country.country_id:
            continue
        adjacent_to_army = any(
            hex_distance((start[0], start[1]), coord) == 1 for coord in target.tiles
        )
        best = None
        for coord in target.tiles:
            for candidate in neighbors(*coord):
                if candidate in distance and (best is None or distance[candidate] < best[0]):
                    best = (distance[candidate], candidate)
        reachable = adjacent_to_army or best is not None
        next_step = None
        if best is not None and not adjacent_to_army and best[0] > 0:
            path = []
            current = best[1]
            while current is not None:
                path.append(current)
                current = parent[current]
            path.reverse()
            next_step = path[min(len(path) - 1, min(4, len(path) - 1))]
        staging[target_id] = {
            "can_attack": adjacent_to_army,
            "reachable": reachable,
            "march_target": (
                {"col": next_step[0], "row": next_step[1]} if next_step else None
            ),
        }
    return staging


def build_observation(state, country_id: str) -> dict[str, Any]:
    country = state.countries[country_id]
    incoming = [
        trade for trade in state.trades.values()
        if trade["target"] == country_id and trade["status"] == "PENDING"
    ]
    outgoing = [
        trade for trade in state.trades.values()
        if trade["sender"] == country_id and trade["status"] == "PENDING"
    ]
    feedback = [
        entry["result"] for entry in state.action_log
        if entry["result"]["actor"] == country_id
    ][-8:]
    recent_events = [
        event for event in state.event_log
        if event.get("country_id") == country_id
        and event["type"] not in {"economy_daily", "action_result"}
    ][-10:]
    tiles = []
    for coord in country.tiles:
        tile = state.world.tile(coord)
        project = Construction.project_for_tile(country, coord)
        tiles.append({
            "col": coord[0], "row": coord[1], "biome": tile["biome"],
            "elevation_m": tile["elevation_m"], "river": tile["river"],
            "annual_precip_mm": tile["annual_precip_mm"],
            "building": country.buildings.get(coord),
            "project": None if project is None else {
                "building": project["building"],
                "remaining_days": round(project["remaining_days"], 3),
            },
        })
    owned = {coord for other in state.countries.values() for coord in other.tiles}
    frontier = []
    frontier_seen = set()
    from worldgen import neighbors
    for coord in country.tiles:
        for neighbor in neighbors(coord[0], coord[1]):
            if neighbor in owned or neighbor in frontier_seen:
                continue
            frontier_seen.add(neighbor)
            tile = state.world.tile(neighbor)
            if tile["land"]:
                frontier.append({
                    "col": neighbor[0], "row": neighbor[1],
                    "biome": tile["biome"], "river": tile["river"],
                })
    frontier = frontier[:8]
    housing = housing_capacity(country, state.config)
    food_room = food_capacity(country, state.config)
    tier = city_tier(country.population)
    specialty = specialization(country)
    return {
        "country_id": country_id,
        "world_day": state.day_index,
        "date": state.date,
        "country": {
            "population": country.population,
            "food": country.food,
            "treasury": country.treasury,
            "tax_rate": country.tax_rate,
            "workers": country.workers,
            "research_field": country.research_field,
            "research_progress": country.research_progress,
            "technology": country.technology,
            "policy": country.policy,
            "buildings": {f"{c[0]},{c[1]}": b for c, b in country.buildings.items()},
            "projects": Construction.describe(country),
            "contacts": country.contacts,
            "last_economy": country.last_economy,
            "shortage_days_total": country.shortage_days_total,
            "stability": round(country.stability, 2),
            "housing": housing,
            "food_capacity": food_room,
            "city_tier": tier,
            "specialization": specialty,
            "outposts": len(country.outposts),
            "army_strength": country.army_strength,
            "army_position": list(country.army_position) if country.army_position else None,
            "at_war_with": list(country.at_war_with),
            "war_exhaustion": round(country.war_exhaustion, 2),
            "cities": [
                city_static_metrics(city, country, state.world, state.config)
                for city in country.cities
            ],
        },
        "foreign_military": {
            other_id: other.army_strength
            for other_id, other in state.countries.items() if other_id != country_id
        },
        "campaign_options": _campaign_options(state, country),
        "tiles": tiles,
        "frontier_candidates": frontier,
        "known_countries": sorted(state.countries),
        "pending_incoming_trades": incoming,
        "pending_outgoing_trades": outgoing,
        "diplomacy": {
            "relations": {
                other: state.relations.get(relation_key(country_id, other), 0)
                for other in state.countries if other != country_id
            },
            "incoming_pacts": [
                proposal for proposal in state.diplomatic_proposals.values()
                if proposal["target"] == country_id and proposal["status"] == "PENDING"
            ],
            "active_pacts": [
                pact for pact in state.pacts.values()
                if country_id in (pact["sender"], pact["target"])
            ],
            "outgoing_pacts": [
                proposal for proposal in state.diplomatic_proposals.values()
                if proposal["sender"] == country_id and proposal["status"] == "PENDING"
            ],
        },
        "recent_action_feedback": feedback,
        "recent_events": recent_events,
        "rules": {
            "allowed_actions": sorted(PUBLIC_ACTIONS),
            "max_actions_per_decision": state.config["max_actions_per_decision"],
            "buildings": state.config["buildings"],
            "research_fields": state.config["research_fields"],
            "policies": sorted(state.config["policies"]),
            "maximum_tax_rate": state.config["maximum_tax_rate"],
            "expansion": state.config["expansion"],
        },
    }


class AgentScheduler:
    def __init__(self, agents: dict[str, Any] | None = None) -> None:
        self.agents = agents or {}
        self.controlled_by_player: set[str] = set()

    def set_player_country(self, country_id: str | None) -> None:
        """The selected country becomes human-controlled; all others keep their controllers."""
        self.controlled_by_player = set() if country_id is None else {country_id}

    def set_agent(self, country_id: str, agent: Any) -> None:
        self.agents[country_id] = agent

    def _agent_for(self, country_id: str):
        if country_id not in self.agents:
            self.agents[country_id] = HeuristicAgent(country_id)
        return self.agents[country_id]

    async def _decide_safe(self, country_id: str, observation: dict[str, Any]):
        try:
            # Agents are untrusted: never alias live state into their observations.
            decision = await self._agent_for(country_id).decide(deepcopy(observation))
            return country_id, decision, None
        except Exception as exc:  # A controller must never crash the simulation.
            return country_id, {
                "country_id": country_id,
                "world_day": observation["world_day"],
                "actions": [{"type": "NO_OP"}],
                "reason": "Agent failure fallback",
            }, f"{type(exc).__name__}: {exc}"

    def plan(self, engine) -> dict[str, list]:
        observations = {
            country_id: build_observation(engine.state, country_id)
            for country_id in engine.state.countries
            if country_id not in self.controlled_by_player
        }
        if not observations:
            return {}
        async def gather_decisions():
            return await asyncio.gather(*[
                self._decide_safe(country_id, observation)
                for country_id, observation in observations.items()
            ])
        decisions = asyncio.run(gather_decisions())
        results = {}
        for country_id, decision, error in decisions:
            agent = self._agent_for(country_id)
            drain_usage = getattr(agent, "drain_usage_events", None)
            if drain_usage is not None:
                for usage_event in drain_usage():
                    engine.state.record("llm_call", country_id=country_id, **usage_event)
            if error is not None:
                engine.state.record("agent_fallback", country_id=country_id, error=error)
            elif agent.__class__.__name__ == "OpenAICompatibleAgent":
                # Preserve the actual model action response, never the API key or request headers.
                engine.state.record("llm_decision", country_id=country_id, decision=decision)
                if (
                    decision.get("country_id") == country_id
                    and decision.get("world_day") == engine.state.day_index
                ):
                    raw_diary = decision.get("diary")
                    diary = raw_diary if isinstance(raw_diary, dict) else {}
                    text = str(diary.get("text") or decision.get("reason") or "").strip()
                    if text:
                        settings = getattr(agent, "settings", None)
                        engine.state.record(
                            "llm_diary",
                            country_id=country_id,
                            title=str(diary.get("title") or "决策记录")[:40],
                            mood=str(diary.get("mood") or "未说明")[:16],
                            text=text[:1600],
                            reason=str(decision.get("reason") or "")[:1000],
                            actions=decision.get("actions", [])[:4],
                            provider=getattr(settings, "provider", None),
                            model=getattr(settings, "model", None),
                            synthetic=not bool(raw_diary),
                        )
            results[country_id] = engine.apply_decision(country_id, decision)
        return results
