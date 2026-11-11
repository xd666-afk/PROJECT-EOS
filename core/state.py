"""Immutable geographic input, mutable game state, and portable JSON saves."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORLD = BASE_DIR / "output" / "world_2000BCE.json"
DEFAULT_RULES = BASE_DIR / "config" / "rules.json"
MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relation_key(left: str, right: str) -> str:
    return "|".join(sorted((left, right)))


def tile_key(coord: tuple[int, int]) -> str:
    return f"{coord[0]},{coord[1]}"


def parse_tile_key(key: str) -> tuple[int, int]:
    col, row = key.split(",", 1)
    return int(col), int(row)


def _merge_defaults(defaults: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in saved.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def calendar_date(day_index: int, start_astronomical_year: int = -1999) -> dict[str, Any]:
    if day_index < 0:
        raise ValueError("day_index must be non-negative")
    year = start_astronomical_year + day_index // 365
    day_of_year = day_index % 365
    month = 0
    while day_of_year >= MONTH_DAYS[month]:
        day_of_year -= MONTH_DAYS[month]
        month += 1
    month += 1
    day = day_of_year + 1
    if year <= 0:
        label = f"公元前{1 - year}年{month}月{day}日"
    else:
        label = f"公元{year}年{month}月{day}日"
    return {
        "astronomical_year": year,
        "month": month,
        "day": day,
        "day_of_year": day_index % 365 + 1,
        "label": label,
    }


@dataclass(frozen=True)
class WorldStatic:
    path: Path
    sha256: str
    data: dict[str, Any]
    tiles: dict[tuple[int, int], dict[str, Any]]
    polities: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_WORLD) -> "WorldStatic":
        world_path = Path(path).resolve()
        data = json.loads(world_path.read_text(encoding="utf-8"))
        width = data["metadata"]["grid_width"]
        height = data["metadata"]["grid_height"]
        if len(data["tiles"]) != width * height:
            raise ValueError("world tile count does not match metadata")
        tiles = {(tile["col"], tile["row"]): tile for tile in data["tiles"]}
        if len(tiles) != len(data["tiles"]):
            raise ValueError("duplicate tile coordinates")
        polities = {polity["id"]: polity for polity in data["polities"]}
        if not polities:
            raise ValueError("world must contain at least one polity")
        return cls(world_path, file_sha256(world_path), data, tiles, polities)

    def tile(self, coord: tuple[int, int]) -> dict[str, Any]:
        try:
            return self.tiles[coord]
        except KeyError as exc:
            raise ValueError(f"unknown tile {coord}") from exc

    def neighbors(self, x: int, y: int):
        from worldgen import neighbors

        return neighbors(
            x, y,
            self.data["metadata"]["grid_width"],
            self.data["metadata"]["grid_height"],
        )


@dataclass
class CityState:
    city_id: str
    name: str
    center: tuple[int, int]
    population: int
    focus: str
    tiles: list[tuple[int, int]]
    founded_day: int = 0
    zones: dict[tuple[int, int], str] = field(default_factory=dict)
    managed_by: str = "ai"
    livability: float = 60.0
    food_output: float = 0.0
    food_need: float = 0.0
    food_balance: float = 0.0
    food_loss: float = 0.0
    budget: str = "balanced"
    local_revenue: float = 0.0
    local_upkeep: float = 0.0
    local_net: float = 0.0
    security: float = 55.0
    health: float = 55.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "city_id": self.city_id,
            "name": self.name,
            "center": list(self.center),
            "population": self.population,
            "focus": self.focus,
            "tiles": [list(coord) for coord in self.tiles],
            "founded_day": self.founded_day,
            "zones": {tile_key(coord): zone for coord, zone in self.zones.items()},
            "managed_by": self.managed_by,
            "livability": self.livability,
            "food_output": self.food_output,
            "food_need": self.food_need,
            "food_balance": self.food_balance,
            "food_loss": self.food_loss,
            "budget": self.budget,
            "local_revenue": self.local_revenue,
            "local_upkeep": self.local_upkeep,
            "local_net": self.local_net,
            "security": self.security,
            "health": self.health,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CityState":
        return cls(
            city_id=data["city_id"],
            name=data["name"],
            center=tuple(data["center"]),
            population=int(data["population"]),
            focus=data.get("focus", "balanced"),
            tiles=[tuple(coord) for coord in data["tiles"]],
            founded_day=int(data.get("founded_day", 0)),
            zones={parse_tile_key(key): zone for key, zone in data.get("zones", {}).items()},
            managed_by=data.get("managed_by", "ai"),
            livability=float(data.get("livability", 60.0)),
            food_output=float(data.get("food_output", 0.0)),
            food_need=float(data.get("food_need", 0.0)),
            food_balance=float(data.get("food_balance", 0.0)),
            food_loss=float(data.get("food_loss", 0.0)),
            budget=data.get("budget", "balanced"),
            local_revenue=float(data.get("local_revenue", 0.0)),
            local_upkeep=float(data.get("local_upkeep", 0.0)),
            local_net=float(data.get("local_net", 0.0)),
            security=float(data.get("security", 55.0)),
            health=float(data.get("health", 55.0)),
        )


@dataclass
class CountryState:
    country_id: str
    name: str
    population: int
    food: float
    treasury: float
    tiles: list[tuple[int, int]]
    technology: dict[str, int]
    tax_rate: float
    workers: dict[str, float] = field(default_factory=dict)
    research_field: str = "agriculture"
    research_progress: dict[str, float] = field(default_factory=dict)
    policy: str = "BALANCED"
    buildings: dict[tuple[int, int], str] = field(default_factory=dict)
    projects: list[dict[str, Any]] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)
    outposts: list[tuple[int, int]] = field(default_factory=list)
    last_economy: dict[str, float] = field(default_factory=dict)
    shortage_days_total: int = 0
    days_without_shortage: int = 0
    stability: float = 60.0
    army_strength: int = 0
    army_position: tuple[int, int] | None = None
    at_war_with: list[str] = field(default_factory=list)
    war_exhaustion: float = 0.0
    cities: list[CityState] = field(default_factory=list)
    personality: str = "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "country_id": self.country_id,
            "name": self.name,
            "population": self.population,
            "food": self.food,
            "treasury": self.treasury,
            "tiles": [list(coord) for coord in self.tiles],
            "technology": self.technology,
            "tax_rate": self.tax_rate,
            "workers": self.workers,
            "research_field": self.research_field,
            "research_progress": self.research_progress,
            "policy": self.policy,
            "buildings": {tile_key(coord): building for coord, building in self.buildings.items()},
            "projects": self.projects,
            "contacts": self.contacts,
            "outposts": [list(coord) for coord in self.outposts],
            "last_economy": self.last_economy,
            "shortage_days_total": self.shortage_days_total,
            "days_without_shortage": self.days_without_shortage,
            "stability": self.stability,
            "army_strength": self.army_strength,
            "army_position": list(self.army_position) if self.army_position else None,
            "at_war_with": self.at_war_with,
            "war_exhaustion": self.war_exhaustion,
            "cities": [city.to_dict() for city in self.cities],
            "personality": self.personality,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CountryState":
        restored = cls(
            country_id=data["country_id"],
            name=data["name"],
            population=data["population"],
            food=data["food"],
            treasury=data["treasury"],
            tiles=[tuple(coord) for coord in data["tiles"]],
            technology=data["technology"],
            tax_rate=data["tax_rate"],
            workers=data["workers"],
            research_field=data["research_field"],
            research_progress=data["research_progress"],
            policy=data["policy"],
            buildings={parse_tile_key(key): value for key, value in data["buildings"].items()},
            projects=data["projects"],
            contacts=data["contacts"],
            outposts=[tuple(coord) for coord in data.get("outposts", [])],
            last_economy=data["last_economy"],
            shortage_days_total=data["shortage_days_total"],
            days_without_shortage=data["days_without_shortage"],
            stability=float(data.get("stability", 60.0)),
            army_strength=int(data.get("army_strength", 0)),
            army_position=tuple(data["army_position"]) if data.get("army_position") else None,
            at_war_with=list(data.get("at_war_with", [])),
            war_exhaustion=float(data.get("war_exhaustion", 0.0)),
            cities=[CityState.from_dict(city) for city in data.get("cities", [])],
            personality=str(data.get("personality", "neutral")),
        )
        for project in restored.projects:
            project["tile"] = tuple(project["tile"])
        return restored


class GameState:
    def __init__(self, world: WorldStatic, config: dict[str, Any], seed: int) -> None:
        from core.weather import WeatherModel

        self.world = world
        self.config = deepcopy(config)
        self.seed = seed
        self.start_astronomical_year = int(
            world.data["metadata"].get("astronomical_year", -1999)
        )
        from core.society import starting_era_for_year
        self.start_era_index = starting_era_for_year(
            self.config, self.start_astronomical_year
        )["index"]
        self.day_index = 0
        self.countries: dict[str, CountryState] = {}
        self.trades: dict[str, dict[str, Any]] = {}
        self.relations: dict[str, int] = {}
        country_ids = sorted(world.polities)
        for index, left in enumerate(country_ids):
            for right in country_ids[index + 1:]:
                self.relations[f"{left}|{right}"] = 0
        self.pacts: dict[str, dict[str, Any]] = {}
        self.diplomatic_proposals: dict[str, dict[str, Any]] = {}
        self.next_diplomacy_number = 1
        self.action_log: list[dict[str, Any]] = []
        self.event_log: list[dict[str, Any]] = []
        self.next_action_number = 1
        self.next_project_number = 1
        self.next_trade_number = 1
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self.weather = WeatherModel(world, seed)

    @classmethod
    def new(
        cls,
        world_path: str | Path = DEFAULT_WORLD,
        config_path: str | Path | dict[str, Any] = DEFAULT_RULES,
        seed: int = 2000,
    ) -> "GameState":
        world = WorldStatic.load(world_path)
        config = (
            deepcopy(config_path)
            if isinstance(config_path, dict)
            else json.loads(Path(config_path).read_text(encoding="utf-8"))
        )
        from core.society import default_zone

        state = cls(world, config, seed)
        for country_id, polity in world.polities.items():
            capital = (int(polity["capital"]["col"]), int(polity["capital"]["row"]))
            state.countries[country_id] = CountryState(
                country_id=country_id,
                name=polity["name"],
                cities=[CityState(
                    city_id=f"{country_id}-C1",
                    name=f"{polity['name']}都城",
                    center=capital,
                    population=int(polity["population"]),
                    focus="balanced",
                    tiles=[tuple(coord) for coord in polity["initial_tiles"]],
                    founded_day=0,
                    zones={
                        (int(coord[0]), int(coord[1])): default_zone(
                            capital,
                            (int(coord[0]), int(coord[1])),
                            world.tiles[(int(coord[0]), int(coord[1]))],
                        )
                        for coord in polity["initial_tiles"]
                    },
                )],
                population=int(polity["population"]),
                food=float(polity["food_storage_units"]),
                treasury=float(polity["treasury_units"]),
                tiles=[tuple(coord) for coord in polity["initial_tiles"]],
                technology=deepcopy(polity["technology"]),
                tax_rate=float(config["default_tax_rate"]),
                workers=deepcopy(config["workers_baseline"]),
                research_progress={field: 0.0 for field in config["research_fields"]},
                stability=float(config["stability"]["initial"]),
                personality=str(polity.get("personality", "neutral")),
                army_position=(
                    int(polity["capital"]["col"]), int(polity["capital"]["row"])
                ),
            )
        state.record("simulation_initialized", seed=seed, rules_version=config["rules_version"])
        return state

    @property
    def date(self) -> dict[str, Any]:
        return calendar_date(self.day_index, self.start_astronomical_year)

    def sync_city_population(self, country: CountryState) -> None:
        """Keep national population equal to the sum of city populations."""
        if not country.cities:
            from core.society import default_zone
            capital = self.world.polities[country.country_id]["capital"]
            center = (int(capital["col"]), int(capital["row"]))
            country.cities = [CityState(
                city_id=f"{country.country_id}-C1",
                name=f"{country.name}都城",
                center=center,
                population=country.population,
                focus="balanced",
                tiles=list(country.tiles),
                zones={
                    coord: default_zone(center, coord, self.world.tiles[coord])
                    for coord in country.tiles
                },
            )]
            return
        difference = country.population - sum(city.population for city in country.cities)
        if difference == 0:
            return
        target = max(country.cities, key=lambda city: city.population)
        target.population = max(0, target.population + difference)

    def configure_starting_era(self, astronomical_year: int) -> dict[str, Any]:
        from core.society import starting_era_for_year

        if not -799 <= astronomical_year <= 500:
            raise ValueError("start year must be between 800 BCE and 500 CE")
        era = starting_era_for_year(self.config, astronomical_year)
        baseline = int(era["baseline"])
        bonuses = {
            "river_valley": "agriculture",
            "semiarid": "agriculture",
            "highland": "bronze_metallurgy",
            "maritime": "writing",
        }
        maximum = self.config["research_max_level"]
        for country in self.countries.values():
            polity_type = self.world.polities[country.country_id].get("type")
            for field in self.config["research_fields"]:
                country.technology[field] = baseline
                country.research_progress[field] = 0.0
            bonus_field = bonuses.get(polity_type)
            if bonus_field:
                country.technology[bonus_field] = min(
                    maximum, country.technology[bonus_field] + 1
                )
        self.start_astronomical_year = astronomical_year
        self.start_era_index = int(era["index"])
        self.record(
            "era_configured",
            start_year=astronomical_year,
            era=era,
            baseline_technology=baseline,
        )
        return era

    def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(listener)

    def record(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "sequence": len(self.event_log) + 1,
            "day": self.day_index,
            "date": self.date["label"],
            "type": event_type,
            **payload,
        }
        self.event_log.append(event)
        for listener in self._listeners:
            listener(event)
        return event

    def victory_announced(self) -> bool:
        for event in reversed(self.event_log):
            if event["type"] == "victory":
                return True
        return False

    def victory_status(
        self, scores: dict[str, dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        from core.society import score_country, victory_progress

        progress = {
            country_id: victory_progress(country, self)
            for country_id, country in self.countries.items()
        }
        achievers = [
            country_id for country_id, value in progress.items() if value["any"]
        ]
        if scores is None:
            scores = {
                country_id: score_country(country, self.config)
                for country_id, country in self.countries.items()
            }
        winner = (
            max(achievers, key=lambda country_id: scores[country_id]["total"])
            if achievers else None
        )
        return {
            "winner": winner,
            "condition": progress[winner]["primary"] if winner else None,
            "label": progress[winner]["label"] if winner else "",
            "countries": progress,
        }

    def summary(self) -> dict[str, Any]:
        from core.society import (
            city_static_metrics,
            city_tier,
            era_info,
            food_capacity,
            housing_capacity,
            score_country,
            specialization,
            stability_factor,
        )

        country_eras = {
            country_id: era_info(self.config, min(country.technology.values()), self.start_era_index)
            for country_id, country in self.countries.items()
        }
        world_era = max(country_eras.values(), key=lambda era: era["index"])
        scores = {
            country_id: score_country(country, self.config)
            for country_id, country in self.countries.items()
        }
        victory = self.victory_status(scores)
        ranking = sorted(
            (
                {"country_id": country_id, **score}
                for country_id, score in scores.items()
            ),
            key=lambda entry: entry["total"],
            reverse=True,
        )
        return {
            "day": self.day_index,
            "date": self.date["label"],
            "era": world_era,
            "start_year": self.start_astronomical_year,
            "countries": {
                country_id: {
                    "population": country.population,
                    "food": round(country.food, 4),
                    "treasury": round(country.treasury, 4),
                    "tax_rate": country.tax_rate,
                    "workers": country.workers,
                    "policy": country.policy,
                    "research_field": country.research_field,
                    "research_progress": {
                        key: round(value, 4) for key, value in country.research_progress.items()
                    },
                    "technology": country.technology,
                    "buildings": {
                        tile_key(coord): building for coord, building in country.buildings.items()
                    },
                    "projects": len(country.projects),
                    "contacts": country.contacts,
                    "diplomacy": {
                        "relations": {
                            other: self.relations.get(relation_key(country_id, other), 0)
                            for other in self.countries if other != country_id
                        },
                        "active_pacts": [
                            pact for pact in self.pacts.values()
                            if pact["status"] == "ACTIVE"
                            and country_id in (pact["sender"], pact["target"])
                        ],
                        "incoming_proposals": [
                            proposal for proposal in self.diplomatic_proposals.values()
                            if proposal["target"] == country_id and proposal["status"] == "PENDING"
                        ],
                        "outgoing_proposals": [
                            proposal for proposal in self.diplomatic_proposals.values()
                            if proposal["sender"] == country_id and proposal["status"] == "PENDING"
                        ],
                    },
                    "tiles": [list(coord) for coord in country.tiles],
                    "outposts": [list(coord) for coord in country.outposts],
                    "cities": [
                        city_static_metrics(city, country, self.world, self.config)
                        for city in country.cities
                    ],
                    "shortage_days_total": country.shortage_days_total,
                    "stability": round(country.stability, 2),
                    "stability_factor": round(stability_factor(country.stability, self.config), 4),
                    "army_strength": country.army_strength,
                    "army_position": list(country.army_position) if country.army_position else None,
                    "at_war_with": country.at_war_with,
                    "war_exhaustion": round(country.war_exhaustion, 2),
                    "personality": country.personality,
                    "military_upkeep": round(country.army_strength * self.config["military"]["upkeep_per_strength_per_day"], 3),
                    "housing": housing_capacity(country, self.config),
                    "food_capacity": food_capacity(country, self.config),
                    "city_tier": city_tier(country.population),
                    "specialization": specialization(country),
                    "era": country_eras[country_id],
                    "last_economy": {
                        key: round(value, 6) for key, value in country.last_economy.items()
                    },
                    "victory": victory["countries"][country_id],
                    **scores[country_id],
                }
                for country_id, country in self.countries.items()
            },
            "victory": {
                "winner": victory["winner"],
                "condition": victory["condition"],
                "label": victory["label"],
            },
            "ranking": ranking,
            "leader": ranking[0]["country_id"] if ranking else None,
            "trades": {
                status: sum(trade["status"] == status for trade in self.trades.values())
                for status in ("PENDING", "ACCEPTED", "REJECTED", "EXPIRED")
            },
        }

    def fingerprint(self) -> str:
        dynamic = {
            "day_index": self.day_index,
            "countries": {key: value.to_dict() for key, value in self.countries.items()},
            "trades": self.trades,
            "relations": self.relations,
            "pacts": self.pacts,
            "diplomatic_proposals": self.diplomatic_proposals,
            "weather": self.weather.to_dict(),
            "counters": [
                self.next_action_number, self.next_project_number,
                self.next_trade_number, self.next_diplomacy_number,
            ],
        }
        blob = json.dumps(dynamic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        try:
            world_reference = str(self.world.path.relative_to(BASE_DIR))
        except ValueError:
            world_reference = str(self.world.path)
        return {
            "format": "project-eos-dynamic-save",
            "format_version": 1,
            "rules_version": self.config["rules_version"],
            "world_file": world_reference,
            "world_sha256": self.world.sha256,
            "seed": self.seed,
            "day_index": self.day_index,
            "start_astronomical_year": self.start_astronomical_year,
            "start_era_index": self.start_era_index,
            "rules": self.config,
            "countries": {key: value.to_dict() for key, value in self.countries.items()},
            "trades": self.trades,
            "relations": self.relations,
            "pacts": self.pacts,
            "diplomatic_proposals": self.diplomatic_proposals,
            "weather": self.weather.to_dict(),
            "counters": {
                "action": self.next_action_number,
                "project": self.next_project_number,
                "trade": self.next_trade_number,
                "diplomacy": self.next_diplomacy_number,
            },
            "action_log": self.action_log,
            "event_log": self.event_log,
        }

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(destination)
        return destination

    @classmethod
    def load(
        cls,
        path: str | Path,
        world_path: str | Path | None = None,
    ) -> "GameState":
        from core.weather import WeatherModel

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != "project-eos-dynamic-save" or data.get("format_version") != 1:
            raise ValueError("unsupported save format")
        if world_path is None:
            candidate = Path(data["world_file"])
            world_path = candidate if candidate.is_absolute() else BASE_DIR / candidate
        world = WorldStatic.load(world_path)
        if world.sha256 != data["world_sha256"]:
            raise ValueError("static world SHA-256 differs from the saved baseline")
        state = cls.__new__(cls)
        state.world = world
        # Merge newly introduced rule fields into older saves without discarding saved tuning.
        default_config = json.loads(DEFAULT_RULES.read_text(encoding="utf-8"))
        state.config = _merge_defaults(default_config, data["rules"])
        # Content/schema updates (tech names, eras, building prerequisites) must come
        # from the current rules so old saves do not keep a superseded tech tree.
        for content_key in ("tech_tree", "eras", "research_fields", "buildings"):
            if content_key in default_config:
                state.config[content_key] = deepcopy(default_config[content_key])
        state.seed = data["seed"]
        state.start_astronomical_year = int(
            data.get("start_astronomical_year", world.data["metadata"]["astronomical_year"])
        )
        from core.society import starting_era_for_year
        state.start_era_index = int(
            data.get(
                "start_era_index",
                starting_era_for_year(state.config, state.start_astronomical_year)["index"],
            )
        )
        state.day_index = data["day_index"]
        state.countries = {
            key: CountryState.from_dict(value) for key, value in data["countries"].items()
        }
        state.trades = data["trades"]
        state.relations = data.get("relations", {})
        for index, left in enumerate(sorted(state.countries)):
            for right in sorted(state.countries)[index + 1:]:
                state.relations.setdefault(relation_key(left, right), 0)
        state.pacts = data.get("pacts", {})
        state.diplomatic_proposals = data.get("diplomatic_proposals", {})
        state.action_log = data["action_log"]
        state.event_log = data["event_log"]
        counters = data["counters"]
        state.next_action_number = counters["action"]
        state.next_project_number = counters["project"]
        state.next_trade_number = counters["trade"]
        state.next_diplomacy_number = counters.get("diplomacy", 1)
        state._listeners = []
        state.weather = WeatherModel(world, state.seed, data["weather"])
        from core.society import default_zone
        for country in state.countries.values():
            for city in country.cities:
                if not city.zones or all(
                    city.zones.get(coord, "unzoned") == "unzoned" for coord in city.tiles
                ):
                    for coord in city.tiles:
                        city.zones[coord] = default_zone(
                            city.center, coord, world.tiles[coord]
                        )
            state.sync_city_population(country)
        return state
