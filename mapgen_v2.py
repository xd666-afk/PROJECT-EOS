"""V2 map generation: continuous terrain first, then fine hex-cell entities.

The v1 generator remains available for the fixed baseline and old saves. V2 keeps
all fields needed by GameState, but adds river depth and occupied road cells.
"""
from __future__ import annotations

import heapq
import json
import math
from collections import Counter, deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter, minimum_filter

import mapgen
import worldgen
from worldgen import CELL_AREA_KM2 as V1_CELL_AREA_KM2

BASE_DIR = Path(__file__).resolve().parent
V2_WIDTH = 144
V2_HEIGHT = 108
V2_RADIUS_KM = 17.0
V2_CELL_AREA_KM2 = (3 * math.sqrt(3) / 2) * V2_RADIUS_KM ** 2
CONTINUOUS_SCALE = 4
CONTINUOUS_WIDTH = V2_WIDTH * CONTINUOUS_SCALE
CONTINUOUS_HEIGHT = V2_HEIGHT * CONTINUOUS_SCALE
CONTINUOUS_RADIUS_KM = V2_RADIUS_KM / CONTINUOUS_SCALE
CONTINUOUS_CELL_AREA_KM2 = (3 * math.sqrt(3) / 2) * CONTINUOUS_RADIUS_KM ** 2
CONTINUOUS_RIVER_MIN_BASIN = max(1, round(17 * V1_CELL_AREA_KM2 / CONTINUOUS_CELL_AREA_KM2))
V2_RIVER_MIN_BASIN = max(1, round(17 * V1_CELL_AREA_KM2 / V2_CELL_AREA_KM2))
DEPTH_STOPS = [
    [0.3, "#b9e6ed"],
    [1.2, "#83cfdd"],
    [2.5, "#54a8c0"],
    [4.5, "#337f9d"],
    [7.0, "#205c79"],
    [10.0, "#153e57"],
]


def _blocks(field: np.ndarray):
    for y in range(V2_HEIGHT):
        for x in range(V2_WIDTH):
            y0 = y * CONTINUOUS_SCALE
            y1 = (y + 1) * CONTINUOUS_SCALE
            x0 = x * CONTINUOUS_SCALE
            x1 = (x + 1) * CONTINUOUS_SCALE
            if field.ndim == 3:
                yield x, y, field[:, y0:y1, x0:x1]
            else:
                yield x, y, field[y0:y1, x0:x1]


def _mean(value: np.ndarray) -> float:
    return float(np.mean(value)) if value.size else 0.0


def _dominant(values: np.ndarray, fallback: str) -> str:
    values = [str(item) for item in values.ravel() if str(item) != "ocean"]
    if not values:
        return fallback
    return Counter(values).most_common(1)[0][0]


# --- hydrology geometry -----------------------------------------------------
# Rivers are still hex entities, but their cell paths are shaped as meandering
# walks instead of raw flow-accumulation blobs. A reach is a chain of cells
# between two junctions/outlets: each reach is replaced by a curved walk with a
# sine offset, so bends survive at hex resolution.

HEX_SQRT3 = math.sqrt(3.0)


def _hex_center(col: int, row: int) -> tuple[float, float]:
    return HEX_SQRT3 * (col + .5 * (row & 1)), 1.5 * row


def _offset_to_cube(col: int, row: int) -> tuple[int, int, int]:
    q = col - (row - (row & 1)) // 2
    return q, row, -q - row


def _cube_round(q: float, r: float, s: float) -> tuple[int, int]:
    rq, rr, rs = round(q), round(r), round(s)
    dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    else:
        rs = -rq - rr
    return int(rq), int(rr)


def _cube_to_offset(q: int, r: int) -> tuple[int, int]:
    return q + (r - (r & 1)) // 2, r


def _pixel_to_hex(x: float, y: float) -> tuple[int, int]:
    r = 2.0 * y / 3.0
    q = x / HEX_SQRT3 - y / 3.0
    qr, rr = _cube_round(q, r, -q - r)
    return _cube_to_offset(qr, rr)


def _hex_line(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    q1, r1, s1 = _offset_to_cube(*start)
    q2, r2, s2 = _offset_to_cube(*end)
    steps = max(abs(q1 - q2), abs(r1 - r2), abs(s1 - s2))
    if steps == 0:
        return [start]
    path = []
    for index in range(steps + 1):
        t = index / steps
        q, r, s = q1 + (q2 - q1) * t, r1 + (r2 - r1) * t, s1 + (s2 - s1) * t
        qr, rr = _cube_round(q, r, s)
        path.append(_cube_to_offset(qr, rr))
    return path


def _chaikin(points: list[tuple[float, float]], iterations: int = 2) -> list[tuple[float, float]]:
    for _ in range(iterations):
        if len(points) < 2:
            return points
        smoothed = [points[0]]
        for first, second in zip(points, points[1:]):
            smoothed.append((
                .75 * first[0] + .25 * second[0],
                .75 * first[1] + .25 * second[1],
            ))
            smoothed.append((
                .25 * first[0] + .75 * second[0],
                .25 * first[1] + .75 * second[1],
            ))
        smoothed.append(points[-1])
        points = smoothed
    return points


def _resample(points: list[tuple[float, float]], step: float) -> list[tuple[float, float, float]]:
    """Return (arc_length, x, y) samples at roughly even spacing."""
    lengths = [0.0]
    for first, second in zip(points, points[1:]):
        lengths.append(lengths[-1] + math.hypot(second[0] - first[0], second[1] - first[1]))
    total = lengths[-1]
    if total <= 0:
        return [(0.0, points[0][0], points[0][1])]
    count = max(2, int(math.ceil(total / max(step, .05))))
    samples = []
    cursor = 0
    for index in range(count + 1):
        target = total * index / count
        while cursor < len(lengths) - 2 and lengths[cursor + 1] < target:
            cursor += 1
        span = lengths[cursor + 1] - lengths[cursor]
        local = 0.0 if span <= 0 else (target - lengths[cursor]) / span
        x = points[cursor][0] + (points[cursor + 1][0] - points[cursor][0]) * local
        y = points[cursor][1] + (points[cursor + 1][1] - points[cursor][1]) * local
        samples.append((target, x, y))
    return samples


def _offset_curve(
    samples: list[tuple[float, float, float]],
    total: float,
    amplitude: float,
    wavelength: float,
    phase: float,
) -> list[tuple[float, float]]:
    curve = []
    for index, (arc, x, y) in enumerate(samples):
        before = samples[max(0, index - 1)]
        after = samples[min(len(samples) - 1, index + 1)]
        tx, ty = after[1] - before[1], after[2] - before[2]
        norm = math.hypot(tx, ty) or 1.0
        tx, ty = tx / norm, ty / norm
        envelope = math.sin(math.pi * min(1.0, max(0.0, arc / max(total, 1e-6)))) ** .42
        wave = (
            math.sin(2 * math.pi * arc / max(wavelength, 1.0) + phase)
            + .34 * math.sin(2 * math.pi * arc / max(wavelength * .47, 1.0) + phase * 1.8)
        )
        offset = amplitude * envelope * wave
        curve.append((x - ty * offset, y + tx * offset))
    curve[0] = (samples[0][1], samples[0][2])
    curve[-1] = (samples[-1][1], samples[-1][2])
    return curve


def _curve_to_cells(
    curve: list[tuple[float, float]],
    original: list[tuple[int, int]],
    land_ok,
    elev: np.ndarray,
    max_base_elev: float,
    max_climb: float = 190.0,
) -> list[tuple[int, int]] | None:
    height, width = elev.shape
    raw = [_pixel_to_hex(x, y) for x, y in curve]
    raw[0], raw[-1] = original[0], original[-1]
    path: list[tuple[int, int]] = [raw[0]]

    def permitted(cell: tuple[int, int]) -> bool:
        x, y = cell
        return 0 <= x < width and 0 <= y < height and land_ok(x, y) and float(elev[y, x]) <= max_base_elev + 110

    if not all(permitted(cell) for cell in raw):
        return None
    path_set = {path[0]}
    for cell in raw[1:]:
        if cell == path[-1]:
            continue
        previous = path[-1]
        for nxt in _hex_line(previous, cell)[1:]:
            if not permitted(nxt):
                return None
            if abs(float(elev[nxt[1], nxt[0]]) - float(elev[previous[1], previous[0]])) > max_climb:
                return None
            # Keep the channel one cell wide: reject tight folds that would make
            # the water two cells thick, while allowing ordinary hex bends.
            touching = sum(
                1 for neighbor in worldgen.neighbors(nxt[0], nxt[1], width, height)
                if neighbor in path_set and neighbor != previous
            )
            if touching > 1:
                return None
            path.append(nxt)
            path_set.add(nxt)
            previous = nxt
    if path[0] != original[0] or path[-1] != original[-1]:
        return None
    if len(set(path)) != len(path):
        return None
    if len(path) > max(len(original) * 2.8, len(original) + 14):
        return None
    return path


def _meander_reach(
    cells: list[tuple[int, int]],
    elev: np.ndarray,
    land_ok,
    amplitude: float,
    wavelength: float,
    phase: float,
) -> list[tuple[int, int]] | None:
    if len(cells) < 5:
        return None
    points = [_hex_center(*cell) for cell in cells]
    smoothed = _chaikin(points, 2)
    lengths = [0.0]
    for first, second in zip(smoothed, smoothed[1:]):
        lengths.append(lengths[-1] + math.hypot(second[0] - first[0], second[1] - first[1]))
    total = lengths[-1]
    if total < 2.0:
        return None
    samples = _resample(smoothed, .38)
    max_base_elev = max(float(elev[y, x]) for x, y in cells)
    for factor in (1.0, .78, .56, .36, .2):
        curve = _offset_curve(samples, total, amplitude * factor, wavelength, phase)
        candidate = _curve_to_cells(curve, cells, land_ok, elev, max_base_elev)
        if candidate:
            return candidate
    return None


def _hex_zone(
    cells: set[tuple[int, int]],
    radius: int,
    width: int,
    height: int,
) -> set[tuple[int, int]]:
    zone = set(cells)
    frontier = set(cells)
    for _ in range(max(0, radius)):
        following = set()
        for x, y in frontier:
            for nx, ny in worldgen.neighbors(x, y, width, height):
                if (nx, ny) not in zone:
                    following.add((nx, ny))
        zone |= following
        frontier = following
    return zone


def _river_reaches(
    mask: np.ndarray,
    parent: np.ndarray,
    width: int,
    height: int,
) -> list[list[tuple[int, int]]]:
    cells = [(x, y) for y in range(height) for x in range(width) if mask[y, x]]
    if not cells:
        return []
    cellset = set(cells)
    downstream: dict[tuple[int, int], tuple[int, int] | None] = {}
    upstream: dict[tuple[int, int], list[tuple[int, int]]] = {cell: [] for cell in cells}
    for x, y in cells:
        px, py = int(parent[y, x][0]), int(parent[y, x][1])
        destination = (px, py) if px >= 0 and (px, py) in cellset else None
        downstream[(x, y)] = destination
        if destination:
            upstream[destination].append((x, y))
    special = {
        cell for cell in cells
        if len(upstream[cell]) != 1 or downstream[cell] is None
    }
    reaches = []
    seen_edges = set()
    for start in special:
        destination = downstream[start]
        if destination is None:
            continue
        reach = [start]
        current = start
        while True:
            nxt = downstream[current]
            if nxt is None or (current, nxt) in seen_edges:
                break
            seen_edges.add((current, nxt))
            reach.append(nxt)
            current = nxt
            if current in special:
                break
        if len(reach) >= 2:
            reaches.append(reach)
    return reaches


def _road_path(
    start: tuple[int, int],
    end: tuple[int, int],
    land: np.ndarray,
    elev: np.ndarray,
    river: np.ndarray,
) -> list[tuple[int, int]] | None:
    height, width = land.shape
    heap = [(0.0, start)]
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    costs = {start: 0.0}
    while heap:
        cost, current = heapq.heappop(heap)
        if current == end:
            break
        if cost > costs.get(current, float("inf")):
            continue
        x, y = current
        for nx, ny in worldgen.neighbors(x, y, width, height):
            if not land[ny, nx]:
                continue
            step = 1.0 + abs(float(elev[ny, nx] - elev[y, x])) / 260.0
            if river[ny, nx]:
                step += 3.5
            new_cost = cost + step
            if new_cost < costs.get((nx, ny), float("inf")):
                costs[(nx, ny)] = new_cost
                previous[(nx, ny)] = current
                heapq.heappush(heap, (new_cost, (nx, ny)))
    if end not in previous:
        return None
    path = []
    current: tuple[int, int] | None = end
    while current is not None:
        path.append(current)
        current = previous[current]
    return list(reversed(path))


def _build_roads(
    polities: list[dict[str, Any]],
    land: np.ndarray,
    elev: np.ndarray,
    river: np.ndarray,
) -> list[dict[str, Any]]:
    """Connect capitals through a real, cost-aware road network on the raster."""
    capitals = [
        (int(polity["capital"]["col"]), int(polity["capital"]["row"]), polity["id"])
        for polity in polities
    ]
    if len(capitals) < 2:
        return []
    edges = []
    for index, left in enumerate(capitals):
        for right in capitals[index + 1:]:
            distance = worldgen.hex_distance(left[:2], right[:2])
            edges.append((distance, left, right))
    edges.sort(key=lambda item: item[0])
    parent = {cid: cid for _, _, cid in capitals}

    def find(cid: str) -> str:
        while parent[cid] != cid:
            parent[cid] = parent[parent[cid]]
            cid = parent[cid]
        return cid

    raw_paths: list[dict[str, Any]] = []
    for _, left, right in edges:
        left_id, right_id = left[2], right[2]
        if find(left_id) == find(right_id):
            continue
        parent[find(left_id)] = find(right_id)
        start = (left[0] * CONTINUOUS_SCALE + 1, left[1] * CONTINUOUS_SCALE + 1)
        end = (right[0] * CONTINUOUS_SCALE + 1, right[1] * CONTINUOUS_SCALE + 1)
        path = _road_path(start, end, land, elev, river)
        if not path:
            continue
        network_id = f"RN_{left_id}_{right_id}"
        for x, y in path:
            left_distance = worldgen.hex_distance((x // CONTINUOUS_SCALE, y // CONTINUOUS_SCALE), left[:2])
            right_distance = worldgen.hex_distance((x // CONTINUOUS_SCALE, y // CONTINUOUS_SCALE), right[:2])
            raw_paths.append({
                "x": x, "y": y, "owner_id": left_id if left_distance <= right_distance else right_id,
                "network_id": network_id,
            })
    return raw_paths


def _aggregate_roads(raw_paths: list[dict[str, Any]], river_mask: np.ndarray) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for point in raw_paths:
        key = (point["x"] // CONTINUOUS_SCALE, point["y"] // CONTINUOUS_SCALE)
        grouped.setdefault(key, []).append(point)
    cells = []
    for (col, row), points in grouped.items():
        cells.append({
            "id": f"RD{col:03d}{row:03d}",
            "network_id": Counter(point["network_id"] for point in points).most_common(1)[0][0],
            "tile": {"col": col, "row": row},
            "kind": "bridge" if any(river_mask[point["y"], point["x"]] for point in points) else "road",
            "owner_id": Counter(point["owner_id"] for point in points).most_common(1)[0][0],
        })
    return sorted(cells, key=lambda cell: (cell["tile"]["row"], cell["tile"]["col"]))


def _split_road_networks(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_network: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        by_network.setdefault(cell["network_id"], []).append(cell)
    result = []
    for network_id, members in by_network.items():
        coords = {(cell["tile"]["col"], cell["tile"]["row"]): cell for cell in members}
        remaining = set(coords)
        part = 0
        while remaining:
            start = next(iter(remaining))
            queue = deque([start])
            component = {start}
            remaining.remove(start)
            while queue:
                current = queue.popleft()
                for neighbor in worldgen.neighbors(*current, V2_WIDTH, V2_HEIGHT):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        queue.append(neighbor)
            part += 1
            for coord in component:
                cell = dict(coords[coord])
                cell["network_id"] = network_id if part == 1 else f"{network_id}_{part}"
                result.append(cell)
    return result


def _terrain_texture(
    elev: np.ndarray,
    land: np.ndarray,
    biome: np.ndarray,
    precip: np.ndarray,
    temp: np.ndarray,
    seed: int,
) -> Path:
    """Render the continuous terrain once, before hex quantization."""
    palette = {
        "desert": (192, 162, 108),
        "alpine": (112, 120, 116),
        "tundra": (135, 148, 127),
        "forest": (50, 105, 70),
        "rainforest": (36, 92, 64),
        "wetland": (76, 130, 115),
        "steppe": (150, 140, 92),
        "savanna": (140, 152, 82),
        "grassland": (104, 145, 86),
    }
    height, width = elev.shape
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    gy, gx = np.gradient(elev)
    shade = np.clip(1.0 - gx * 0.0018 - gy * 0.0008, .72, 1.22)
    for y in range(height):
        for x in range(width):
            if not land[y, x]:
                depth = np.clip(-float(elev[y, x]) / 1400.0, 0, 1)
                base = np.array([35, 89, 112], dtype=np.float32) * (1 - depth) + np.array([7, 30, 45], dtype=np.float32) * depth
                rgb[y, x] = base
                continue
            base = np.array(palette.get(str(biome[y, x]), palette["grassland"]), dtype=np.float32)
            dry = 1 - min(1.0, float(precip[y, x]) / 1200.0)
            base = base * (1 - dry * .25) + np.array([125, 100, 70], dtype=np.float32) * (dry * .25)
            base = base * (1 - min(1.0, max(0.0, float(elev[y, x])) / 3000.0) * .22) + np.array([180, 184, 172], dtype=np.float32) * (min(1.0, max(0.0, float(elev[y, x])) / 3000.0) * .22)
            rgb[y, x] = base * shade[y, x]
    path = BASE_DIR / "runs" / "worlds" / f"world_v2_custom_{seed}_terrain.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    image = image.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
    image.save(path, optimize=True)
    return path


def _generate_candidate(seed: int, countries: list[dict[str, Any]]) -> dict[str, Any]:
    rng, X, Y, lat, land, elev, fault, ridge = worldgen.gen_base(
        seed, CONTINUOUS_WIDTH, CONTINUOUS_HEIGHT
    )
    p, tmean, monthly_temp, monthly_rain, biome, dist_ocean = worldgen.gen_climate(
        rng, lat, land, elev, CONTINUOUS_WIDTH, CONTINUOUS_HEIGHT, CONTINUOUS_RADIUS_KM
    )
    parent, flow, basin, river, slope = worldgen.gen_hydrology(
        land, elev, p,
        CONTINUOUS_WIDTH, CONTINUOUS_HEIGHT,
        CONTINUOUS_RADIUS_KM, CONTINUOUS_CELL_AREA_KM2,
        CONTINUOUS_RIVER_MIN_BASIN,
    )
    hazards = worldgen.gen_hazards(
        land, elev, fault, biome, p, tmean, lat, river, basin, slope, dist_ocean,
        CONTINUOUS_WIDTH, CONTINUOUS_HEIGHT, CONTINUOUS_RADIUS_KM,
    )

    aggregated: dict[tuple[int, int], dict[str, Any]] = {}
    for x, y, block in _blocks(land):
        land_cell = bool(block.sum() >= (CONTINUOUS_SCALE ** 2) / 2)
        aggregated[(x, y)] = {"land": land_cell}
    for x, y, block in _blocks(elev):
        aggregated[(x, y)]["elevation_m"] = _mean(block)
    for x, y, block in _blocks(p):
        aggregated[(x, y)]["annual_precip_mm"] = _mean(block)
    for x, y, block in _blocks(tmean):
        aggregated[(x, y)]["annual_mean_temp_c"] = _mean(block)
    for x, y, block in _blocks(monthly_temp):
        aggregated[(x, y)]["monthly_temp_c"] = [
            float(value) for value in block.mean(axis=(1, 2))
        ]
    for x, y, block in _blocks(monthly_rain):
        aggregated[(x, y)]["monthly_precip_mm"] = [
            float(value) for value in block.mean(axis=(1, 2))
        ]
    for x, y, block in _blocks(biome):
        aggregated[(x, y)]["biome"] = _dominant(block, "ocean" if not aggregated[(x, y)]["land"] else "grassland")
    for key in hazards:
        for x, y, block in _blocks(hazards[key]):
            aggregated[(x, y)][key] = _mean(block)
    for x, y, block in _blocks(river):
        aggregated[(x, y)]["river_count"] = int(block.sum())
    for x, y, block in _blocks(flow):
        aggregated[(x, y)]["flow"] = float(block.max()) if block.size else 0.0
    for x, y, block in _blocks(basin):
        aggregated[(x, y)]["basin"] = int(block.max()) if block.size else 0

    v2_elev = np.array([
        [aggregated[(x, y)]["elevation_m"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    v2_land = np.array([
        [aggregated[(x, y)]["land"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    v2_parent, _, _, _, v2_slope = worldgen.gen_hydrology(
        v2_land, v2_elev,
        np.array([[aggregated[(x, y)]["annual_precip_mm"] for x in range(V2_WIDTH)] for y in range(V2_HEIGHT)]),
        V2_WIDTH, V2_HEIGHT, V2_RADIUS_KM, V2_CELL_AREA_KM2,
    )

    polity_p = np.array([
        [aggregated[(x, y)]["annual_precip_mm"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    river_count = np.array([
        [aggregated[(x, y)].get("river_count", 0) for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    lake_mask, lakes = _find_inland_lakes(v2_land, v2_elev, polity_p, V2_WIDTH, V2_HEIGHT)
    hydro_parent, by_lake, _ = _endorheic_catchments(
        v2_land, v2_elev, lake_mask, lakes, v2_parent, V2_WIDTH, V2_HEIGHT
    )
    v2_basin, v2_flow = _recompute_accumulation(
        v2_land, lake_mask, hydro_parent, polity_p, V2_WIDTH, V2_HEIGHT
    )
    terminus = _terminal_lakes(
        v2_land, lake_mask, hydro_parent, lakes, V2_WIDTH, V2_HEIGHT
    )
    polity_land = v2_land & ~lake_mask
    polity_river, river_meta, max_river_basin = _shape_rivers(
        v2_land, lake_mask, v2_elev, hydro_parent, v2_basin, v2_flow,
        by_lake, terminus, river_count, V2_WIDTH, V2_HEIGHT, seed,
    )
    polity_biome = np.array([
        [aggregated[(x, y)]["biome"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ], dtype=object)
    polity_tmean = np.array([
        [aggregated[(x, y)]["annual_mean_temp_c"] for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    polity_basin = v2_basin
    polity_hazards = {
        key: np.array([
            [aggregated[(x, y)][key] for x in range(V2_WIDTH)]
            for y in range(V2_HEIGHT)
        ])
        for key in hazards
    }
    polity_lat = np.array([
        [float(lat[y * CONTINUOUS_SCALE, x * CONTINUOUS_SCALE]) for x in range(V2_WIDTH)]
        for y in range(V2_HEIGHT)
    ])
    polity_dist_ocean = worldgen.distance_transform_edt(polity_land) * V2_RADIUS_KM * 1.7
    capitals = mapgen._place_capitals(
        countries, polity_land, v2_elev, polity_biome, polity_p, polity_tmean,
        polity_river, polity_basin, v2_slope, polity_dist_ocean,
        polity_hazards, polity_lat, V2_WIDTH, V2_HEIGHT, True, polity_river,
    )
    available = polity_land.copy()
    ownership, territories = mapgen._grow_equal_territories(
        capitals, polity_land, available, V2_WIDTH, V2_HEIGHT
    )
    if any(len(cells) < mapgen.CORE_TILES for cells in territories):
        raise RuntimeError("v2 map cannot provide equal connected cores")
    fairness = mapgen._fairness(
        countries, territories, v2_elev, polity_p, polity_biome,
        polity_river, polity_hazards,
    )

    polities = []
    ids = mapgen.country_ids(len(countries))
    for index, (country, capital, cells) in enumerate(zip(countries, capitals, territories)):
        x0, y0 = capital
        polities.append({
            "id": ids[index], "name": country["name"], "type": country["archetype"],
            "color": country["color"], "government": mapgen.ARCHETYPES[country["archetype"]],
            "description": f"{mapgen.ARCHETYPES[country['archetype']]}风格的自定义国家",
            "population": country["population"],
            "capital": {"col": x0, "row": y0, "q": x0 - (y0 - (y0 & 1)) // 2, "r": y0},
            "initial_tiles": cells,
            "territorial_area_km2": round(len(cells) * V2_CELL_AREA_KM2, 1),
            "avg_annual_temp_c": round(float(polity_tmean[y0, x0]), 1),
            "avg_annual_precip_mm": round(float(polity_p[y0, x0])),
            "elevation_m": round(float(v2_elev[y0, x0])),
            "river_distance_tiles": round(float(worldgen.distance_transform_edt(~polity_river)[y0, x0]), 1),
            "dominant_biome": str(polity_biome[y0, x0]),
            "technology": {
                "agriculture": 1,
                "bronze_metallurgy": 2 if country["archetype"] == "highland" else 1,
                "writing": 1 if country["archetype"] in {"river_valley", "semiarid"} else 0,
            },
            "treasury_units": 100, "food_storage_units": 160, "diplomatic_status": "no_contact",
        })

    raw_roads = _build_roads(polities, land, elev, river)
    road_cells = _split_road_networks([
        cell for cell in _aggregate_roads(raw_roads, river)
        if polity_land[cell["tile"]["row"], cell["tile"]["col"]]
    ])
    for cell in road_cells:
        cell["kind"] = (
            "bridge" if polity_river[cell["tile"]["row"], cell["tile"]["col"]]
            else "road"
        )
    tiles = []
    river_cells = []
    for y in range(V2_HEIGHT):
        for x in range(V2_WIDTH):
            data = aggregated[(x, y)]
            lake = bool(lake_mask[y, x])
            tiles.append({
                "q": x - (y - (y & 1)) // 2, "r": y, "col": x, "row": y,
                "latitude_deg": round(float(polity_lat[y, x]), 2),
                "land": bool(data["land"] and not lake),
                "lake": lake,
                "elevation_m": int(round(data["elevation_m"])),
                "biome": "lake" if lake else str(data["biome"]),
                "annual_mean_temp_c": round(data["annual_mean_temp_c"], 1),
                "annual_precip_mm": int(round(data["annual_precip_mm"])),
                "monthly_temp_c": [round(value, 1) for value in data["monthly_temp_c"]],
                "monthly_precip_mm": [round(value, 1) for value in data["monthly_precip_mm"]],
                "slope": round(float(v2_slope[y, x]), 4),
                "river": bool(polity_river[y, x] and not lake),
                "drainage_area_km2": int(v2_basin[y, x] * V2_CELL_AREA_KM2),
                "downstream": None,
                "hazards": {key: round(float(data[key]), 3) for key in hazards},
                "owner_id": str(ownership[y, x]) or None,
            })
            if polity_river[y, x] and not lake:
                info = river_meta[(x, y)]
                ratio = min(1.0, info["basin"] / max(1, max_river_basin))
                depth = max(0.3, min(12.0, 0.3 + 9.6 * ratio ** 0.55))
                river_cells.append({
                    "id": f"RV{x:03d}{y:03d}",
                    "network_id": None,
                    "tile": {"col": x, "row": y},
                    "depth_m": round(depth, 3),
                    "coverage": round(min(1.0, info["coverage"]) or .15, 3),
                    "flow_m3_per_year": round(info["flow"], 1),
                    "drainage_area_km2": int(info["basin"] * V2_CELL_AREA_KM2),
                    "kind": info["kind"],
                    "terminal_lake_id": info["terminal_lake_id"],
                })
    river_cells = _label_river_networks(river_cells)
    for tile in tiles:
        x, y = tile["col"], tile["row"]
        px, py = hydro_parent[y, x]
        tile["downstream"] = {"col": int(px), "row": int(py)} if tile["land"] and px >= 0 else None

    weather_samples, events = worldgen.demo_weather_hazards(
        seed, polity_land,
        np.array([[aggregated[(x, y)]["monthly_precip_mm"] for x in range(V2_WIDTH)] for y in range(V2_HEIGHT)]).transpose(2, 0, 1),
        np.array([[aggregated[(x, y)]["monthly_temp_c"] for x in range(V2_WIDTH)] for y in range(V2_HEIGHT)]).transpose(2, 0, 1),
        polity_hazards, polities, V2_WIDTH, V2_HEIGHT,
    )
    texture_path = _terrain_texture(elev, land, biome, p, tmean, seed)
    try:
        texture_reference = str(texture_path.relative_to(BASE_DIR)).replace("\\", "/")
    except ValueError:
        texture_reference = str(texture_path)
    world = {
        "metadata": {
            "project": "Project Eos",
            "version": "0.2.0",
            "schema_version": 2,
            "generator": "mapgen_v2",
            "seed": seed,
            "world_year_bce": 2000,
            "astronomical_year": -1999,
            "start_month": 1,
            "day_count": 0,
            "grid_type": "odd-r pointy-top hex",
            "grid_width": V2_WIDTH,
            "grid_height": V2_HEIGHT,
            "hex_radius_km": V2_RADIUS_KM,
            "cell_area_km2": round(V2_CELL_AREA_KM2, 1),
            "assumed_planet": "Earth-like, 24h day, 365-day year, Northern Hemisphere",
            "latitude_range_deg": [8, 51],
            "custom_game": True,
            "terrain_texture": texture_reference,
            "fairness": fairness,
            "core_tiles_per_country": mapgen.CORE_TILES,
            "continuous_grid": {
                "width": CONTINUOUS_WIDTH,
                "height": CONTINUOUS_HEIGHT,
                "resolution_km": CONTINUOUS_RADIUS_KM,
                "sampling": "4x4 block aggregation at hex centers",
            },
            "river_depth_model": "basin_area_proxy_v2; depth is an estimate, not a hydraulic measurement",
            "hydrology_model": "meandering hex reaches + terminal endorheic lakes; closed basins stop at the shore",
        },
        "world_summary": {
            "land_hexes": int(polity_land.sum()),
            "ocean_hexes": int((~v2_land).sum()),
            "lake_hexes": int(lake_mask.sum()),
            "lake_count": len(lakes),
            "land_area_km2": round(float(polity_land.sum() * V2_CELL_AREA_KM2)),
            "lake_area_km2": round(float(lake_mask.sum() * V2_CELL_AREA_KM2)),
            "endorheic_catchment_km2": round(float(sum(len(c) for c in by_lake.values()) * V2_CELL_AREA_KM2)),
            "maximum_elevation_m": round(float(v2_elev.max())),
            "river_hexes": len(river_cells),
            "river_cell_count": len(river_cells),
            "endorheic_river_hexes": sum(1 for cell in river_cells if cell["kind"] == "endorheic"),
            "endorheic_network_count": len({
                cell["network_id"] for cell in river_cells if cell["kind"] == "endorheic"
            }),
            "road_cell_count": len(road_cells),
            "unclaimed_land_hexes": int(np.count_nonzero(polity_land & (ownership == ""))),
        },
        "terrain": {
            "kind": "continuous_raster",
            "width": CONTINUOUS_WIDTH,
            "height": CONTINUOUS_HEIGHT,
            "resolution_km": CONTINUOUS_RADIUS_KM,
            "elevation_m": np.rint(elev).astype(int).tolist(),
            "land": land.tolist(),
        },
        "rendering": {
            "river_depth_stops": DEPTH_STOPS,
            "lake_depth_stops": [
                [1.0, "#93e4e8"],
                [4.0, "#5bc6d1"],
                [8.0, "#319fb2"],
                [12.0, "#1c6b80"],
            ],
            "lake_color": "#4fc0cd",
            "endorheic_tint": "#63c9b4",
            "road_color": "#c6a065",
            "bridge_color": "#88949b",
        },
        "polities": polities,
        "tiles": tiles,
        "river_cells": river_cells,
        "lake_cells": _lake_cells(lakes, v2_elev),
        "road_cells": road_cells,
        "weather_samples": weather_samples,
        "illustrative_hazard_events": events,
    }
    validate_v2(world)
    return world


def _find_inland_lakes(
    land: np.ndarray,
    elev: np.ndarray,
    precip: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Find interior closed depressions and fill them to a natural-looking level."""
    distance = distance_transform_edt(land)
    smooth = gaussian_filter(elev, sigma=2.0)
    bowl_depth = gaussian_filter(elev, sigma=6.0) - elev
    minima = (
        (smooth == minimum_filter(smooth, size=7))
        & land
        & (distance > 14)
        & (elev < 1900)
    )
    scored = []
    for y, x in np.argwhere(minima):
        if not (8 <= x < width - 8 and 8 <= y < height - 8):
            continue
        depth = float(bowl_depth[y, x])
        if depth < .4:
            continue
        dryness = min(1.0, max(0.0, (900.0 - float(precip[y, x])) / 700.0))
        score = float(distance[y, x]) * .35 + depth * 3.0 + dryness * 10.0
        scored.append((score, int(x), int(y)))
    scored.sort(reverse=True)

    chosen: list[tuple[int, int]] = []
    for _, cx, cy in scored:
        if all(worldgen.hex_distance((cx, cy), other) >= 24 for other in chosen):
            chosen.append((cx, cy))
        if len(chosen) >= 4:
            break

    lake_mask = np.zeros_like(land, dtype=bool)
    lakes = []
    for index, (cx, cy) in enumerate(chosen, 1):
        start_elev = float(elev[cy, cx])
        # Prefer the lowest cell within a small radius so the lake sits in the basin.
        lowest = (cx, cy)
        for yy in range(max(0, cy - 2), min(height, cy + 3)):
            for xx in range(max(0, cx - 2), min(width, cx + 3)):
                if land[yy, xx] and land[cy, cx] and float(elev[yy, xx]) < float(elev[lowest[1], lowest[0]]):
                    lowest = (xx, yy)
        start_elev = float(elev[lowest[1], lowest[0]])
        target = 8 + ((cx * 13 + cy * 17) % 10)
        heap = [(0.0, start_elev, lowest[1], lowest[0])]
        seen = {lowest}
        cells: list[tuple[int, int]] = []
        while heap and len(cells) < target:
            _, level, y, x = heapq.heappop(heap)
            if level > start_elev + 34:
                continue
            cells.append((x, y))
            for nx, ny in worldgen.neighbors(x, y, width, height):
                if (nx, ny) in seen or not land[ny, nx] or lake_mask[ny, nx]:
                    continue
                if abs(nx - lowest[0]) > 4 or abs(ny - lowest[1]) > 4:
                    continue
                if not (2 <= nx < width - 2 and 2 <= ny < height - 2):
                    continue
                seen.add((nx, ny))
                ring = worldgen.hex_distance((nx, ny), (lowest[0], lowest[1]))
                rank = ring * 4.5 + max(0.0, float(elev[ny, nx]) - start_elev) / 10.0
                heapq.heappush(heap, (rank, float(elev[ny, nx]), ny, nx))
        if len(cells) < 4:
            continue
        level = max(float(elev[y, x]) for x, y in cells) + .4
        for x, y in cells:
            lake_mask[y, x] = True
        depth = max(1.2, min(12.0, level - start_elev + .9))
        lakes.append({
            "id": f"LK{index:02d}",
            "center": [cx, cy],
            "lowest": [lowest[0], lowest[1]],
            "level_m": round(level, 1),
            "depth_m": round(depth, 2),
            "spill_height_m": 110.0,
            "cells": [[x, y] for x, y in sorted(cells, key=lambda item: (item[1], item[0]))],
        })
    return lake_mask, lakes


def _endorheic_catchments(
    land: np.ndarray,
    elev: np.ndarray,
    lake_mask: np.ndarray,
    lakes: list[dict[str, Any]],
    parent: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, dict[str, list[tuple[int, int]]], dict[tuple[int, int], str]]:
    """Route a closed basin around each lake and stop its rivers at the shore."""
    routed = parent.copy()
    claimed = np.zeros_like(land, dtype=bool)
    by_lake: dict[str, list[tuple[int, int]]] = {}
    cell_lake: dict[tuple[int, int], str] = {}
    for lake in lakes:
        cx, cy = lake["center"]
        level = float(lake["level_m"])
        spill = level + float(lake["spill_height_m"])
        visited = np.zeros_like(land, dtype=bool)
        heap = []
        for x, y in lake["cells"]:
            visited[y, x] = True
            heapq.heappush(heap, (level, y, x))
        catchment: list[tuple[int, int]] = []
        while heap and len(catchment) < 130:
            current_level, y, x = heapq.heappop(heap)
            if not lake_mask[y, x]:
                catchment.append((x, y))
                claimed[y, x] = True
                cell_lake[(x, y)] = lake["id"]
            for nx, ny in worldgen.neighbors(x, y, width, height):
                if visited[ny, nx] or not land[ny, nx] or lake_mask[ny, nx] or claimed[ny, nx]:
                    continue
                if worldgen.hex_distance((nx, ny), (cx, cy)) > 14:
                    continue
                neighbor_elev = float(elev[ny, nx])
                if neighbor_elev > spill:
                    continue
                visited[ny, nx] = True
                routed[ny, nx] = [x, y]
                heapq.heappush(heap, (max(neighbor_elev, current_level) + 1e-4, ny, nx))
        by_lake[lake["id"]] = catchment
        lake["catchment_hexes"] = len(catchment)
        lake["spill_m"] = round(spill, 1)
    for lake in lakes:
        for x, y in lake["cells"]:
            routed[y, x] = [-1, -1]
    return routed, by_lake, cell_lake


def _recompute_accumulation(
    land: np.ndarray,
    lake_mask: np.ndarray,
    parent: np.ndarray,
    precip: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    dry_land = land & ~lake_mask
    basin = np.where(dry_land, 1, 0).astype(int)
    flow = np.where(
        dry_land,
        np.maximum(precip - 310.0, 20.0) / 1000.0 * V2_CELL_AREA_KM2 * 1e6 * .36,
        0.0,
    )
    indegree = np.zeros((height, width), dtype=int)
    for y in range(height):
        for x in range(width):
            if not dry_land[y, x]:
                continue
            px, py = int(parent[y, x][0]), int(parent[y, x][1])
            if px >= 0 and dry_land[py, px]:
                indegree[py, px] += 1
    queue = deque(
        (x, y) for y in range(height) for x in range(width)
        if dry_land[y, x] and indegree[y, x] == 0
    )
    processed = 0
    while queue:
        x, y = queue.popleft()
        processed += 1
        px, py = int(parent[y, x][0]), int(parent[y, x][1])
        if px >= 0 and dry_land[py, px]:
            basin[py, px] += basin[y, x]
            flow[py, px] += flow[y, x]
            indegree[py, px] -= 1
            if indegree[py, px] == 0:
                queue.append((px, py))
    if processed != int(dry_land.sum()):
        raise RuntimeError("v2 hydrology parent graph contains a cycle")
    return basin, flow


def _terminal_lakes(
    land: np.ndarray,
    lake_mask: np.ndarray,
    parent: np.ndarray,
    lakes: list[dict[str, Any]],
    width: int,
    height: int,
) -> dict[tuple[int, int], str]:
    """Map every cell that drains into a closed-basin lake to that lake id."""
    lake_at = {}
    for lake in lakes:
        for x, y in lake["cells"]:
            lake_at[(x, y)] = lake["id"]
    upstream: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for y in range(height):
        for x in range(width):
            if not land[y, x] or lake_mask[y, x]:
                continue
            px, py = int(parent[y, x][0]), int(parent[y, x][1])
            if px >= 0:
                upstream.setdefault((px, py), []).append((x, y))
    terminus: dict[tuple[int, int], str] = {}
    queue = deque()
    for (lx, ly), lake_id in lake_at.items():
        for child in upstream.get((lx, ly), []):
            terminus[child] = lake_id
            queue.append(child)
    while queue:
        cell = queue.popleft()
        lake_id = terminus[cell]
        for child in upstream.get(cell, []):
            if child not in terminus:
                terminus[child] = lake_id
                queue.append(child)
    return terminus


def _shape_rivers(
    land: np.ndarray,
    lake_mask: np.ndarray,
    elev: np.ndarray,
    parent: np.ndarray,
    basin: np.ndarray,
    flow: np.ndarray,
    by_lake: dict[str, list[tuple[int, int]]],
    terminus: dict[tuple[int, int], str],
    river_count: np.ndarray,
    width: int,
    height: int,
    seed: int,
) -> tuple[np.ndarray, dict[tuple[int, int], dict[str, Any]], int]:
    """Build a connected river mask from meandering reaches."""
    base = land & ~lake_mask & (basin >= V2_RIVER_MIN_BASIN)
    for lake_id, catchment in by_lake.items():
        threshold = max(6, round(len(catchment) * .10))
        for x, y in catchment:
            if basin[y, x] >= threshold:
                base[y, x] = True

    coverage = np.where(land, np.clip(river_count / (CONTINUOUS_SCALE ** 2), .08, 1.0), 0.0)
    shaped = np.zeros_like(land, dtype=bool)
    blocked = np.zeros_like(land, dtype=bool)
    meta: dict[tuple[int, int], dict[str, Any]] = {}

    reaches = _river_reaches(base, parent, width, height)
    reaches.sort(
        key=lambda reach: -sum(int(basin[y, x]) for x, y in reach) / len(reach)
    )
    base_cells = {(x, y) for y in range(height) for x in range(width) if base[y, x]}
    for index, reach in enumerate(reaches):
        reach_set = set(reach)
        endpoints = {reach[0], reach[-1]}
        corridor = _hex_zone(reach_set, 3, width, height)
        reserved = _hex_zone(base_cells - reach_set, 1, width, height) - reach_set
        endpoint_zone = _hex_zone(endpoints, 2, width, height)

        def land_ok(x: int, y: int) -> bool:
            if not land[y, x] or lake_mask[y, x]:
                return False
            if (x, y) not in corridor:
                return False
            if (x, y) in reserved and (x, y) not in endpoint_zone:
                return False
            if blocked[y, x] and (x, y) not in endpoint_zone:
                return False
            return True

        average = sum(int(basin[y, x]) for x, y in reach) / len(reach)
        amplitude = .75 + .85 * min(1.0, average / 320.0)
        wavelength = 7.2 + 2.8 * ((seed + index * 37) % 100) / 100.0
        phase = ((seed * 131 + index * 977) % 360) / 180.0 * math.pi
        curved = _meander_reach(reach, elev, land_ok, amplitude, wavelength, phase)
        cells = curved or reach
        for x, y in cells:
            source = min(
                reach,
                key=lambda item: worldgen.hex_distance(item, (x, y)),
            )
            sx, sy = source
            record = meta.get((x, y))
            lake_id = terminus.get((x, y))
            values = {
                "basin": int(basin[sy, sx]),
                "flow": float(flow[sy, sx]),
                "coverage": float(coverage[sy, sx]),
                "kind": "endorheic" if lake_id else "exorheic",
                "terminal_lake_id": lake_id,
            }
            if record is None:
                meta[(x, y)] = values
            else:
                record["basin"] = max(record["basin"], values["basin"])
                record["flow"] = max(record["flow"], values["flow"])
                record["coverage"] = max(record["coverage"], values["coverage"])
                if values["kind"] == "endorheic":
                    record["kind"] = "endorheic"
                    record["terminal_lake_id"] = values["terminal_lake_id"] or record["terminal_lake_id"]
            shaped[y, x] = True
        for x, y in cells:
            blocked[y, x] = True
            for nx, ny in worldgen.neighbors(x, y, width, height):
                blocked[ny, nx] = True
    # Isolated river mouths can be single cells and are not part of a reach.
    for y in range(height):
        for x in range(width):
            if base[y, x] and not shaped[y, x]:
                shaped[y, x] = True
                lake_id = terminus.get((x, y))
                meta[(x, y)] = {
                    "basin": int(basin[y, x]),
                    "flow": float(flow[y, x]),
                    "coverage": float(coverage[y, x]),
                    "kind": "endorheic" if lake_id else "exorheic",
                    "terminal_lake_id": lake_id,
                }
    max_basin = max((item["basin"] for item in meta.values()), default=1)
    return shaped, meta, max_basin


def _label_river_networks(river_cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_coord = {(cell["tile"]["col"], cell["tile"]["row"]): cell for cell in river_cells}
    remaining = set(by_coord)
    components = []
    while remaining:
        start = next(iter(remaining))
        remaining.remove(start)
        queue = deque([start])
        component = [start]
        while queue:
            current = queue.popleft()
            for neighbor in worldgen.neighbors(*current, V2_WIDTH, V2_HEIGHT):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
                    component.append(neighbor)
        components.append(component)
    components.sort(key=len, reverse=True)
    for index, component in enumerate(components, 1):
        for coord in component:
            by_coord[coord]["network_id"] = f"RV{index:02d}"
    return river_cells


def _lake_cells(lakes: list[dict[str, Any]], elev: np.ndarray) -> list[dict[str, Any]]:
    cells = []
    for lake in lakes:
        level = float(lake["level_m"])
        for col, row in lake["cells"]:
            depth = max(.8, min(float(lake["depth_m"]), level - float(elev[row, col]) + .8))
            cells.append({
                "id": f"{lake['id']}-{col:03d}{row:03d}",
                "lake_id": lake["id"],
                "tile": {"col": col, "row": row},
                "depth_m": round(depth, 2),
                "area_km2": round(len(lake["cells"]) * V2_CELL_AREA_KM2, 1),
                "level_m": lake["level_m"],
            })
    return cells


def validate_v2(world: dict[str, Any]) -> bool:
    metadata = world["metadata"]
    width, height = metadata["grid_width"], metadata["grid_height"]
    assert metadata["schema_version"] == 2
    assert len(world["tiles"]) == width * height
    tiles = {(tile["col"], tile["row"]): tile for tile in world["tiles"]}
    summary = world["world_summary"]
    assert summary["land_hexes"] == sum(tile["land"] for tile in world["tiles"])
    assert summary["river_hexes"] == len(world["river_cells"])
    assert summary["river_cell_count"] == len(world["river_cells"])

    lake_cells = world.get("lake_cells", [])
    lake_ids = {cell["lake_id"] for cell in lake_cells}
    lake_coords = {(cell["tile"]["col"], cell["tile"]["row"]) for cell in lake_cells}
    assert summary["lake_hexes"] == len(lake_cells)
    assert summary["lake_count"] == len(lake_ids)
    assert len(lake_coords) == len(lake_cells), "duplicate lake cell"
    for cell in lake_cells:
        coord = (cell["tile"]["col"], cell["tile"]["row"])
        assert tiles[coord]["lake"] and not tiles[coord]["land"]
        assert tiles[coord]["biome"] == "lake"
        assert cell["depth_m"] > 0
        assert cell["lake_id"]
    for tile in world["tiles"]:
        assert bool(tile["lake"]) == ((tile["col"], tile["row"]) in lake_coords)
        if tile["lake"]:
            assert not tile["land"] and not tile["river"]

    all_occupied = set()
    for polity in world["polities"]:
        assert len(polity["initial_tiles"]) == mapgen.CORE_TILES
        capital = (polity["capital"]["col"], polity["capital"]["row"])
        assert capital in {tuple(coord) for coord in polity["initial_tiles"]}
        capital_tile = tiles[capital]
        assert capital_tile["land"] and not capital_tile["river"] and not capital_tile["lake"], (
            "capital must be dry land"
        )
        coords = {tuple(coord) for coord in polity["initial_tiles"]}
        for coord in coords:
            assert coord not in all_occupied
            all_occupied.add(coord)
        seen = {capital}
        queue = deque([capital])
        while queue:
            current = queue.popleft()
            for neighbor in worldgen.neighbors(*current, width, height):
                if neighbor in coords and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        assert seen == coords, "polity core is not connected"

    for tile in world["tiles"]:
        if not tile["land"]:
            continue
        current = tile
        seen = set()
        terminated = False
        for _ in range(width * height):
            key = (current["col"], current["row"])
            assert key not in seen, "v2 drainage loop"
            seen.add(key)
            destination = current["downstream"]
            assert destination is not None, "v2 land has no downstream"
            next_tile = tiles[(destination["col"], destination["row"])]
            assert worldgen.hex_distance(key, (next_tile["col"], next_tile["row"])) == 1
            if next_tile["lake"] or not next_tile["land"]:
                terminated = True
                break
            current = next_tile
        assert terminated, "v2 drainage does not reach ocean or lake"

    river_ids = set()
    river_coords = set()
    for cell in world["river_cells"]:
        assert cell["id"] not in river_ids
        river_ids.add(cell["id"])
        coord = (cell["tile"]["col"], cell["tile"]["row"])
        river_coords.add(coord)
        assert tiles[coord]["land"]
        assert tiles[coord]["river"]
        assert not tiles[coord]["lake"]
        assert cell["depth_m"] > 0
        assert cell["kind"] in {"exorheic", "endorheic"}
        if cell["kind"] == "endorheic":
            assert cell["terminal_lake_id"] in lake_ids
        else:
            assert cell["terminal_lake_id"] is None
    assert len(river_coords) == len(world["river_cells"]), "duplicate river cell"
    for tile in world["tiles"]:
        assert tile["river"] == ((tile["col"], tile["row"]) in river_coords)
    river_networks: dict[str, list[tuple[int, int]]] = {}
    for cell in world["river_cells"]:
        coord = (cell["tile"]["col"], cell["tile"]["row"])
        river_networks.setdefault(cell["network_id"], []).append(coord)
    for coords in river_networks.values():
        seen = {coords[0]}
        queue = deque(seen)
        while queue:
            current = queue.popleft()
            for neighbor in worldgen.neighbors(*current, width, height):
                if neighbor in coords and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        assert seen == set(coords), "river network is not hex-connected"

    lake_ids_by_coord = {
        (cell["tile"]["col"], cell["tile"]["row"]): cell["lake_id"]
        for cell in lake_cells
    }
    for cell in world["river_cells"]:
        current = (cell["tile"]["col"], cell["tile"]["row"])
        seen = set()
        terminated = False
        for _ in range(width * height):
            assert current not in seen, "river drainage loop"
            seen.add(current)
            destination = tiles[current]["downstream"]
            assert destination is not None, "river cell has no downstream"
            nxt = (destination["col"], destination["row"])
            if nxt in lake_ids_by_coord:
                assert cell["kind"] == "endorheic", "river entering a lake must be endorheic"
                assert cell["terminal_lake_id"] == lake_ids_by_coord[nxt]
                terminated = True
                break
            if not tiles[nxt]["land"]:
                assert cell["kind"] == "exorheic", "river reaching the ocean must be exorheic"
                terminated = True
                break
            current = nxt
        assert terminated, "river drainage does not reach ocean or lake"
    assert summary["endorheic_river_hexes"] == sum(
        1 for cell in world["river_cells"] if cell["kind"] == "endorheic"
    )
    assert summary["endorheic_network_count"] == len({
        cell["network_id"] for cell in world["river_cells"] if cell["kind"] == "endorheic"
    })
    depths = [stop[0] for stop in world["rendering"]["river_depth_stops"]]
    assert depths == sorted(depths)

    road_ids = set()
    by_network: dict[str, list[tuple[int, int]]] = {}
    for cell in world["road_cells"]:
        assert cell["id"] not in road_ids
        road_ids.add(cell["id"])
        coord = (cell["tile"]["col"], cell["tile"]["row"])
        assert tiles[coord]["land"]
        assert cell["kind"] in {"road", "bridge"}
        assert (cell["kind"] == "bridge") == bool(tiles[coord]["river"])
        by_network.setdefault(cell["network_id"], []).append(coord)
    for coords in by_network.values():
        if not coords:
            continue
        seen = {coords[0]}
        queue = deque(seen)
        while queue:
            current = queue.popleft()
            for neighbor in worldgen.neighbors(*current, width, height):
                if neighbor in coords and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        assert seen == set(coords), "road network is not hex-connected"
    return True


def generate_fair_world_v2(
    countries: list[dict[str, Any]] | None = None,
    base_seed: int | None = None,
    attempts: int = 8,
) -> tuple[dict[str, Any], Path]:
    normalized = mapgen.normalize_countries(countries)
    import secrets

    base = secrets.randbelow(2_000_000_000) if base_seed is None else int(base_seed)
    best = None
    for offset in range(max(1, attempts)):
        seed = base + offset
        try:
            world = _generate_candidate(seed, normalized)
        except RuntimeError:
            continue
        score = world["metadata"]["fairness"]["score"]
        if best is None or score > best[0]:
            best = (score, world)
        if score >= 0.72:
            break
    if best is None:
        raise RuntimeError("could not generate a playable fair v2 map")
    world = best[1]
    world["metadata"]["generation"] = {
        "base_seed": base,
        "selected_seed": world["metadata"]["seed"],
        "attempts": min(attempts, world["metadata"]["seed"] - base + 1),
        "fairness_floor": 0.72,
    }
    directory = BASE_DIR / "runs" / "worlds"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"world_v2_custom_{world['metadata']['seed']}.json"
    path.write_text(json.dumps(world, ensure_ascii=False, indent=1), encoding="utf-8")
    return world, path
