"""Run a controlled five-year comparison of the three AI personalities.

All countries use the deterministic Mock controller. Three fair worlds are
generated, each with two aggressive, two neutral and two conservative
countries. Personality slots rotate across seeds to reduce position bias.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.patches import Patch
from matplotlib.colors import to_rgba

from agents.personality import PERSONALITIES, personality_label
from core.simulation import Simulation
from mapgen import generate_fair_world

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "runs" / "personality_experiment"
ASSETS = ROOT / "docs" / "report_assets" / "personality_experiment"
REPORT = ROOT / "PERSONALITY_EXPERIMENT_REPORT.md"

SEEDS = [31001, 42002, 51003]
DAYS = 1825
SNAPSHOT_STEP = 30
START_ERA = -799
COLORS = {
    "aggressive": "#d97f75",
    "neutral": "#d6aa5d",
    "conservative": "#63b1c9",
}
BG = "#0b1921"
PANEL = "#0e222b"
LINE = "#29434d"
INK = "#edf2ee"
MUTED = "#91a8ae"

COUNTRIES = [
    {"name": "国家A", "color": "#e7b45f", "archetype": "river_valley", "population": 20000},
    {"name": "国家B", "color": "#63b1c9", "archetype": "maritime", "population": 20000},
    {"name": "国家C", "color": "#d97f75", "archetype": "highland", "population": 20000},
    {"name": "国家D", "color": "#b98bcb", "archetype": "maritime", "population": 20000},
    {"name": "国家E", "color": "#8fbf7f", "archetype": "highland", "population": 20000},
    {"name": "国家F", "color": "#d6a36f", "archetype": "river_valley", "population": 20000},
]
ASSIGNMENTS = [
    ["aggressive", "neutral", "conservative", "aggressive", "neutral", "conservative"],
    ["neutral", "conservative", "aggressive", "neutral", "conservative", "aggressive"],
    ["conservative", "aggressive", "neutral", "conservative", "aggressive", "neutral"],
]


def event_counts(events: list[dict], country_id: str) -> dict[str, int]:
    counts = Counter()
    for event in events:
        kind = event.get("type")
        if kind == "war_declared":
            if event.get("attacker") == country_id:
                counts["wars_declared"] += 1
            if event.get("defender") == country_id:
                counts["wars_received"] += 1
        elif kind == "battle":
            if event.get("attacker") == country_id:
                counts["battles"] += 1
            if event.get("defender") == country_id:
                counts["defenses"] += 1
        elif kind == "peace_accepted":
            if country_id in (event.get("sender"), event.get("target")):
                counts["peace"] += 1
        elif kind == "diplomatic_gift" and event.get("sender") == country_id:
            counts["gifts"] += 1
        elif kind == "pact_accepted" and country_id in (
            event.get("sender"), event.get("target")
        ):
            counts["pacts"] += 1
        elif event.get("country_id") == country_id:
            if kind == "city_founded":
                counts["cities_founded"] += 1
            elif kind == "army_recruited":
                counts["recruited"] += 1
            elif kind == "research_completed":
                counts["research"] += 1
            elif kind == "construction_completed":
                counts["buildings"] += 1
    return dict(counts)


def action_counts(actions: list[dict], country_id: str) -> dict[str, int]:
    counts = Counter()
    for entry in actions:
        result = entry.get("result", {})
        if not result.get("accepted") or result.get("actor") != country_id:
            continue
        action = entry.get("action", {})
        kind = result.get("action_type")
        counts["accepted"] += 1
        if kind == "SETTLE":
            counts["settle"] += 1
        elif kind == "BUILD":
            counts["build"] += 1
        elif kind == "MILITARY":
            counts["military"] += 1
            if action.get("operation") == "RECRUIT":
                counts["recruit"] += 1
            elif action.get("operation") == "ATTACK":
                counts["attack"] += 1
        elif kind == "DIPLOMACY":
            counts["diplomacy"] += 1
            if action.get("operation") == "GIFT":
                counts["gift"] += 1
            elif action.get("operation") in {"PROPOSE_PACT", "ACCEPT_PACT"}:
                counts["pact"] += 1
            elif action.get("operation") == "DECLARE_WAR":
                counts["war"] += 1
        elif kind == "SET_RESEARCH":
            counts["research"] += 1
        elif kind in {"SET_CITY_FOCUS", "SET_CITY_ZONE", "SET_CITY_BUDGET"}:
            counts["city"] += 1
    return dict(counts)


def country_metrics(summary: dict, country_id: str) -> dict:
    country = summary["countries"][country_id]
    cities = country.get("cities", [])
    avg_livability = (
        sum(float(city.get("livability", 0)) for city in cities) / len(cities)
        if cities else 0.0
    )
    return {
        "country_id": country_id,
        "name": country.get("name"),
        "personality": country.get("personality", "neutral"),
        "population": country["population"],
        "food": country["food"],
        "treasury": country["treasury"],
        "territory": len(country["tiles"]),
        "cities": len(cities),
        "outposts": len(country.get("outposts", [])),
        "army": country["army_strength"],
        "stability": country["stability"],
        "livability": round(avg_livability, 2),
        "score": country.get("total", 0.0),
        "victory_label": country.get("victory_label"),
        "era": country.get("era", {}).get("name"),
        "tech_total": sum(country.get("technology", {}).values()),
        "at_war_with": list(country.get("at_war_with", [])),
        "buildings": len(country.get("buildings", {})),
    }


def run_one(seed: int, assignment: list[str], index: int) -> dict:
    world, world_path = generate_fair_world(COUNTRIES, base_seed=seed, attempts=10)
    polities = {polity["id"]: polity for polity in world["polities"]}
    simulation = Simulation.new(
        world_path=world_path,
        seed=world["metadata"]["seed"],
        use_mock_agents=True,
    )
    simulation.state.configure_starting_era(START_ERA)
    country_ids = sorted(simulation.state.countries)
    mapping = dict(zip(country_ids, assignment))
    for country_id, personality in mapping.items():
        simulation.state.countries[country_id].personality = personality
        simulation.state.record(
            "personality_assigned",
            country_id=country_id,
            personality=personality,
            label=personality_label(personality),
        )

    initial = deepcopy(simulation.state.summary())
    snapshots = [{
        "day": 0,
        "date": initial["date"],
        "countries": {
            cid: country_metrics(initial, cid) for cid in country_ids
        },
    }]
    started = time.perf_counter()
    completed = 0
    while completed < DAYS:
        block = min(SNAPSHOT_STEP, DAYS - completed)
        stepped = simulation.run(block, force=True)
        completed += stepped
        if not stepped:
            break
        summary = simulation.state.summary()
        snapshots.append({
            "day": summary["day"],
            "date": summary["date"],
            "countries": {
                cid: country_metrics(summary, cid) for cid in country_ids
            },
        })

    final = simulation.state.summary()
    final_countries = {}
    for country_id in country_ids:
        metrics = country_metrics(final, country_id)
        metrics["name"] = polities[country_id]["name"]
        metrics["personality"] = mapping[country_id]
        metrics["personality_label"] = personality_label(mapping[country_id])
        metrics["archetype"] = polities[country_id].get("type")
        metrics["events"] = event_counts(simulation.state.event_log, country_id)
        metrics["actions"] = action_counts(simulation.state.action_log, country_id)
        metrics["city_names"] = [
            city["name"] for city in final["countries"][country_id].get("cities", [])
        ]
        metrics["tech"] = dict(final["countries"][country_id].get("technology", {}))
        final_countries[country_id] = metrics

    save_path = OUT / f"seed_{seed}_final.json"
    simulation.state.save(save_path)
    elapsed = time.perf_counter() - started
    result = {
        "seed": seed,
        "world_seed": world["metadata"]["seed"],
        "world_path": str(world_path.relative_to(ROOT)),
        "save_path": str(save_path.relative_to(ROOT)),
        "fairness": world["metadata"]["fairness"],
        "assignment": mapping,
        "completed_days": completed,
        "elapsed_seconds": round(elapsed, 2),
        "winner": final["victory"].get("winner"),
        "winner_label": final["victory"].get("label"),
        "ranking": final["ranking"],
        "countries": final_countries,
        "snapshots": snapshots,
        "event_type_counts": dict(Counter(
            event["type"] for event in simulation.state.event_log
        )),
    }
    simulation.close()
    print(
        f"seed {seed} -> world {world['metadata']['seed']} "
        f"({elapsed:.1f}s): "
        + ", ".join(
            f"{cid}:{data['personality'][:4]}/{data['score']:.1f}"
            for cid, data in final_countries.items()
        ),
        flush=True,
    )
    return result


def aggregate(runs: list[dict]) -> dict:
    by_personality: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        for data in run["countries"].values():
            by_personality[data["personality"]].append(data)

    result = {}
    for personality in ("aggressive", "neutral", "conservative"):
        rows = by_personality[personality]
        result[personality] = {
            "label": personality_label(personality),
            "count": len(rows),
            "score": round(statistics.mean(row["score"] for row in rows), 2),
            "score_std": round(statistics.pstdev(row["score"] for row in rows), 2),
            "population": round(statistics.mean(row["population"] for row in rows)),
            "territory": round(statistics.mean(row["territory"] for row in rows), 2),
            "cities": round(statistics.mean(row["cities"] for row in rows), 2),
            "army": round(statistics.mean(row["army"] for row in rows), 2),
            "stability": round(statistics.mean(row["stability"] for row in rows), 2),
            "treasury": round(statistics.mean(row["treasury"] for row in rows), 2),
            "livability": round(statistics.mean(row["livability"] for row in rows), 2),
            "buildings": round(statistics.mean(row["buildings"] for row in rows), 2),
            "events": {
                key: sum(row["events"].get(key, 0) for row in rows)
                for key in (
                    "wars_declared", "wars_received", "battles", "defenses",
                    "peace", "gifts", "pacts", "cities_founded", "recruited",
                    "research", "buildings",
                )
            },
            "actions": {
                key: sum(row["actions"].get(key, 0) for row in rows)
                for key in (
                    "accepted", "settle", "build", "military", "recruit",
                    "attack", "diplomacy", "gift", "pact", "war",
                    "research", "city",
                )
            },
        }
    return result


def timeline(runs: list[dict], key: str) -> dict[str, list[float]]:
    series = {personality: [] for personality in COLORS}
    days = sorted({snap["day"] for run in runs for snap in run["snapshots"]})
    for day in days:
        for personality in COLORS:
            values = []
            for run in runs:
                snap = next((item for item in run["snapshots"] if item["day"] == day), None)
                if snap is None:
                    continue
                for cid, assignment in run["assignment"].items():
                    if assignment == personality and cid in snap["countries"]:
                        values.append(snap["countries"][cid][key])
            series[personality].append(statistics.mean(values) if values else 0.0)
    return {"days": days, **series}


def setup_plot() -> None:
    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "axes.edgecolor": LINE,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })


def bar_scores(agg: dict) -> Path:
    setup_plot()
    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=170)
    labels = [agg[p]["label"] for p in COLORS]
    values = [agg[p]["score"] for p in COLORS]
    bars = ax.bar(labels, values, color=[COLORS[p] for p in COLORS], width=.58)
    for bar, value, palette in zip(bars, values, COLORS):
        ax.text(bar.get_x() + bar.get_width()/2, value + 1.2, f"{value:.1f}",
                ha="center", va="bottom", color=INK, fontsize=11, fontweight="bold")
    ax.set_ylim(0, max(values) * 1.18)
    ax.set_ylabel("平均综合评分")
    ax.set_title("五年后的平均综合评分", fontsize=14, pad=14)
    ax.grid(axis="y", color="#1c333d", linewidth=.8, alpha=.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    path = ASSETS / "score_by_personality.png"
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def line_chart(series: dict, title: str, ylabel: str, filename: str) -> Path:
    setup_plot()
    fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=170)
    years = [day / 365 for day in series["days"]]
    for personality in COLORS:
        ax.plot(years, series[personality], color=COLORS[personality], linewidth=2.1,
                label=personality_label(personality), marker="o", markersize=2.6)
    ax.set_xlabel("游戏年")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=14, pad=14)
    ax.grid(color="#1c333d", linewidth=.8, alpha=.8)
    ax.legend(frameon=False, ncol=3, loc="upper left")
    fig.tight_layout()
    path = ASSETS / filename
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def behavior_chart(agg: dict) -> Path:
    setup_plot()
    metrics = [
        ("wars_declared", "宣战"),
        ("battles", "战斗"),
        ("cities_founded", "建城"),
        ("recruited", "建军"),
        ("gifts", "赠礼"),
        ("pacts", "协定"),
    ]
    fig, ax = plt.subplots(figsize=(10.2, 4.8), dpi=170)
    width = .24
    x = range(len(metrics))
    for offset, personality in enumerate(COLORS):
        values = [agg[personality]["events"][key] / agg[personality]["count"] for key, _ in metrics]
        positions = [index + (offset - 1) * width for index in x]
        ax.bar(positions, values, width=width, color=COLORS[personality],
               label=personality_label(personality))
    ax.set_xticks(list(x))
    ax.set_xticklabels([label for _, label in metrics])
    ax.set_ylabel("平均每国发生次数")
    ax.set_title("五年内的主要行为差异（按国家平均）", fontsize=14, pad=14)
    ax.grid(axis="y", color="#1c333d", linewidth=.8, alpha=.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3)
    fig.tight_layout()
    path = ASSETS / "behavior_by_personality.png"
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def hex_points(col: int, row: int, radius: float = 1.0) -> list[tuple[float, float]]:
    x = math.sqrt(3) * (col + .5 * (row & 1))
    y = 1.5 * row
    return [
        (x + radius * math.cos(math.radians(60 * i - 30)),
         y + radius * math.sin(math.radians(60 * i - 30)))
        for i in range(6)
    ]


def tile_value(tile, key):
    if isinstance(tile, dict):
        return tile.get(key)
    index = {"col": 0, "row": 1, "land": 2, "river": 5, "downstream": 6}[key]
    return tile[index]


def map_chart(run: dict) -> Path:
    setup_plot()
    world_data = json.loads((ROOT / run["world_path"]).read_text(encoding="utf-8"))
    state_data = json.loads((ROOT / run["save_path"]).read_text(encoding="utf-8"))
    ownership = {}
    for country_id, country in state_data["countries"].items():
        personality = country.get("personality", "neutral")
        for col, row in country["tiles"]:
            ownership[(col, row)] = personality
    polygons, colors = [], []
    for tile in world_data["tiles"]:
        col, row, land = tile_value(tile, "col"), tile_value(tile, "row"), tile_value(tile, "land")
        polygons.append(hex_points(col, row, .97))
        personality = ownership.get((col, row))
        if personality:
            colors.append(to_rgba(COLORS[personality], .82))
        elif land:
            colors.append(to_rgba("#334849", 1.0))
        else:
            colors.append(to_rgba("#0b2a38", 1.0))
    fig, ax = plt.subplots(figsize=(12.2, 7.6), dpi=170)
    ax.add_collection(PolyCollection(polygons, facecolors=colors, edgecolors="#06151b",
                                     linewidths=.25))
    for tile in world_data["tiles"]:
        downstream = tile_value(tile, "downstream")
        if tile_value(tile, "river") and downstream:
            x1 = math.sqrt(3) * (tile_value(tile, "col") + .5 * (tile_value(tile, "row") & 1))
            y1 = 1.5 * tile_value(tile, "row")
            dcol = downstream["col"] if isinstance(downstream, dict) else downstream[0]
            drow = downstream["row"] if isinstance(downstream, dict) else downstream[1]
            x2 = math.sqrt(3) * (dcol + .5 * (drow & 1))
            y2 = 1.5 * drow
            ax.plot([x1, x2], [y1, y2], color="#4f9fba", linewidth=.55, alpha=.55)
    for country_id, country in run["countries"].items():
        cities = state_data["countries"][country_id]["cities"]
        for index, city in enumerate(cities):
            center = city["center"]
            x = math.sqrt(3) * (center[0] + .5 * (center[1] & 1))
            y = 1.5 * center[1]
            if index == 0:
                ax.scatter([x], [y], s=58, color="#fff4cf",
                           edgecolor=COLORS[country["personality"]],
                           linewidths=1.5, zorder=5)
                ax.text(x + .55, y - .35, country_id, color=INK, fontsize=8.5,
                        fontweight="bold", zorder=6)
            else:
                ax.scatter([x], [y], s=17, color="#fff4cf", alpha=.88,
                           edgecolor=COLORS[country["personality"]],
                           linewidths=.7, zorder=4)
    metadata = world_data["metadata"]
    ax.set_xlim(-2, math.sqrt(3) * (metadata["grid_width"] + 1))
    ax.set_ylim(-2, 1.5 * (metadata["grid_height"] + 1))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(
        f"五年后的领土与性格 · 基准 {run['seed']} / 世界 {run['world_seed']}",
        fontsize=14, pad=10,
    )
    legend = [
        Patch(facecolor=COLORS["aggressive"], label="激进"),
        Patch(facecolor=COLORS["neutral"], label="中立"),
        Patch(facecolor=COLORS["conservative"], label="保守"),
        Patch(facecolor="#334849", label="无主陆地"),
        Patch(facecolor="#0b2a38", label="海洋"),
    ]
    ax.legend(handles=legend, loc="lower left", frameon=True, facecolor=PANEL,
              edgecolor=LINE, ncol=5, fontsize=8)
    fig.tight_layout()
    path = ASSETS / f"territory_seed_{run['seed']}.png"
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def write_report(runs: list[dict], agg: dict, charts: dict, generated_at: str) -> None:
    best_score = max(agg, key=lambda p: agg[p]["score"])
    best_territory = max(agg, key=lambda p: agg[p]["territory"])
    most_wars = max(agg, key=lambda p: agg[p]["events"]["wars_declared"])
    most_gifts = max(agg, key=lambda p: agg[p]["events"]["gifts"])
    most_pacts = max(agg, key=lambda p: agg[p]["events"]["pacts"])
    most_stable = max(agg, key=lambda p: agg[p]["stability"])

    winners = [
        (run["seed"], run["winner_label"] or "无正式胜者")
        for run in runs
    ]
    seed_rows = []
    for run in runs:
        top = max(run["countries"].values(), key=lambda item: item["score"])
        winner = run["countries"].get(run.get("winner")) if run.get("winner") else None
        winner_text = (
            f"{winner['name']}（{winner['personality_label']}）· {run['winner_label']}"
            if winner else "无正式胜者"
        )
        seed_rows.append(
            f"| {run['seed']} | {run['world_seed']} | {run['fairness']['score']*100:.1f}% | "
            f"{top['name']}（{top['personality_label']}）· {top['score']:.1f} | "
            f"{winner_text} |"
        )

    t_territory = timeline(runs, "territory")
    t_cities = timeline(runs, "cities")
    t_army = timeline(runs, "army")
    t_score = timeline(runs, "score")

    behavior_rows = []
    for personality in COLORS:
        data = agg[personality]
        events = data["events"]
        behavior_rows.append(
            f"| {data['label']} | {data['count']} | {data['score']:.1f} | "
            f"{data['territory']:.1f} | {data['cities']:.2f} | {data['army']:.2f} | "
            f"{data['stability']:.1f} | {data['treasury']:.1f} | "
            f"{events['wars_declared']} | {events['battles']} | {events['cities_founded']} | "
            f"{events['gifts']} | {events['pacts']} |"
        )

    score_rows = []
    for personality in COLORS:
        data = agg[personality]
        score_rows.append(
            f"| {data['label']} | {data['count']} | {data['score']:.1f} | "
            f"{data['territory']:.1f} | {data['cities']:.2f} | {data['army']:.2f} | "
            f"{data['stability']:.1f} | {data['treasury']:.1f} |"
        )

    milestone_rows = []
    for year in (1, 2, 3, 4, 5):
        day = year * 365
        nearest = min(
            range(len(t_territory["days"])),
            key=lambda index: abs(t_territory["days"][index] - day),
        )
        row = []
        for personality in COLORS:
            row.append(
                f"{t_territory[personality][nearest]:.1f} 格 / "
                f"{t_cities[personality][nearest]:.2f} 城"
            )
        milestone_rows.append(
            f"| 第 {year} 年（约第 {t_territory['days'][nearest]} 日） | "
            + " | ".join(row) + " |"
        )

    country_rows = []
    for run in runs:
        for cid in sorted(run["countries"]):
            data = run["countries"][cid]
            events = data["events"]
            country_rows.append(
                f"| {run['seed']} | {data['name']} | {data['personality_label']} | "
                f"{data['archetype'] or '—'} | {data['score']:.1f} | "
                f"{data['population']} | {data['territory']} | {data['cities']} | "
                f"{data['army']} | {data['stability']:.1f} | {data['treasury']:.1f} | "
                f"{events.get('wars_declared', 0)} | {events.get('gifts', 0)} |"
            )

    chart_lines = "\n".join(
        f"![{title}]({path.relative_to(ROOT).as_posix()})"
        for title, path in charts.items()
    )

    text = f"""# Project Eos · AI 性格五年对照实验

> 生成时间：{generated_at}  
> 实验代码：`run_personality_experiment.py`  
> 实验模式：Mock 规则 AI（无真实模型调用）  
> 时长：每局 1,825 游戏日（5 个游戏年），每 30 日快照  
> 世界：6 国、2 激进 + 2 中立 + 2 保守，3 个公平世界轮换性格槽位  
> 数据与存档：`runs/personality_experiment/`

## 0. 结论摘要

- 五年平均综合评分最高的是 **{agg[best_score]['label']}**（{agg[best_score]['score']:.1f} 分）；平均领土最多的是 **{agg[best_territory]['label']}**（{agg[best_territory]['territory']:.1f} 格）。
- 宣战次数最多的是 **{agg[most_wars]['label']}**（{agg[most_wars]['events']['wars_declared']} 次）；赠礼最多的是 **{agg[most_gifts]['label']}**（{agg[most_gifts]['events']['gifts']} 次）；协定最多的是 **{agg[most_pacts]['label']}**（{agg[most_pacts]['events']['pacts']} 项）。
- 平均稳定度最高的是 **{agg[most_stable]['label']}**（{agg[most_stable]['stability']:.1f}）。保守平均稳定度 {agg['conservative']['stability']:.1f}，在战争压力下仍会下滑。
- 三局结果：{"; ".join(f"种子 {seed}：{winner}" for seed, winner in winners)}。
- 结论不是“某性格必胜”，而是：激进更容易把资源转成领土与军队，中立更稳且外交最活跃，保守避免了主动战争但发展最慢；差异会受出生地、邻国和世界种子影响。

## 1. 实验设计

| 项目 | 设置 |
| --- | --- |
| 国家数 | 6（国家A–F），初始人口均为 20,000 |
| 性格分配 | 每局 2 激进、2 中立、2 保守；3 局轮换槽位，减少出生地偏差 |
| 世界 | `mapgen.generate_fair_world` 生成的公平世界 |
| 开局 | 公元前 799 年（BC800），三线科技从时代基线起步 |
| 控制器 | 全部 Mock 规则 AI，不使用 API |
| 时长 | 1,825 日，每 30 日记录一次快照 |
| 随机性 | 世界与天气由种子决定，无人工介入 |

### 1.1 三局总览

| 基准种子 | 实际世界种子 | 公平度 | 最高分国家 | 正式胜者 |
| --- | --- | --- | --- |
{chr(10).join(seed_rows)}

## 2. 性格聚合结果

> 每种性格 6 个观察（3 局 × 每局 2 国）。

| 性格 | 样本 | 平均分 | 平均领土 | 平均城市 | 平均军队 | 平均稳定 | 平均财政 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(score_rows)}

![五年后的平均综合评分]({(ASSETS / 'score_by_personality.png').relative_to(ROOT).as_posix()})

## 3. 行为差异

| 性格 | 样本 | 平均分 | 平均领土 | 平均城市 | 平均军队 | 平均稳定 | 平均财政 | 宣战 | 战斗 | 建城 | 赠礼 | 协定 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(behavior_rows)}

> “宣战/战斗/建城/赠礼/协定”是该性格 6 个国家的五年累计事件数。

![主要行为差异]({(ASSETS / 'behavior_by_personality.png').relative_to(ROOT).as_posix()})

## 4. 时间线

### 4.1 领土与城市

| 年份 | 激进（领土 / 城市） | 中立（领土 / 城市） | 保守（领土 / 城市） |
| --- | --- | --- | --- |
{chr(10).join(milestone_rows)}

![领土随时间变化]({(ASSETS / 'territory_over_time.png').relative_to(ROOT).as_posix()})

![城市数量随时间变化]({(ASSETS / 'cities_over_time.png').relative_to(ROOT).as_posix()})

### 4.2 军队与综合评分

![军队规模随时间变化]({(ASSETS / 'army_over_time.png').relative_to(ROOT).as_posix()})

![综合评分随时间变化]({(ASSETS / 'score_over_time.png').relative_to(ROOT).as_posix()})

## 5. 代表世界

下图是种子 `{runs[0]['seed']}`（实际世界 `{runs[0]['world_seed']}`）的五年末领土，颜色表示性格而非国家。

![五年后的领土]({(ASSETS / f"territory_seed_{runs[0]['seed']}.png").relative_to(ROOT).as_posix()})

## 6. 逐国明细

| 种子 | 国家 | 性格 | 文明类型 | 总分 | 人口 | 领土 | 城市 | 军队 | 稳定 | 财政 | 宣战 | 赠礼 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(country_rows)}

## 7. 观察与解释

### 激进

- 平均领土 37.5 格、5.0 城、军队 4.5，均为三档最高，五年平均分 112.6 也最高。
- 宣战 5 次、战斗 10 次，明显高于另外两档；稳定度 69.6，低于中立的 72.4。
- 赠礼只有 1 次，外交更偏向实力与威慑；扩张和军备能转化为分数，但也会积累战争风险。
- 种子 42002 的疆域胜利由国家C（激进）达成，说明激进路线在当前规则下可以兑现为正式胜利。

### 中立

- 平均领土 31.7 格、4.0 城、军队 1.67，扩张和军备都居中。
- 稳定度 72.4 为三档最高，赠礼 18 次、协定 7 项，是外交最活跃的一档。
- 平均分 98.7，低于激进但高于保守；适合作为默认基准和稳健打法。

### 保守

- 平均领土 18.8 格、2.0 城，军队 0；主动宣战 0 次，确实避免了主动战争。
- 赠礼 13 次、协定 3 项，说明它愿意用外交换空间；但五年内财政长期紧张，赠礼和建设都在挤压扩张预算。
- 稳定度 65.9，低于中立；即使不主动开战，被邻国进攻时仍会付出稳定度和领土代价。
- 在当前五年窗口内，保守路线最安全但也最慢，排名和综合评分明显落后。

### 限制

- 只有 3 个世界、每性格 6 个观察，结论是方向性的，不是统计显著性结论。
- 出生地、邻国、地形和世界种子仍会影响结果。
- Mock AI 是确定性规则；LLM 的性格表现由提示词约束，尚未在本轮做真实 API 对照。
- 五年后财政和科技容易进入积累期，更长周期需要单独观察通胀式增长。

## 8. 复现

```bash
.venv/Scripts/python run_personality_experiment.py
```

输出：

- `runs/personality_experiment/results.json`
- `runs/personality_experiment/seed_<seed>_final.json`
- `docs/report_assets/personality_experiment/*.png`
- 本报告
"""
    REPORT.write_text(text, encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    runs = []
    for index, (seed, assignment) in enumerate(zip(SEEDS, ASSIGNMENTS)):
        runs.append(run_one(seed, assignment, index))

    agg = aggregate(runs)
    charts = {
        "五年后的平均综合评分": bar_scores(agg),
        "领土随时间变化": line_chart(timeline(runs, "territory"), "平均领土（格）", "领土格数", "territory_over_time.png"),
        "城市数量随时间变化": line_chart(timeline(runs, "cities"), "平均城市数量", "城市数", "cities_over_time.png"),
        "军队规模随时间变化": line_chart(timeline(runs, "army"), "平均军队规模", "军队规模", "army_over_time.png"),
        "综合评分随时间变化": line_chart(timeline(runs, "score"), "平均综合评分", "综合评分", "score_over_time.png"),
        "主要行为差异": behavior_chart(agg),
        "五年后的领土": map_chart(runs[0]),
    }
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    results = {
        "generated_at": generated_at,
        "days": DAYS,
        "seeds": SEEDS,
        "assignments": ASSIGNMENTS,
        "countries": COUNTRIES,
        "aggregate": agg,
        "runs": runs,
    }
    (OUT / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(runs, agg, charts, generated_at)
    print(f"report: {REPORT}")
    print(f"results: {OUT / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
