"""City grain stores and capacity-constrained civil routes; no combat rules."""
from __future__ import annotations

import heapq
from collections import deque
from core.access import access_rights
from core.society import food_capacity


def storage_capacities(country, config):
    cities = country.cities
    if not cities:
        return
    storage = config["food_storage"]
    bonuses = {"GRANARY": storage["granary_bonus"], "IRRIGATION": storage["irrigation_bonus"],
               "GREAT_GRANARY": storage["great_granary_bonus"]}
    population = sum(max(1, c.population) for c in cities)
    local = {c.city_id: sum(bonuses.get(country.buildings.get(coord), 0) for coord in c.tiles)
             for c in cities}
    shared = max(0.0, food_capacity(country, config) - sum(local.values()))
    for city in cities:
        city.food_capacity = shared * max(1, city.population) / population + local[city.city_id]


def reconcile_stocks(country, config=None):
    """National food is the aggregate, never an additional pile of grain.

    Legacy saves allocate their existing aggregate once. Existing national actions
    (trade, recruitment, events) debit/credit that same inventory proportionally.
    """
    cities = country.cities
    if not cities:
        return
    if config is not None:
        storage_capacities(country, config)
    if all(city.food_stock is None for city in cities):
        weights = [max(1, city.population) for city in cities]
        total = sum(weights)
        for city, weight in zip(cities, weights):
            city.food_stock = max(0.0, country.food) * weight / total
    else:
        for city in cities:
            if city.food_stock is None:
                city.food_stock = 0.0
        old = sum(city.food_stock for city in cities)
        if old > 1e-12 and abs(old - country.food) > 1e-10:
            factor = max(0.0, country.food) / old
            for city in cities:
                city.food_stock *= factor
        elif old <= 1e-12 and country.food > 0:
            total = sum(max(1, city.population) for city in cities)
            for city in cities:
                city.food_stock = country.food * max(1, city.population) / total


def transfer_city_stock(attacker, defender, city):
    amount = min(max(0.0, city.food_stock or 0.0), defender.food)
    defender.food -= amount
    attacker.food += amount


class Logistics:
    def __init__(self, state):
        self.state = state
        self.cache = {}
        self.signature = None

    def _refresh(self):
        state = self.state
        signature = (id(state.world), tuple(
            (cid, tuple(c.tiles), tuple(sorted(c.buildings.items())), tuple(sorted(getattr(c, "roads", ()))), tuple(c.at_war_with))
            for cid, c in sorted(state.countries.items())),
            tuple((key, p["status"], p["pact"], p["sender"], p["target"])
                  for key, p in sorted(state.pacts.items())))
        if signature != self.signature:
            self.signature = signature
            self.cache = {}
        self.owners = {coord: c.country_id for c in state.countries.values() for coord in c.tiles}
        self.roads = {(int(cell["tile"]["col"]), int(cell["tile"]["row"]))
                      for cell in state.world.road_cells()}
        self.roads.update(coord for c in state.countries.values() for coord in getattr(c, "roads", ()))
        self.roads.update(coord for c in state.countries.values()
                          for coord, building in c.buildings.items() if building == "ROAD")

    def blocked_reason(self, country, source, target):
        """Distinguish a closed border from a genuine water/bridge barrier."""
        previous = {source: None}
        queue = deque([source])
        while queue and target not in previous:
            coord = queue.popleft()
            for neighbor in self.state.world.neighbors(*coord):
                if neighbor in previous:
                    continue
                tile = self.state.world.tile(neighbor)
                if not tile["land"] or (tile["river"] and neighbor not in self.roads):
                    continue
                previous[neighbor] = coord
                queue.append(neighbor)
        if target not in previous:
            return "水域或无桥河道阻断运输", []
        denied = set()
        coord = target
        while coord is not None:
            owner = self.owners.get(coord)
            if owner and not access_rights(self.state, country.country_id, owner)["civil"]:
                denied.add(owner)
            coord = previous[coord]
        names = "、".join(self.state.countries[cid].name for cid in sorted(denied))
        return f"缺少与 {names} 的开放边境或同盟", sorted(denied)

    def routes(self, country):
        self._refresh()
        centers = tuple((c.city_id, c.center) for c in country.cities)
        key = (country.country_id, centers)
        if key in self.cache:
            return self.cache[key]
        rules = self.state.config["transport"]
        result = []
        cities = sorted(country.cities, key=lambda c: c.city_id)
        rights = {owner: access_rights(self.state, country.country_id, owner)["civil"]
                  for owner in self.state.countries}
        for index, source in enumerate(cities):
            targets = {c.center for c in cities[index+1:]}
            costs, previous = {source.center: 0.0}, {}
            queue = [(0.0, source.center)]
            while queue and targets:
                cost, coord = heapq.heappop(queue)
                if cost > costs[coord] + 1e-9:
                    continue
                targets.discard(coord)
                if not targets:
                    break
                for neighbor in self.state.world.neighbors(*coord):
                    tile = self.state.world.tile(neighbor)
                    owner = self.owners.get(neighbor)
                    if not tile["land"] or (tile["river"] and neighbor not in self.roads):
                        continue
                    if owner and owner != country.country_id and not rights[owner]:
                        continue
                    step = rules["road_cost"] if neighbor in self.roads else 1.0
                    value = cost + step
                    if value < costs.get(neighbor, float("inf")) - 1e-9:
                        costs[neighbor], previous[neighbor] = value, coord
                        heapq.heappush(queue, (value, neighbor))
            for target in cities[index+1:]:
                path = []
                if target.center in costs:
                    path = [target.center]
                    while path[-1] != source.center:
                        path.append(previous[path[-1]])
                    path.reverse()
                edges = list(zip(path, path[1:]))
                capacity = min((rules["road_capacity"] if a in self.roads and b in self.roads
                                else rules["land_capacity"] for a, b in edges), default=0.0)
                # Endpoint costs must be symmetric for a bidirectional civil route.
                distance = sum((rules["road_cost"] if a in self.roads else 1.0)
                               + (rules["road_cost"] if b in self.roads else 1.0)
                               for a, b in edges) / 2
                reason, denied = ("可运输", []) if path else self.blocked_reason(country, source.center, target.center)
                result.append({"source": source.city_id, "target": target.city_id,
                    "path": [list(c) for c in path], "cost": round(distance, 4),
                    "capacity": capacity, "loss_rate": min(rules["max_loss"],
                    rules["base_loss"] + distance * rules["loss_per_cost"]),
                    "status": "connected" if path else "blocked",
                    "reason": reason, "blocked_by": denied})
        self.cache[key] = result
        return result

    def settle(self, country, outputs, rural_output):
        reconcile_stocks(country)
        cities = sorted(country.cities, key=lambda c: c.city_id)
        if not cities:
            return {"shortage": 0.0, "loss": 0.0, "overflow": 0.0}
        rules = self.state.config["transport"]
        previous_shortages = {city.city_id: city.food_unmet for city in cities}
        storage_capacities(country, self.state.config)
        for city in cities:
            city.food_stock += outputs.get(city.city_id, 0.0)
            city.food_imported = city.food_exported = city.food_loss = 0.0
            city.food_unmet = city.food_need
            city.logistics_status = "本地供给"
            city.logistics_routes = []
        cities[0].food_stock += rural_output
        # Eat local stocks first; disconnected cities cannot eat a distant national total.
        for city in cities:
            eaten = min(city.food_stock, city.food_unmet)
            city.food_stock -= eaten
            city.food_unmet -= eaten
        by_id = {c.city_id: c for c in cities}
        routes = sorted(self.routes(country), key=lambda r: (r["cost"], r["source"], r["target"]))
        edge_used = {}
        for emergency in (True, False):
            for route in routes:
                if route["status"] != "connected":
                    continue
                for source_id, target_id in ((route["source"], route["target"]),
                                             (route["target"], route["source"])):
                    source, target = by_id[source_id], by_id[target_id]
                    reserve = 0.0 if emergency else source.food_need * rules["reserve_days"]
                    available = max(0.0, source.food_stock - reserve)
                    wanted = target.food_unmet if emergency else max(0.0,
                        min(target.food_capacity, target.food_need * rules["reserve_days"]) - target.food_stock)
                    edges = [tuple(sorted((tuple(a), tuple(b)))) for a, b in zip(route["path"], route["path"][1:])]
                    room = min((route["capacity"] - edge_used.get(edge, 0.0) for edge in edges), default=0.0)
                    sent = min(available, wanted / (1 - route["loss_rate"]), max(0.0, room))
                    if sent <= 1e-12:
                        continue
                    received = sent * (1 - route["loss_rate"])
                    source.food_stock -= sent
                    target.food_stock += received
                    source.food_exported += sent
                    target.food_imported += received
                    source.food_loss += sent - received
                    for edge in edges:
                        edge_used[edge] = edge_used.get(edge, 0.0) + sent
                    eaten = min(target.food_stock, target.food_unmet)
                    target.food_stock -= eaten
                    target.food_unmet -= eaten
        for city in cities:
            city.logistics_routes = [dict(r) for r in routes if city.city_id in (r["source"], r["target"])]
            connected = any(r["status"] == "connected" for r in city.logistics_routes)
            if city.food_unmet > 1e-9:
                city.logistics_status = "运力不足或全国缺粮" if connected else "运输中断：本地缺粮"
            elif city.food_imported > 1e-9:
                city.logistics_status = "调入粮食"
            elif len(cities) > 1 and not connected:
                city.logistics_status = "与其他城市隔离"
            elif city.food_exported > 1e-9:
                city.logistics_status = "输出粮食"
            if city.food_unmet > 1e-9 and previous_shortages[city.city_id] <= 1e-9:
                self.state.record("city_supply_shortage", country_id=country.country_id,
                    city_id=city.city_id, city_name=city.name, shortage=city.food_unmet,
                    reason=city.logistics_status)
            elif city.food_unmet <= 1e-9 and previous_shortages[city.city_id] > 1e-9:
                self.state.record("city_supply_restored", country_id=country.country_id,
                    city_id=city.city_id, city_name=city.name)
        overflow = sum(max(0.0, city.food_stock - city.food_capacity) for city in cities)
        for city in cities:
            city.food_stock = min(city.food_capacity, max(0.0, city.food_stock))
        country.food = sum(city.food_stock for city in cities)
        return {"shortage": sum(city.food_unmet for city in cities),
                "loss": sum(city.food_loss for city in cities), "overflow": overflow}
