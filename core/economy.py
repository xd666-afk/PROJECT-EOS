"""Daily food, treasury, population, and research settlement."""
from __future__ import annotations

from typing import Any

import numpy as np

from core.society import (
    building_counts,
    city_housing,
    city_livability_target,
    food_capacity,
    housing_capacity,
    stability_factor,
    zone_adjacency,
)
from core.state import CountryState, GameState, MONTH_DAYS, calendar_date


class Economy:
    def __init__(self, state: GameState) -> None:
        self.state = state
        self.config = state.config

    def _labor_factor(self, country: CountryState, sector: str) -> float:
        baseline = self.config["workers_baseline"][sector]
        return country.workers[sector] / baseline if baseline else 1.0

    def _tax_factor(self, country: CountryState) -> float:
        excess = max(0.0, country.tax_rate - self.config["high_tax_threshold"])
        return max(
            self.config["minimum_tax_production_factor"],
            1.0 - excess * self.config["high_tax_production_penalty"],
        )

    def tile_weather_factor(
        self,
        tile: dict[str, Any],
        rain: float,
        temperature: float,
        day_index: int,
    ) -> tuple[float, float, float]:
        month = calendar_date(
            day_index, self.state.world.data["metadata"]["astronomical_year"]
        )["month"] - 1
        expected_daily_rain = tile["monthly_precip_mm"][month] / MONTH_DAYS[month]
        rain_ratio = rain / max(expected_daily_rain, 0.05)
        weather_config = self.config["weather"]
        rain_factor = float(np.clip(
            0.85 + 0.25 * (rain_ratio - 1.0),
            weather_config["minimum_rain_factor"],
            weather_config["maximum_rain_factor"],
        ))
        temperature_factor = float(np.clip(
            0.55 + temperature / 50.0,
            weather_config["minimum_temperature_factor"],
            weather_config["maximum_temperature_factor"],
        ))
        return rain_factor, temperature_factor, rain_factor * temperature_factor

    def settle_country(
        self,
        country: CountryState,
        current_weather: dict[str, np.ndarray],
    ) -> dict[str, float]:
        baseline_food = 0.0
        baseline_mining = 0.0
        weather_factors: list[float] = []
        city_focus = {
            coord: city.focus for city in country.cities for coord in city.tiles
        }
        city_zone = {
            coord: city.zones.get(coord, "unzoned")
            for city in country.cities for coord in city.tiles
        }
        city_by_coord = {
            coord: city for city in country.cities for coord in city.tiles
        }
        city_food_base = {city.city_id: 0.0 for city in country.cities}
        city_mining_base = {city.city_id: 0.0 for city in country.cities}
        city_tax_bonus = {city.city_id: 0.0 for city in country.cities}
        rural_food_base = 0.0
        focus_config = self.config["city_focuses"]
        zone_config = self.config["city_zones"]
        for coord in country.tiles:
            tile = self.state.world.tile(coord)
            row, col = coord[1], coord[0]
            _, _, weather_factor = self.tile_weather_factor(
                tile,
                float(current_weather["rain"][row, col]),
                float(current_weather["temperature"][row, col]),
                self.state.day_index,
            )
            weather_factors.append(weather_factor)
            biome_yield = self.config["biome_food_yield"].get(tile["biome"], 0.4)
            food = self.config["base_food_per_tile"] * biome_yield
            mining = self.config["base_mine_per_tile"] * (
                1.0 + min(max(tile["elevation_m"], 0) / 2000.0, 1.0)
            )
            building = country.buildings.get(coord)
            if building == "FARM":
                food += self.config["farm_food_bonus"] * max(biome_yield, 0.5)
            elif building == "MINE":
                mining += self.config["mine_treasury_bonus"] * (
                    1.0 + min(max(tile["elevation_m"], 0) / 1500.0, 1.5)
                )
            road_factor = 1.0 + (
                self.config["road_production_bonus"] if building == "ROAD" else 0.0
            )
            focus = focus_config.get(city_focus.get(coord, "balanced"), focus_config["balanced"])
            zone = zone_config.get(city_zone.get(coord, "unzoned"), zone_config["unzoned"])
            city = city_by_coord.get(coord)
            adjacency = zone_adjacency(city, coord) if city else {
                "food": 1.0, "mining": 1.0, "tax": 1.0, "research": 1.0,
            }
            livability_factor = 0.8 + max(0, min(100, city.livability)) / 200.0 if city else 1.0
            tile_food = food * weather_factor * road_factor * focus["food"] * zone["food"] * adjacency["food"] * livability_factor
            baseline_food += tile_food
            if city is not None:
                city_food_base[city.city_id] += tile_food
                city_tax_bonus[city.city_id] += zone["tax_bonus"] + (adjacency["tax"] - 1.0)
            else:
                rural_food_base += tile_food
            tile_mining = mining * road_factor * focus["mining"] * zone["mining"] * adjacency["mining"] * livability_factor
            baseline_mining += tile_mining
            if city is not None:
                city_mining_base[city.city_id] += tile_mining

        agriculture_technology = 1.0 + (
            country.technology.get("agriculture", 1) - 1
        ) * self.config["agriculture_bonus_per_level"]
        metallurgy_technology = 1.0 + (
            country.technology.get("bronze_metallurgy", 1) - 1
        ) * self.config["metallurgy_bonus_per_level"]
        counts = building_counts(country)
        policy = self.config["policies"][country.policy]
        tax_factor = self._tax_factor(country)
        social_factor = stability_factor(country.stability, self.config)
        food_buildings = (
            1.0
            + counts.get("GRANARY", 0) * 0.08
            + counts.get("IRRIGATION", 0) * 0.12
            + counts.get("GREAT_GRANARY", 0) * 0.20
        )
        mining_buildings = 1.0 + counts.get("WORKSHOP", 0) * 0.15 + counts.get("GREAT_FORGE", 0) * 0.25
        trade_buildings = 1.0 + counts.get("MARKET", 0) * 0.15
        food_factor = (
            self._labor_factor(country, "agriculture")
            * agriculture_technology
            * policy["food"]
            * tax_factor
            * social_factor
            * food_buildings
        )
        food_production = baseline_food * food_factor
        mine_count = counts.get("MINE", 0)
        extraction_efficiency = 1.0
        excess_mines = max(0, mine_count - self.config["mine_diminishing_start"])
        if excess_mines:
            extraction_efficiency = max(
                self.config["mine_minimum_efficiency"],
                1.0 / (1.0 + excess_mines * self.config["mine_diminishing_penalty"]),
            )
        mine_income = (
            baseline_mining
            * self._labor_factor(country, "mining")
            * metallurgy_technology
            * policy["mining"]
            * tax_factor
            * social_factor
            * mining_buildings
            * extraction_efficiency
        )
        trade_pacts = sum(
            1 for pact in self.state.pacts.values()
            if pact["status"] == "ACTIVE" and pact.get("pact") == "TRADE"
            and country.country_id in (pact["sender"], pact["target"])
        )
        population_total = max(sum(city.population for city in country.cities), 1)
        city_tax_multiplier = sum(
            city.population * focus_config.get(city.focus, focus_config["balanced"]).get("tax", 1.0)
            for city in country.cities
        ) / population_total
        zone_tax_bonus = sum(
            zone_config.get(city_zone.get(coord, "unzoned"), zone_config["unzoned"])["tax_bonus"]
            + (zone_adjacency(city_by_coord[coord], coord)["tax"] - 1.0 if coord in city_by_coord else 0.0)
            for coord in country.tiles
        )
        city_tax_multiplier *= 1.0 + zone_tax_bonus
        tax_income = (
            country.population * country.tax_rate
            / self.config["treasury_population_tax_divisor"]
            * policy.get("tax", 1.0)
            * trade_buildings
            * (1.0 + trade_pacts * 0.05)
            * city_tax_multiplier
        )
        upkeep = len(country.buildings) * self.config["building_upkeep_per_day"]
        food_per_1000 = self.config["food_per_1000_people_per_day"]
        consumption = country.population / 1000.0 * food_per_1000
        logistics_config = self.config["city_logistics"]
        road_relief = min(
            logistics_config["max_road_loss_reduction"],
            counts.get("ROAD", 0) * logistics_config["road_loss_reduction"],
        )
        export_loss_rate = max(0.01, logistics_config["export_loss"] - road_relief)
        import_loss_rate = max(0.02, logistics_config["import_loss"] - road_relief)
        logistics_loss = 0.0
        city_surplus = 0.0
        city_deficit = 0.0
        for city in country.cities:
            output = city_food_base.get(city.city_id, 0.0) * food_factor
            need = city.population / 1000.0 * food_per_1000
            balance = output - need
            loss = (balance * export_loss_rate) if balance > 0 else (-balance * import_loss_rate)
            city.food_output = output
            city.food_need = need
            city.food_balance = balance
            city.food_loss = loss
            logistics_loss += loss
            if balance > 0:
                city_surplus += balance
            else:
                city_deficit += -balance
        rural_output = rural_food_base * food_factor
        budget_config = self.config["city_budgets"]
        service_rate = self.config["city_service_cost_per_1000"]
        upkeep_per_building = self.config["building_upkeep_per_day"]
        city_tax_weight = {
            city.city_id: max(
                1e-9,
                city.population
                * focus_config.get(city.focus, focus_config["balanced"]).get("tax", 1.0)
                * (1.0 + city_tax_bonus.get(city.city_id, 0.0)),
            )
            for city in country.cities
        }
        total_tax_weight = sum(city_tax_weight.values())
        service_spend_total = 0.0
        for city in country.cities:
            weight = city_tax_weight[city.city_id]
            tax_share = tax_income * weight / total_tax_weight if total_tax_weight else 0.0
            mining_share = (
                mine_income * city_mining_base.get(city.city_id, 0.0) / baseline_mining
                if baseline_mining > 1e-12 else 0.0
            )
            building_upkeep = (
                sum(1 for coord in city.tiles if coord in country.buildings)
                * upkeep_per_building
            )
            budget = budget_config.get(city.budget, budget_config["balanced"])
            service_spend = (
                city.population / 1000.0 * service_rate * budget["service_factor"]
            )
            city.local_revenue = tax_share + mining_share
            city.local_upkeep = building_upkeep + service_spend
            city.local_net = city.local_revenue - city.local_upkeep
            service_spend_total += service_spend
        available_food = country.food + food_production - logistics_loss
        shortage = max(0.0, consumption - available_food)
        storage_capacity = food_capacity(country, self.config)
        unbounded_food = max(0.0, available_food - consumption)
        food_overflow = max(0.0, unbounded_food - storage_capacity)
        country.food = min(storage_capacity, unbounded_food)
        population_loss = 0
        if shortage > 1e-12:
            shortage_ratio = shortage / max(consumption, 1e-12)
            population_loss = min(
                country.population,
                max(1, int(country.population * shortage_ratio * self.config["shortage_mortality_fraction"])),
            )
            country.population -= population_loss
            self._distribute_famine(country, population_loss)
            country.shortage_days_total += 1
            country.days_without_shortage = 0
            self.state.record(
                "food_shortage",
                country_id=country.country_id,
                shortage_units=round(shortage, 6),
                population_loss=population_loss,
            )
        else:
            country.days_without_shortage += 1
        net_income = tax_income + mine_income - upkeep - service_spend_total
        country.treasury = max(0.0, country.treasury + net_income)
        metrics = {
            "food_production": food_production,
            "food_consumption": consumption,
            "food_shortage": shortage,
            "food_capacity": storage_capacity,
            "food_overflow": food_overflow,
            "food_logistics_loss": logistics_loss,
            "city_service_spend": service_spend_total,
            "city_food_surplus": city_surplus,
            "city_food_deficit": city_deficit,
            "rural_food_output": rural_output,
            "export_loss_rate": export_loss_rate,
            "import_loss_rate": import_loss_rate,
            "tax_income": tax_income,
            "mine_income": mine_income,
            "upkeep": upkeep,
            "treasury_income": net_income,
            "mean_weather_factor": float(np.mean(weather_factors)) if weather_factors else 0.0,
            "population_loss": float(population_loss),
            "stability_factor": social_factor,
            "mine_efficiency": extraction_efficiency,
        }
        country.last_economy = metrics
        if (
            shortage > 0
            or self.state.day_index % self.config.get("economy_log_interval_days", 1) == 0
        ):
            self.state.record(
                "economy_daily",
            country_id=country.country_id,
            food_production=round(food_production, 6),
            food_consumption=round(consumption, 6),
            food_storage=round(country.food, 6),
            food_capacity=round(storage_capacity, 6),
            food_overflow=round(food_overflow, 6),
            food_logistics_loss=round(logistics_loss, 6),
            city_service_spend=round(service_spend_total, 6),
            city_food_deficit=round(city_deficit, 6),
            treasury_income=round(net_income, 6),
            upkeep=round(upkeep, 6),
            stability=round(country.stability, 3),
            treasury=round(country.treasury, 6),
            weather_factor=round(metrics["mean_weather_factor"], 6),
            population=country.population,
        )
        return metrics

    def _distribute_famine(self, country: CountryState, loss: int) -> None:
        """Famine hits importing cities first, then evens out national totals."""
        if loss <= 0 or not country.cities:
            return
        weights = [
            max(0.0, city.food_need - city.food_output) for city in country.cities
        ]
        if sum(weights) <= 1e-9:
            weights = [float(city.population) for city in country.cities]
        total_weight = sum(weights) or 1.0
        order = sorted(
            range(len(country.cities)), key=lambda index: weights[index], reverse=True
        )
        remaining = loss
        for position, index in enumerate(order):
            if remaining <= 0:
                break
            city = country.cities[index]
            if position == len(order) - 1:
                amount = min(city.population, remaining)
            else:
                amount = min(city.population, int(loss * weights[index] / total_weight))
            city.population -= amount
            remaining -= amount
        difference = country.population - sum(city.population for city in country.cities)
        if difference:
            target = max(country.cities, key=lambda city: city.population)
            target.population = max(0, target.population + difference)

    def settle_all(self, current_weather: dict[str, np.ndarray]) -> None:
        for country in self.state.countries.values():
            self.settle_country(country, current_weather)

    def advance_research(self, country: CountryState) -> None:
        field = country.research_field
        level = country.technology[field]
        if level >= self.config["research_max_level"]:
            return
        writing_level = country.technology.get("writing", 0)
        writing_factor = 1.0 + writing_level * self.config["writing_research_bonus_per_level"]
        policy_factor = self.config["policies"][country.policy]["research"]
        counts = building_counts(country)
        library_factor = 1.0 + counts.get("LIBRARY", 0) * 0.18 + counts.get("GREAT_LIBRARY", 0) * 0.25
        population_total = max(sum(city.population for city in country.cities), 1)
        zone_config = self.config["city_zones"]
        city_zone = {
            coord: city.zones.get(coord, "unzoned")
            for city in country.cities for coord in city.tiles
        }
        city_by_coord = {
            coord: city for city in country.cities for coord in city.tiles
        }
        city_research_multiplier = sum(
            city.population * self.config["city_focuses"].get(
                city.focus, self.config["city_focuses"]["balanced"]
            ).get("research", 1.0)
            for city in country.cities
        ) / population_total
        city_research_multiplier *= 1.0 + sum(
            zone_config.get(city_zone.get(coord, "unzoned"), zone_config["unzoned"])["research_bonus"]
            + (zone_adjacency(city_by_coord[coord], coord)["research"] - 1.0 if coord in city_by_coord else 0.0)
            for coord in country.tiles
        )
        points = (
            self.config["base_research_points_per_day"]
            * writing_factor
            * policy_factor
            * library_factor
            * stability_factor(country.stability, self.config)
            * city_research_multiplier
        )
        country.research_progress[field] += points
        threshold = self.config["research_base_threshold"] * level
        if country.research_progress[field] + 1e-12 >= threshold:
            country.research_progress[field] -= threshold
            country.technology[field] += 1
            self.state.record(
                "research_completed",
                country_id=country.country_id,
                field=field,
                level=country.technology[field],
            )

    def grow_population_monthly(self) -> None:
        for country in self.state.countries.values():
            if country.days_without_shortage < 30 or country.population <= 0:
                continue
            previous = country.population
            total_growth = 0
            for city in country.cities:
                capacity = city_housing(city, country, self.config)
                headroom = capacity - city.population / 1000.0
                growth_factor = 1.0 if headroom >= 2 else (0.5 if headroom >= 0 else 0.25)
                if city.food_need > city.food_output:
                    growth_factor *= self.config["city_logistics"]["import_growth_penalty"]
                budget = self.config["city_budgets"].get(
                    city.budget, self.config["city_budgets"]["balanced"]
                )
                growth_factor *= budget["growth"]
                growth = (
                    city.population
                    * self.config["monthly_population_growth_rate"]
                    * growth_factor
                    * (0.7 + max(0, min(100, city.livability)) / 200.0)
                )
                city_growth = max(0, int(round(growth)))
                city.population += city_growth
                total_growth += city_growth
            country.population = max(previous, previous + total_growth)
            self.state.sync_city_population(country)
            if country.population != previous:
                self.state.record(
                    "population_growth",
                    country_id=country.country_id,
                    previous=previous,
                    population=country.population,
                    cities=len(country.cities),
                )

    def update_stability_monthly(self) -> None:
        settings = self.config["stability"]
        for country in self.state.countries.values():
            counts = building_counts(country)
            target = settings["base_target"]
            target -= max(0.0, len(country.buildings) - settings["urbanization_threshold"]) * settings["urbanization_penalty"]
            target -= max(0.0, country.tax_rate - 0.12) * settings["monthly_tax_penalty_factor"]
            if country.days_without_shortage >= 30:
                target += settings["food_security_bonus"]
            else:
                target -= settings["food_shortage_penalty"]
            housing = housing_capacity(country, self.config)
            target -= max(0.0, country.population / 1000.0 - housing) * settings["overcrowding_penalty"]
            for building, bonus in settings["building_bonus"].items():
                target += counts.get(building, 0) * bonus
            target += settings["policy_bonus"].get(country.policy, 0.0)
            if country.cities:
                average_livability = sum(city.livability for city in country.cities) / len(country.cities)
                target += (average_livability - 60.0) * 0.08
            target = max(0.0, min(90.0, target))
            country.stability += (target - country.stability) * settings["convergence"]
            country.stability = max(0.0, min(100.0, country.stability))
            if country.stability < settings["unrest_threshold"]:
                food_loss = country.food * settings["unrest_food_loss_fraction"]
                treasury_loss = country.treasury * settings["unrest_treasury_loss_fraction"]
                country.food = max(0.0, country.food - food_loss)
                country.treasury = max(0.0, country.treasury - treasury_loss)
                self.state.record(
                    "stability_crisis",
                    country_id=country.country_id,
                    stability=round(country.stability, 3),
                    food_loss=round(food_loss, 6),
                    treasury_loss=round(treasury_loss, 6),
                )
            self.state.record(
                "stability_month",
                country_id=country.country_id,
                stability=round(country.stability, 3),
                target=round(target, 3),
                housing=housing,
                population=country.population,
            )

    def update_city_livability_monthly(self) -> None:
        for country in self.state.countries.values():
            for city in country.cities:
                target = city_livability_target(city, country, self.config)
                city.livability += (target - city.livability) * 0.25
                city.livability = max(0.0, min(100.0, city.livability))

    def apply_social_events(self) -> None:
        settings = self.config["social_events"]
        for country in self.state.countries.values():
            capacity = food_capacity(country, self.config)
            if country.treasury >= settings["corruption_threshold"] and self.state.weather.random() < settings["corruption_chance"]:
                loss = country.treasury * settings["corruption_treasury_fraction"]
                country.treasury = max(0.0, country.treasury - loss)
                country.stability = max(0.0, country.stability - settings["corruption_stability_loss"])
                self.state.record(
                    "social_event",
                    country_id=country.country_id,
                    event="court_corruption",
                    treasury_loss=round(loss, 4),
                    stability_loss=settings["corruption_stability_loss"],
                )
            if country.food >= capacity - 2 and self.state.weather.random() < settings["festival_chance"]:
                cost = min(country.treasury, settings["festival_treasury_cost"])
                country.treasury -= cost
                country.stability = min(100.0, country.stability + settings["festival_stability_gain"])
                self.state.record(
                    "social_event",
                    country_id=country.country_id,
                    event="harvest_festival",
                    treasury_cost=round(cost, 4),
                    stability_gain=settings["festival_stability_gain"],
                )
            if country.stability >= 70 and self.state.weather.random() < settings["migration_chance"]:
                growth = max(1, int(country.population * settings["migration_population_fraction"]))
                country.population += growth
                self.state.sync_city_population(country)
                self.state.record(
                    "social_event",
                    country_id=country.country_id,
                    event="craftsmen_migration",
                    population_gain=growth,
                )
