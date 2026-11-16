"""Shared diplomatic rights for civil transport and military adapters."""
from __future__ import annotations

PACT_SPECS = {
    "TRADE": {"label": "贸易协定", "min_relation": 15},
    "OPEN_BORDERS": {"label": "开放边境", "min_relation": 25},
    "MILITARY_ACCESS": {"label": "军事通行", "min_relation": 40},
    "ALLIANCE": {"label": "同盟", "min_relation": 60},
}


def has_pact(state, left, right, kinds):
    if left not in state.countries or right not in state.countries:
        return False
    if right in state.countries[left].at_war_with:
        return False
    return any(p["status"] == "ACTIVE" and p["pact"] in kinds
               and {p["sender"], p["target"]} == {left, right}
               for p in state.pacts.values())


def access_rights(state, actor, owner):
    own = owner in (None, actor)
    war = not own and owner in state.countries[actor].at_war_with
    civil = own or has_pact(state, actor, owner, {"OPEN_BORDERS", "ALLIANCE"})
    military = own or has_pact(state, actor, owner, {"MILITARY_ACCESS", "ALLIANCE"})
    return {"civil": civil, "military": military, "at_war": war,
            "status": "own" if own else "war" if war else "authorized" if military else "restricted",
            "label": "本国或无主" if own else "交战" if war else "军事通行获准" if military else "未获军事通行"}


def record_border_crossing(state, actor, route, seen):
    """Preserve military routing rules, charge a diplomatic consequence for trespass."""
    from core.diplomacy import Diplomacy
    owners = {coord: c.country_id for c in state.countries.values() for coord in c.tiles}
    crossed = sorted({owners.get(tuple(coord)) for coord in route[1:]} - {None, actor})
    for owner in crossed:
        if owner in seen:
            continue
        rights = access_rights(state, actor, owner)
        if rights["military"] or rights["at_war"]:
            continue
        seen.append(owner)
        diplomacy = Diplomacy(state)
        penalty = int(state.config.get("diplomacy", {}).get("trespass_relation_penalty", 5))
        relation = diplomacy.change_relation(actor, owner, -penalty)
        state.record("border_trespass", country_id=actor, target=owner, relation=relation,
                     penalty=penalty)
