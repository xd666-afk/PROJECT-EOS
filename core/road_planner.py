"""Read-only road route quotations and atomic, sequential route queues."""
from heapq import heappop, heappush
from math import ceil

from core.actions import ActionRejected
from core.road import built_roads, road_connection_status, road_permit, road_quote


def plan(state, country, start, end):
    start, end = tuple(start), tuple(end)
    for p in (start, end):
        if p not in country.tiles:
            raise ActionRejected("TILE_NOT_OWNED", "道路起终点都必须位于本国领土")
        if state.world.tile(p).get("river"):
            raise ActionRejected("ROAD_NEEDS_BANK", "跨河路线必须从一侧陆地规划到另一侧陆地")
    if start == end:
        raise ActionRejected("ROAD_SAME_ENDPOINT", "请选择不同的起点和终点")
    existing = built_roads(country) | {tuple(c.center) for c in country.cities}
    existing |= {(int(c["tile"]["col"]), int(c["tile"]["row"])) for c in state.world.road_cells()}
    pending = {tuple(p["tile"]): p for p in country.projects if p["building"] == "ROAD"}
    if start not in existing and start not in pending and not road_connection_status(state, country, start)[0]:
        raise ActionRejected("ROAD_NOT_CONNECTED", "起点需要接入本国城市、道路或已规划道路")
    owned = set(country.tiles)
    allowed = {}
    for p in owned:
        # Existing infrastructure is grandfathered; new segments need current permits.
        allowed[p] = None if p in existing or p in pending else road_permit(state, country, p)
        if p not in existing and p not in pending and allowed[p] is None:
            denied = road_connection_status(state, country, p)[1]
            if denied:
                allowed[p] = ("ROAD_DIPLOMACY_REQUIRED", "临近外国路网需要友好关系：" + "、".join(denied))
    if allowed[start]:
        raise ActionRejected(*allowed[start])
    limit = state.config["road_rules"]["modern_bridge_width"] if "modern_engineering" in country.known_techs else state.config["road_rules"]["ancient_bridge_width"]
    first = (start, 0)
    distance, previous = {first: 0.0}, {first: None}
    queue = [(0.0, first)]
    final = None
    while queue:
        cost, key = heappop(queue)
        if cost != distance[key]:
            continue
        p, river_run = key
        if p == end:
            final = key
            break
        for neighbor in sorted(state.world.neighbors(*p)):
            if neighbor not in allowed or allowed[neighbor]:
                continue
            run = river_run + 1 if state.world.tile(neighbor).get("river") and neighbor not in existing else 0
            if run > limit:
                continue
            next_key = neighbor, run
            step = .01 if neighbor in existing or neighbor in pending else road_quote(state, country, neighbor)[0]
            candidate = cost + step
            if candidate < distance.get(next_key, float("inf")):
                distance[next_key], previous[next_key] = candidate, key
                heappush(queue, (candidate, next_key))
    if final is None:
        blocked = {}
        for result in allowed.values():
            if result:
                blocked[result[0]] = result[1]
        raise ActionRejected("ROAD_NO_ROUTE", "本国境内没有符合修筑许可的连通路线。" + "；".join(sorted(blocked.values())))
    path = []
    while final is not None:
        path.append(final[0])
        final = previous[final]
    path.reverse()
    if len(path) > 256:
        raise ActionRejected("ROAD_ROUTE_TOO_LONG", "单次最多规划 256 格，请分段规划")
    segments, total, days = [], 0.0, 0.0
    for p in path:
        if p in existing or p in pending:
            continue
        connected, denied, _ = road_connection_status(state, country, p)
        if denied:
            raise ActionRejected("ROAD_DIPLOMACY_REQUIRED", "临近外国路网需要先达到友好关系：" + "、".join(denied))
        cost, duration = road_quote(state, country, p)
        segments.append({"tile": list(p), "cost": cost, "days": duration})
        total += cost
        days += duration
    baseline = state.config["workers_baseline"]["construction"]
    progress = country.workers["construction"] / baseline * state.config["policies"][country.policy]["construction"]
    return {"path": [list(p) for p in path], "segments": segments, "cost": round(total, 4),
            "work_days": round(days, 4), "estimated_days": sum(ceil(s["days"] / progress) for s in segments) if progress > 0 else None,
            "affordable": country.treasury + 1e-9 >= total,
            "bridge_limit": limit, "pending_tiles": [list(p) for p in pending if p in path]}


def enqueue(state, country, quote):
    if not quote["segments"]:
        raise ActionRejected("ROAD_EXISTS", "这段路线已经修通或已在队列中")
    if not quote["affordable"]:
        raise ActionRejected("INSUFFICIENT_TREASURY", f"整段路线需要 {quote['cost']} 财政单位")
    country.treasury -= quote["cost"]
    route_id = f"R{state.next_project_number:06d}"
    segments = {tuple(s["tile"]): s for s in quote["segments"]}
    pending = {tuple(p["tile"]): p["project_id"] for p in country.projects if p["building"] == "ROAD"}
    dependency = None
    for coord in map(tuple, quote["path"]):
        if coord in pending:
            dependency = pending[coord]
        if coord not in segments:
            continue
        segment = segments[coord]
        project_id = f"P{state.next_project_number:06d}"
        state.next_project_number += 1
        country.projects.append({"project_id": project_id, "tile": coord, "building": "ROAD",
                                 "remaining_days": segment["days"], "total_days": segment["days"],
                                 "cost": segment["cost"], "started_day": state.day_index,
                                 "route_id": route_id, "depends_on": dependency})
        dependency = project_id
    state.record("road_route_planned", country_id=country.country_id, route_id=route_id,
                 path=quote["path"], cost=quote["cost"], segments=len(segments))
    return {"route_id": route_id, **quote}
