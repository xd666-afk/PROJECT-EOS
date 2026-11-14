"""Prerequisite graph, persistent node progress, and strategic research effects."""
from __future__ import annotations


def initialize(country, config, *, reset=False):
    if country.research_initialized and not reset:
        return
    tree = config["research_tree"]
    known = {key for key, node in tree.items() if node.get("legacy") and
             country.technology.get(node["legacy"]["field"], 0) >= node["legacy"]["level"]}
    def include(key):
        for parent in tree[key]["requires"]:
            if parent not in known:
                known.add(parent)
                include(parent)
    for key in list(known):
        include(key)
    country.known_techs = sorted(known)
    for key in known:
        grant = tree[key].get("legacy")
        if grant:
            country.technology[grant["field"]] = max(country.technology.get(grant["field"], 0), grant["level"])
    country.tech_progress = {} if reset else dict(country.tech_progress)
    country.research_node = None
    country.research_initialized = True
    # An old save's unfinished points follow its selected capability, once only.
    pending = next((key for key, node in tree.items() if key not in known and
                    node.get("legacy", {}).get("field") == country.research_field), None)
    if pending:
        country.tech_progress[pending] = max(country.tech_progress.get(pending, 0.0),
                                             country.research_progress.get(country.research_field, 0.0))
    chosen = legacy_target(country, config, country.research_field)
    if chosen:
        country.research_node = chosen


def available(country, config):
    known = set(country.known_techs)
    return [key for key, node in config["research_tree"].items()
            if key not in known and set(node["requires"]) <= known]


def bonus(country, config, kind):
    return sum(config["research_tree"].get(key, {}).get("bonuses", {}).get(kind, 0.0)
               for key in country.known_techs)


def select(country, config, node_id):
    from core.actions import ActionRejected
    if node_id in country.known_techs:
        raise ActionRejected("RESEARCH_KNOWN", "已经掌握这项技术")
    node = config["research_tree"][node_id]
    missing = [config["research_tree"][key]["name"] for key in node["requires"] if key not in country.known_techs]
    if missing:
        raise ActionRejected("RESEARCH_PREREQUISITES", "尚缺前置技术：" + "、".join(missing))
    previous = country.research_node
    country.research_node = node_id
    if node.get("legacy"):
        country.research_field = node["legacy"]["field"]
    return {"previous_node": previous, "node": node_id, "name": node["name"]}


def legacy_target(country, config, field):
    """Old action clients may request a capability; walk its unmet prerequisites."""
    tree = config["research_tree"]
    targets = [key for key, node in tree.items() if node.get("legacy", {}).get("field") == field and key not in country.known_techs]
    ready = set(available(country, config))
    def first(key):
        if key in ready:
            return key
        for parent in tree[key]["requires"]:
            if parent not in country.known_techs:
                found = first(parent)
                if found:
                    return found
        return None
    return first(targets[0]) if targets else None


def advance(state, country, points):
    config = state.config
    initialize(country, config)
    key = country.research_node
    if key not in available(country, config):
        return
    node = config["research_tree"][key]
    country.tech_progress[key] = country.tech_progress.get(key, 0.0) + points * (1 + bonus(country, config, "research"))
    if country.tech_progress[key] + 1e-12 < node["cost"]:
        return
    country.tech_progress[key] -= node["cost"]
    country.known_techs = sorted(set(country.known_techs) | {key})
    if node.get("legacy"):
        grant = node["legacy"]
        country.technology[grant["field"]] = max(country.technology.get(grant["field"], 0), grant["level"])
        country.research_progress[grant["field"]] = 0.0
    country.research_node = None
    state.record("research_completed", country_id=country.country_id, node=key, name=node["name"],
                 field=node.get("legacy", {}).get("field"), level=node.get("legacy", {}).get("level"))


def snapshot(country, config):
    known = set(country.known_techs)
    ready = set(available(country, config))
    return {"selected": country.research_node, "known": sorted(known), "nodes": [
        {"id": key, **node, "progress": round(country.tech_progress.get(key, 0.0), 4),
         "status": "known" if key in known else "researching" if key == country.research_node and key in ready else "available" if key in ready else "locked"}
        for key, node in config["research_tree"].items()]}
