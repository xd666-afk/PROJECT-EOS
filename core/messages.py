"""Event-driven, short vernacular ruler messages for the live dashboard."""
from __future__ import annotations

from typing import Any

RESEARCH_LABELS = {
    "agriculture": "农业",
    "bronze_metallurgy": "冶金",
    "writing": "文字",
}
HAZARD_LABELS = {"flood": "洪水", "drought": "干旱"}


def _country_name(state, country_id: str) -> str:
    country = state.countries.get(country_id)
    return country.name if country else country_id


def _building_name(state, building: str) -> str:
    return state.config.get("buildings", {}).get(building, {}).get("label", building)


def _messages_for_event(state, event: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one or more candidate messages; the composer picks one per country."""
    kind = event.get("type")
    if kind == "war_declared":
        attacker, defender = event.get("attacker"), event.get("defender")
        return [
            {
                "country_id": attacker, "priority": 100, "title": "边境开战", "mood": "警觉",
                "text": f"我已经向{_country_name(state, defender)}宣战。先把边境的军队和粮草调过去。",
            },
            {
                "country_id": defender, "priority": 100, "title": "遭到宣战", "mood": "警觉",
                "text": f"{_country_name(state, attacker)}向我们宣战了。边境进入戒备，先稳住民心。",
            },
        ]
    if kind == "battle":
        attacker, defender = event.get("attacker"), event.get("defender")
        captured = bool(event.get("captured"))
        if captured:
            return [
                {
                    "country_id": attacker, "priority": 95, "title": "边境得手", "mood": "振奋",
                    "text": f"刚从{_country_name(state, defender)}手里拿下一块边境地。不能松劲，补给要跟上。",
                },
                {
                    "country_id": defender, "priority": 95, "title": "边境失地", "mood": "焦虑",
                    "text": f"{_country_name(state, attacker)}夺走了我们一块边境地。先稳住阵脚，别让恐慌蔓延。",
                },
            ]
        return [
            {
                "country_id": attacker, "priority": 92, "title": "边境交火", "mood": "谨慎",
                "text": f"在边境和{_country_name(state, defender)}打了一仗，谁也没占到便宜。先补兵。",
            },
            {
                "country_id": defender, "priority": 92, "title": "边境交火", "mood": "谨慎",
                "text": f"{_country_name(state, attacker)}在边境试探我们。守住阵线，别贸然追击。",
            },
        ]
    if kind == "peace_accepted":
        sender, target = event.get("sender"), event.get("target")
        return [
            {
                "country_id": sender, "priority": 78, "title": "停战", "mood": "沉稳",
                "text": f"和{_country_name(state, target)}停战了。先把战争疲劳压下去，恢复生产。",
            },
            {
                "country_id": target, "priority": 78, "title": "停战", "mood": "沉稳",
                "text": f"和{_country_name(state, sender)}停战了。边境终于能喘口气。",
            },
        ]
    if kind in {"trade_accepted", "pact_accepted"}:
        sender, target = event.get("sender"), event.get("target")
        label = "贸易协定" if kind == "pact_accepted" else "一笔交易"
        return [
            {
                "country_id": sender, "priority": 55, "title": "生意谈成", "mood": "沉稳",
                "text": f"和{_country_name(state, target)}的{label}谈成了，粮和钱都动了起来。",
            },
            {
                "country_id": target, "priority": 55, "title": "生意谈成", "mood": "沉稳",
                "text": f"和{_country_name(state, sender)}的{label}谈成了，关系也缓和了一些。",
            },
        ]
    if kind == "diplomatic_gift":
        sender, target = event.get("sender"), event.get("target")
        return [
            {
                "country_id": sender, "priority": 50, "title": "外交赠礼", "mood": "沉稳",
                "text": f"给{_country_name(state, target)}送了礼，先把关系稳住。",
            },
            {
                "country_id": target, "priority": 50, "title": "收到赠礼", "mood": "沉稳",
                "text": f"{_country_name(state, sender)}送来礼物，关系缓和了一些。",
            },
        ]
    if kind == "city_founded":
        cid = event.get("country_id")
        return [{
            "country_id": cid, "priority": 68, "title": "建立新城", "mood": "振奋",
            "text": f"{event.get('name', '新地')}已经立起来了。先解决住房和粮食，再谈发展。",
        }]
    if kind == "construction_completed":
        cid = event.get("country_id")
        return [{
            "country_id": cid, "priority": 42, "title": "工程完工", "mood": "沉稳",
            "text": f"{_building_name(state, event.get('building', ''))}完工了，终于能派上用场。",
        }]
    if kind == "research_completed":
        cid = event.get("country_id")
        field = RESEARCH_LABELS.get(event.get("field"), event.get("field", "研究"))
        return [{
            "country_id": cid, "priority": 48, "title": "研究进展", "mood": "沉稳",
            "text": f"研究有了进展：{field}到了{event.get('level')}级。下一步要把它变成实际能力。",
        }]
    if kind == "food_shortage":
        cid = event.get("country_id")
        return [{
            "country_id": cid, "priority": 90, "title": "粮食告急", "mood": "焦虑",
            "text": "粮仓见底了，先保都城和军队。再不想办法，人口会掉。",
        }]
    if kind == "stability_crisis":
        cid = event.get("country_id")
        return [{
            "country_id": cid, "priority": 84, "title": "社会不稳", "mood": "焦虑",
            "text": "社会不稳，先稳住粮价和税负，别让局面继续滑下去。",
        }]
    if kind == "city_unrest":
        cid = event.get("country_id")
        city = event.get("city_name", "城市")
        return [{
            "country_id": cid, "priority": 82, "title": "治安事件", "mood": "警觉",
            "text": f"{city}出了治安事件，先压住乱局，再查原因。",
        }]
    if kind == "city_epidemic":
        cid = event.get("country_id")
        city = event.get("city_name", "城市")
        return [{
            "country_id": cid, "priority": 88, "title": "疫病", "mood": "焦虑",
            "text": f"{city}爆发疫病，预算得往卫生上挪一点，先保住人口。",
        }]
    if kind == "army_recruited":
        cid = event.get("country_id")
        return [{
            "country_id": cid, "priority": 45, "title": "招募军队", "mood": "谨慎",
            "text": f"又招了{event.get('amount', 1)}点兵。军费不低，但边境不能空着。",
        }]
    if kind == "army_desertion":
        cid = event.get("country_id")
        return [{
            "country_id": cid, "priority": 72, "title": "军队逃散", "mood": "焦虑",
            "text": "军饷跟不上，跑了些兵。得先稳住军队。",
        }]
    if kind == "hazard_impact":
        cid = event.get("country_id")
        hazard = HAZARD_LABELS.get(event.get("hazard_type"), event.get("hazard_type", "灾害"))
        return [{
            "country_id": cid, "priority": 70, "title": hazard, "mood": "焦虑",
            "text": f"这场{hazard}让粮食受了损失，得补仓，别让缺口扩大。",
        }]
    return []


def compose_ruler_messages(
    state,
    new_events: list[dict[str, Any]],
    last_message_days: dict[str, int],
    player_country: str | None = None,
    cooldown_days: int = 12,
) -> list[dict[str, Any]]:
    """Choose at most one highest-priority message per country from a batch."""
    candidates: dict[str, dict[str, Any]] = {}
    for event in new_events:
        for message in _messages_for_event(state, event):
            message["source"] = event.get("type", "event")
            cid = message.get("country_id")
            if not cid or cid not in state.countries or cid == player_country:
                continue
            current = candidates.get(cid)
            if current is None or message["priority"] > current["priority"]:
                candidates[cid] = message
    chosen = []
    for cid, message in candidates.items():
        last_day = last_message_days.get(cid, -10_000)
        if (
            message["priority"] < 90
            and state.day_index - last_day < cooldown_days
        ):
            continue
        chosen.append(message)
        last_message_days[cid] = state.day_index
    return chosen


def record_ruler_messages(state, messages: list[dict[str, Any]]) -> None:
    for message in messages:
        state.record(
            "ruler_message",
            country_id=message["country_id"],
            title=message["title"],
            mood=message["mood"],
            text=message["text"],
            priority=message["priority"],
            source=message.get("source", "event"),
            provider="AI 短讯",
        )
