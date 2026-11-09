"""Deterministic, API-free country baselines with distinct strategic preferences."""
from __future__ import annotations

from typing import Any

from agents.base import CountryAgent
from agents.personality import personality_definition

PREFERENCES = {
    "ELAR": {"policy": "AGRICULTURE", "research": "agriculture", "building": "FARM"},
    "MARIS": {"policy": "TRADE", "research": "bronze_metallurgy", "building": "ROAD"},
    "VAYR": {"policy": "INDUSTRY", "research": "bronze_metallurgy", "building": "MINE"},
    "SAHAR": {"policy": "AGRICULTURE", "research": "agriculture", "building": "FARM"},
}
DEFAULT_PROFILES = [
    {"policy": "AGRICULTURE", "research": "agriculture", "building": "FARM"},
    {"policy": "TRADE", "research": "bronze_metallurgy", "building": "ROAD"},
    {"policy": "INDUSTRY", "research": "bronze_metallurgy", "building": "MINE"},
    {"policy": "BALANCED", "research": "writing", "building": "LIBRARY"},
]
PROFILE_ALIASES = {"A": "ELAR", "B": "MARIS", "C": "VAYR", "D": "SAHAR"}


class HeuristicAgent(CountryAgent):
    def __init__(self, country_id: str) -> None:
        self.country_id = country_id
        # New/custom worlds may contain any number of countries. Keep the four
        # tuned profiles as special cases, but never fail for an unknown ID.
        profile_id = PROFILE_ALIASES.get(country_id, country_id)
        profile_index = sum(ord(char) for char in country_id) % len(DEFAULT_PROFILES)
        self.preference = dict(
            PREFERENCES.get(profile_id, DEFAULT_PROFILES[profile_index])
        )

    async def decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        country = observation["country"]
        rules = observation["rules"]
        personality = personality_definition(country.get("personality"))
        profile = personality["mock"]
        actions: list[dict[str, Any]] = []

        incoming_pacts = observation.get("diplomacy", {}).get("incoming_pacts", [])
        if incoming_pacts:
            pact = sorted(incoming_pacts, key=lambda item: item["created_day"])[0]
            actions.append({
                "type": "DIPLOMACY", "operation": "ACCEPT_PACT",
                "proposal_id": pact["proposal_id"],
            })

        wars = country.get("at_war_with", [])
        campaigns = observation.get("campaign_options", {})
        if wars:
            if country.get("war_exhaustion", 0) >= profile["peace_exhaustion"]:
                actions.append({
                    "type": "DIPLOMACY", "operation": "PROPOSE_PEACE", "target": wars[0],
                })
            if country.get("army_strength", 0) > 0:
                actions.append({
                    "type": "MILITARY", "operation": "ATTACK", "target": wars[0],
                })
        elif observation["world_day"] >= profile["recruit_day"]:
            army = country.get("army_strength", 0)
            if army == 0 and country["treasury"] > profile["recruit_first"] and country["food"] > 80:
                actions.append({"type": "MILITARY", "operation": "RECRUIT", "strength": 2})
            elif army < profile["army_target"] and country["treasury"] > profile["recruit_extra"]:
                actions.append({"type": "MILITARY", "operation": "RECRUIT", "strength": 1})

        incoming = sorted(
            observation["pending_incoming_trades"],
            key=lambda trade: trade["offer_food"] / max(trade["request_treasury"], 0.001),
            reverse=True,
        )
        if incoming:
            trade = incoming[0]
            affordable = country["treasury"] >= trade["request_treasury"]
            fair = trade["request_treasury"] <= max(0.5, trade["offer_food"] * 0.75)
            operation = "ACCEPT" if affordable and fair else "REJECT"
            actions.append({
                "type": "TRADE", "operation": operation,
                "proposal_id": trade["proposal_id"],
            })

        research = self._research_choice(country)
        if country["research_field"] != research and len(actions) < 4:
            actions.append({"type": "SET_RESEARCH", "field": research})
        policy = self.preference["policy"]
        if country["policy"] != policy and len(actions) < 4:
            actions.append({"type": "SET_POLICY", "priority": policy})

        desired_workers = self._workers(country)
        if country["workers"] != desired_workers and len(actions) < 4:
            actions.append({"type": "ALLOCATE_WORKERS", **desired_workers})

        expansion = rules["expansion"]
        if (
            len(actions) < profile["expand_actions"]
            and country["outposts"] < expansion["max_outposts"]
            and country["treasury"] >= expansion["treasury_cost"] + profile["expand_reserve"]
            and country["food"] >= profile["expand_food"]
            and observation["frontier_candidates"]
        ):
            candidates = observation["frontier_candidates"]
            target = max(
                candidates,
                key=lambda tile: (1 if tile["river"] else 0, tile["biome"] == "grassland"),
            )
            actions.append({
                "type": "SETTLE",
                "tile": {"col": target["col"], "row": target["row"]},
            })

        projected_treasury = country["treasury"]
        chosen_tiles = set()
        chosen_buildings = set()
        for _ in range(2):
            if len(country["projects"]) + sum(1 for action in actions if action["type"] == "BUILD") >= 2 or len(actions) >= 4:
                break
            building = self._building_choice(country)
            spec = rules["buildings"][building]
            if spec.get("max_per_country") and (
                building in chosen_buildings
                or sum(value == building for value in country["buildings"].values())
                + sum(project["building"] == building for project in country["projects"]) >= spec["max_per_country"]
            ):
                break
            cost = spec["cost"]
            if projected_treasury < cost:
                break
            tile = self._choose_tile(
                [tile for tile in observation["tiles"] if (tile["col"], tile["row"]) not in chosen_tiles],
                building,
            )
            if tile is None:
                break
            chosen_tiles.add((tile["col"], tile["row"]))
            chosen_buildings.add(building)
            projected_treasury -= cost
            actions.append({
                "type": "BUILD",
                "tile": {"col": tile["col"], "row": tile["row"]},
                "building": building,
            })

        diplomacy = observation.get("diplomacy", {})
        relations = diplomacy.get("relations", {})
        active_partners = {
            partner for pact in diplomacy.get("active_pacts", [])
            for partner in (pact["sender"], pact["target"]) if partner != self.country_id
        }
        partners = [partner for partner in sorted(relations) if partner not in wars]
        if partners and len(actions) < 4:
            partner = partners[(observation["world_day"] // 90) % len(partners)]
            relation = relations.get(partner, 0)
            has_pending = any(
                proposal["sender"] == self.country_id and proposal["target"] == partner
                for proposal in observation.get("diplomacy", {}).get("outgoing_pacts", [])
            )
            if relation >= profile["pact_relation"] and partner not in active_partners and not has_pending:
                actions.append({
                    "type": "DIPLOMACY", "operation": "PROPOSE_PACT",
                    "target": partner, "pact": "TRADE",
                })
            elif relation < profile["gift_relation"] and country["treasury"] > profile["gift_treasury"]:
                actions.append({
                    "type": "DIPLOMACY", "operation": "GIFT",
                    "target": partner, "amount": min(profile["gift_max"], round(country["treasury"] * 0.06, 2)),
                })

        if (
            not wars and country.get("army_strength", 0) >= profile["war_min_army"]
            and observation["world_day"] >= profile["recruit_day"] and len(actions) < 4
        ):
            foreign = observation.get("foreign_military", {})
            rivals = [
                partner for partner, relation in relations.items()
                if relation <= profile["war_relation"] and foreign.get(partner, 0) < country["army_strength"]
                and campaigns.get(partner, {}).get("reachable")
            ]
            if rivals and ((observation["world_day"] // 90 + len(self.country_id)) % profile["war_roll"] == 0):
                actions.append({
                    "type": "DIPLOMACY", "operation": "DECLARE_WAR",
                    "target": sorted(rivals)[0],
                })

        outgoing = observation["pending_outgoing_trades"]
        if country["food"] > profile["trade_food"] and not outgoing and len(actions) < 4:
            partners = sorted(set(observation["known_countries"]) - {self.country_id})
            if partners:
                # Deterministic rotation without relying on model output or hidden state.
                target = partners[(observation["world_day"] // 90) % len(partners)]
                actions.append({
                    "type": "TRADE", "operation": "PROPOSE", "target": target,
                    "offer_food": 5.0, "request_treasury": 3.0,
                })

        if not actions:
            actions.append({"type": "NO_OP"})
        return {
            "country_id": self.country_id,
            "world_day": observation["world_day"],
            "actions": actions[: rules["max_actions_per_decision"]],
            "reason": self._reason(country, personality),
        }

    def _workers(self, country: dict[str, Any]) -> dict[str, float]:
        if country["food"] < 60 or country["last_economy"].get("food_shortage", 0) > 0:
            return {"agriculture": 0.7, "mining": 0.1, "construction": 0.2}
        profile = personality_definition(country.get("personality"))["mock"]
        if profile.get("workers"):
            if country.get("personality") == "conservative" and country["food"] < 150:
                return {"agriculture": 0.75, "mining": 0.05, "construction": 0.2}
            return dict(profile["workers"])
        if self.preference["policy"] == "INDUSTRY":
            return {"agriculture": 0.45, "mining": 0.35, "construction": 0.2}
        if self.preference["policy"] in {"TRADE", "RESEARCH"}:
            return {"agriculture": 0.5, "mining": 0.3, "construction": 0.2}
        return {"agriculture": 0.65, "mining": 0.15, "construction": 0.2}

    def _research_choice(self, country: dict[str, Any]) -> str:
        technology = country["technology"]
        preferred = self.preference["research"]
        if technology.get("writing", 0) < 1:
            return "writing"
        if technology.get(preferred, 1) < 2:
            return preferred
        if technology.get("writing", 0) < 2:
            return "writing"
        # Advance the era instead of pouring everything into one line forever.
        lowest = min(technology.values())
        balanced_candidates = [
            field for field in ("agriculture", "bronze_metallurgy", "writing")
            if technology.get(field, 0) == lowest
        ]
        if preferred in balanced_candidates:
            return preferred
        return balanced_candidates[0] if balanced_candidates else preferred

    def _building_choice(self, country: dict[str, Any]) -> str:
        technology = country["technology"]
        counts = {}
        for building in country["buildings"].values():
            counts[building] = counts.get(building, 0) + 1
        for project in country["projects"]:
            counts[project["building"]] = counts.get(project["building"], 0) + 1
        personality = country.get("personality", "neutral")
        wonders = (
            ("GREAT_GRANARY", "agriculture", 3, 220),
            ("GREAT_FORGE", "bronze_metallurgy", 3, 260),
            ("GREAT_LIBRARY", "writing", 3, 300),
        )
        if personality == "aggressive":
            wonders = (wonders[1], wonders[0], wonders[2])
        elif personality == "conservative":
            wonders = (wonders[0], wonders[2], wonders[1])
        for name, field, level, cost in wonders:
            if technology.get(field, 0) >= level and not counts.get(name) and country["treasury"] >= cost:
                return name
        cities = country.get("cities", [])
        low_health = any(float(city.get("health", 100)) < 45 for city in cities)
        low_security = any(float(city.get("security", 100)) < 45 for city in cities)
        if low_health and technology.get("agriculture", 0) >= 2 and not counts.get("GRANARY"):
            return "GRANARY"
        if low_security and technology.get("writing", 0) >= 1 and not counts.get("TEMPLE"):
            return "TEMPLE"
        crowded = country["population"] / 1000.0 >= country["housing"] - 1
        if country["stability"] < 55 and technology.get("writing", 0) >= 1 and not counts.get("TEMPLE"):
            return "TEMPLE"
        near_storage_limit = country["food"] >= country.get("food_capacity", 99999) - 70
        if (country["food"] < 110 or crowded or near_storage_limit) and technology.get("agriculture", 0) >= 2 and not counts.get("GRANARY"):
            return "GRANARY"
        if country["food"] < 100:
            return "FARM"
        if technology.get("bronze_metallurgy", 0) >= 2 and not counts.get("WORKSHOP") and country["treasury"] > 35:
            return "WORKSHOP"
        if technology.get("writing", 0) >= 1 and not counts.get("LIBRARY") and country["treasury"] > 28:
            return "LIBRARY"
        if technology.get("agriculture", 0) >= 3 and not counts.get("MARKET") and country["treasury"] > 40:
            return "MARKET"
        if technology.get("writing", 0) >= 1 and not counts.get("TEMPLE") and country["stability"] < 72:
            return "TEMPLE"
        food_full = country["food"] >= country.get("food_capacity", 99999) - 10
        if food_full:
            if counts.get("ROAD", 0) < 3:
                return "ROAD"
            return "MINE"
        if personality == "aggressive":
            if technology.get("bronze_metallurgy", 0) >= 2 and counts.get("WORKSHOP", 0) < 2 and country["treasury"] > 40:
                return "WORKSHOP"
            if counts.get("MINE", 0) < 3 and country["food"] > 90:
                return "MINE"
        elif personality == "conservative":
            if technology.get("writing", 0) >= 1 and counts.get("TEMPLE", 0) < 1 and country["treasury"] > 25:
                return "TEMPLE"
            if technology.get("writing", 0) >= 1 and counts.get("LIBRARY", 0) < 1 and country["treasury"] > 28:
                return "LIBRARY"
        preferred = self.preference["building"]
        preferred_count = counts.get(preferred, 0) + sum(
            project["building"] == preferred for project in country["projects"]
        )
        if preferred_count >= 2:
            if counts.get("ROAD", 0) < 2:
                return "ROAD"
            return "FARM" if country["food"] < country.get("food_capacity", 99999) - 50 else "MINE"
        return preferred

    @staticmethod
    def _choose_tile(tiles: list[dict[str, Any]], building: str) -> dict[str, Any] | None:
        candidates = [tile for tile in tiles if not tile["building"] and not tile["project"]]
        if not candidates:
            return None
        def score(tile: dict[str, Any]) -> tuple[float, int, int]:
            if building == "FARM":
                biome = {"grassland": 4.0, "wetland": 4.5, "savanna": 3.5,
                         "forest": 2.8, "steppe": 2.0, "desert": 0.4}.get(tile["biome"], 0.0)
                value = biome + (1.5 if tile["river"] else 0.0) - tile["elevation_m"] / 2000.0
            elif building == "MINE":
                value = tile["elevation_m"] / 500.0 + (0.4 if tile["river"] else 0.0)
            else:
                value = 2.0 - abs(tile["elevation_m"] - 400.0) / 1000.0 + (0.5 if tile["river"] else 0.0)
            return value, -tile["row"], -tile["col"]
        return max(candidates, key=score)

    def _reason(self, country: dict[str, Any], personality: dict[str, Any]) -> str:
        return (
            f"{self.country_id} · {personality['label']}性格（{personality['tagline']}）："
            f"优先 {self.preference['building']}、{self.preference['research']} 研究与 "
            f"{self.preference['policy']} 政策；当前粮食 {country['food']:.1f}，"
            f"财政 {country['treasury']:.1f}。"
        )
