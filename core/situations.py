"""Audience interventions, bounded daily effects, and evidence-based chronicles.

Time intervals are [start_day, end_day). Modifiers are derived rather than written
into policies, so expiry never overwrites a country's subsequent decisions.
"""
from __future__ import annotations

from copy import deepcopy
from core.state import relation_key


def preset(name, category, group, description, effects, **extra):
    return dict(name=name, category=category, group=group, description=description,
                effects=effects, default_duration=30, **extra)


PRESETS = {
    "drought": preset("持续干旱", "自然与气候", "climate", "农业减产，考验粮仓与内政安排。", {"food": -.20}),
    "harvest": preset("丰收时节", "自然与气候", "climate", "农业增产，为储粮和贸易创造条件。", {"food": .20}),
    "commerce": preset("商贸繁荣", "经济与贸易", "commerce", "商业税收增加，具体支出由国家决定。", {"tax": .20}),
    "disruption": preset("商贸受阻", "经济与贸易", "commerce", "商业税收减少，现有贸易协议仍按原规则执行。", {"tax": -.20}),
    "confidence": preset("民心振奋", "社会与民生", "society", "每日提升稳定度，已积累的民心变化会保留。", {"stability": .15}),
    "unrest": preset("社会不安", "社会与民生", "society", "每日降低稳定度，可能进一步影响生产。", {"stability": -.15}),
    "immigration": preset("移民涌入", "人口与劳动力", "population", "持续增加城市人口，也会增加粮食与住房需求。", {"population": .0003}),
    "emigration": preset("人口外迁", "人口与劳动力", "population", "持续减少城市人口，已离开的人口不会自动回归。", {"population": -.0003}),
    "discovery": preset("研究热潮", "科技与建设", "research", "每日研究产出增加，已获得的研究进度保留。", {"research": .30}),
    "work_delay": preset("工程受阻", "科技与建设", "construction", "工程每日进度降低，已完成的建设不会倒退。", {"construction": -.30}),
    "friendship": preset("友好契机", "外交关系", "diplomacy", "持续改善指定两国关系，不保证签约或结盟。", {"relation": 1}, bilateral=True),
    "friction": preset("外交摩擦", "外交关系", "diplomacy", "持续恶化指定两国关系，不会直接强制宣战。", {"relation": -1}, bilateral=True),
}
INTENSITIES = {1: ("轻微", .5), 2: ("适中", 1), 3: ("强烈", 1.5)}
ACTION_NAMES = {"BUILD": "下达建设命令", "BUILD_ROAD_ROUTE": "规划道路施工", "ALLOCATE_WORKERS": "调整劳动力",
                "SET_POLICY": "调整国家政策", "SET_TAX": "调整税率", "SET_RESEARCH": "选择研究方向",
                "TRADE": "处理粮食贸易", "DIPLOMACY": "执行外交行动", "MILITARY": "下达军事命令",
                "SETTLE": "建立新城", "SET_CITY_FOCUS": "调整城市重心", "SET_CITY_ZONE": "调整城市分区",
                "SET_CITY_GOVERNANCE": "调整城市治理", "SET_CITY_BUDGET": "调整城市预算"}
EVENT_NAMES = {"trade_proposed": "发出粮食贸易提案", "trade_accepted": "粮食交易达成",
               "trade_completed": "粮食交易完成", "trade_rejected": "贸易提案被拒绝",
               "construction_completed": "工程完工", "research_completed": "完成技术研究",
               "food_shortage": "出现粮食短缺", "war_declared": "战争爆发", "peace_signed": "签订和平协议",
               "pact_proposed": "提出外交协议", "pact_accepted": "外交协议达成",
               "country_eliminated": "国家退出历史舞台", "stability_crisis": "发生社会动荡"}


def catalog():
    return [{"id": key, **deepcopy(value)} for key, value in PRESETS.items()]


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}须为 {low}—{high} 的整数")
    return value


def active(state):
    return [item for item in state.situations.values() if item["status"] == "active"]


def applies(state, item):
    return item["status"] == "active" and item["start_day"] <= state.day_index < item["end_day"]


def factor(state, country_id, kind):
    delta = sum(PRESETS[item["preset_id"]]["effects"].get(kind, 0) * INTENSITIES[item["intensity"]][1]
                for item in active(state) if applies(state, item) and item["country_id"] == country_id)
    return max(.25, min(2.0, 1 + delta))


def metrics(state, item):
    country = state.countries.get(item["country_id"])
    if country is None:
        return None
    data = {"food": round(country.food, 3), "treasury": round(country.treasury, 3),
            "population": country.population, "stability": round(country.stability, 3),
            "food_production": round(country.last_economy.get("food_production", 0), 3),
            "completed_techs": len(country.known_techs)}
    if item.get("partner_id"):
        data["relation"] = state.relations.get(relation_key(item["country_id"], item["partner_id"]), 0)
    return data


def add_log(state, item, kind, text, **fields):
    row = {"day": state.day_index, "kind": kind, "text": text, **fields}
    if kind in {"intervention", "action", "result", "ended"}:
        item.setdefault("milestones", {}).setdefault(kind, fields.get("source_day", state.day_index))
    item["history"].append(row)
    # Counters and final metrics survive even when the detailed recent log is bounded.
    if len(item["history"]) > 300:
        item["history"] = [item["history"][0]] + item["history"][-299:]
    return row


def create(state, payload):
    if not isinstance(payload, dict):
        raise ValueError("事态参数必须是对象")
    allowed = {"preset_id", "country_id", "partner_id", "duration", "intensity"}
    if set(payload) - allowed:
        raise ValueError("事态只接受预设、目标、持续时间和强度")
    key = payload.get("preset_id")
    if not isinstance(key, str) or key not in PRESETS:
        raise ValueError("请选择有效的预设事件")
    spec = PRESETS[key]
    target, partner = payload.get("country_id"), payload.get("partner_id")
    if not isinstance(target, str) or target not in state.countries:
        raise ValueError("目标国家不存在或已经退出世界")
    if spec.get("bilateral"):
        if not isinstance(partner, str) or partner not in state.countries or partner == target:
            raise ValueError("外交事态须选择另一个仍存在的国家")
    elif partner not in (None, ""):
        raise ValueError("此事件不需要第二个国家")
    duration = integer(payload.get("duration", 30), "持续时间", 1, 731 if state.time_unit=='month' else 180)
    intensity = integer(payload.get("intensity", 2), "强度", 1, 3)
    if len(active(state)) >= 12:
        raise ValueError("最多同时推进 12 个事态，请先结束一个事态")
    participants = sorted([target, partner]) if spec.get("bilateral") else [target]
    for item in active(state):
        if PRESETS[item["preset_id"]]["group"] == spec["group"] and item["participants"] == participants:
            raise ValueError("同一目标已有同类事态，请调整现有事态或先结束它")
    capture(state)
    situation_id = f"S{state.next_situation_number:06d}"
    state.next_situation_number += 1
    item = dict(id=situation_id, preset_id=key, name=spec["name"], category=spec["category"],
                country_id=target, country_name=state.countries[target].name,
                partner_id=partner or None, participants=participants,
                start_day=state.day_index, end_day=state.day_index + duration,
                intensity=intensity, status="active", history=[], totals={},
                action_count=0, quote_count=0, last_replan_day=state.day_index - 7,
                initial=None, final=None, chronicle=None, ended_day=None)
    item["initial"] = metrics(state, item)
    state.situations[situation_id] = item
    from core.monthly import months_for_days
    span=f'{months_for_days(state.day_index,duration)} 个月' if state.time_unit=='month' else f'{duration} 日'
    add_log(state, item, "intervention", f"观众施加「{spec['name']}」，持续 {span}，强度{INTENSITIES[intensity][0]}。")
    state.record("situation_created", situation_id=situation_id, country_id=target, preset_id=key,
                 event={"preset_id": key, "country_id": target, "partner_id": partner or None,
                        "duration": duration, "intensity": intensity})
    return deepcopy(item)


def get_active(state, situation_id):
    if not isinstance(situation_id, str) or situation_id not in state.situations:
        raise ValueError("找不到这个事态")
    item = state.situations[situation_id]
    if item["status"] != "active":
        raise ValueError("已结束的事态只能查看")
    return item


def update(state, situation_id, changes):
    item = get_active(state, situation_id)
    if not isinstance(changes, dict) or not changes or set(changes) - {"intensity", "remaining_days"}:
        raise ValueError("只可调整强度和剩余时间")
    intensity = integer(changes.get("intensity", item["intensity"]), "强度", 1, 3)
    remaining = integer(changes.get("remaining_days", item["end_day"] - state.day_index), "剩余时间", 1, 731 if state.time_unit=='month' else 180)
    capture(state)
    item["intensity"] = intensity
    item["end_day"] = state.day_index + remaining
    from core.monthly import months_for_days
    span=f'{months_for_days(state.day_index,remaining)} 个月' if state.time_unit=='month' else f'{remaining} 日'
    add_log(state, item, "adjustment", f"观众调整为{INTENSITIES[intensity][0]}，剩余 {span}；既有结果保留。")
    state.record("situation_adjusted", situation_id=situation_id, intensity=intensity, remaining_days=remaining,
                 changes={"intensity": intensity, "remaining_days": remaining})
    return deepcopy(item)


def end(state, situation_id, reason="观众提前结束"):
    item = get_active(state, situation_id)
    capture(state)
    item["status"] = "ended"
    item["ended_day"] = state.day_index
    item["end_reason"] = reason
    item["final"] = metrics(state, item)
    add_log(state, item, "ended", reason + "；持续影响停止，已经发生的结果保留。")
    final, initial = item["final"], item["initial"]
    changes = "目标国家已退出世界。" if final is None else (
        f"期间人口净变化 {final['population']-initial['population']:+d}，"
        f"稳定度净变化 {final['stability']-initial['stability']:+.1f}，"
        f"国库净变化 {final['treasury']-initial['treasury']:+.1f}。")
    milestones = []
    seen = set()
    rows = [row for row in item["history"] if row["kind"] == "result"] + [row for row in item["history"] if row["kind"] == "action"]
    for row in rows:
        identity = (row.get("country_id"), row["text"])
        if identity in seen:
            continue
        seen.add(identity)
        actor = state.countries.get(row.get("country_id"))
        milestones.append((actor.name if actor else row.get("country_id") or item["country_name"]) + row["text"])
        if len(milestones) >= 3:
            break
    record = "期间，" + "；".join(milestones) + "。" if milestones else "期间未记录到新的相关行动或结果。"
    item["chronicle"] = (f"第 {item['start_day']}—{state.day_index} 日，{item['country_name']}经历了「{item['name']}」。"
                         f"{record}"
                         f"{reason}。{changes}记录到 {item['action_count']} 条相关行动/结果、"
                         f"{item['quote_count']} 条决策理由/公开表态。上述净变化包含同期其他因素，不能全部归因于此事态。")
    state.record("situation_ended", situation_id=situation_id, country_id=item["country_id"], reason=reason)
    return deepcopy(item)


def add_total(item, kind, value):
    item["totals"][kind] = round(item["totals"].get(kind, 0) + value, 6)


def account(state, country_id, kind, baseline, actual):
    """Allocate the direct difference to matching interventions (not all net change)."""
    for item in active(state):
        effect = PRESETS[item["preset_id"]]["effects"].get(kind, 0)
        if applies(state, item) and item["country_id"] == country_id and effect:
            add_total(item, kind, actual - baseline)


def begin_day(state):
    for item in list(active(state)):
        if any(cid not in state.countries for cid in item["participants"]):
            end(state, item["id"], "参与国家已退出世界")
            continue
        if state.day_index >= item["end_day"]:
            end(state, item["id"], "持续时间届满")
            continue
        spec = PRESETS[item["preset_id"]]
        effects = spec["effects"]
        country = state.countries[item["country_id"]]
        strength = INTENSITIES[item["intensity"]][1]
        if "stability" in effects:
            previous = country.stability
            country.stability = max(0., min(100., previous + effects["stability"] * strength))
            add_total(item, "stability", country.stability - previous)
        if "population" in effects:
            before = country.population
            amount = int(round(before * effects["population"] * strength))
            if country.cities:
                # Match the national change exactly to city populations.
                city = max(country.cities, key=lambda c: c.population)
                amount = max(-city.population, amount)
                city.population += amount
                country.population += amount
                add_total(item, "population", amount)
        if "relation" in effects:
            from core.diplomacy import Diplomacy
            diplomacy = Diplomacy(state)
            before = diplomacy.relation(country.country_id, item["partner_id"])
            delta = (1 if effects["relation"] > 0 else -1) * (2 if item["intensity"] == 3 else 1)
            # Mild effects happen every other day, giving strength a real meaning.
            if item["intensity"] != 1 or (state.day_index - item["start_day"]) % 2 == 0:
                after = diplomacy.change_relation(country.country_id, item["partner_id"], delta)
                add_total(item, "relation", after - before)


def replan_due(state):
    result = set()
    for item in active(state):
        if applies(state, item) and state.day_index - item["last_replan_day"] >= 7:
            result.update(item["participants"])
            item["last_replan_day"] = state.day_index
    return result & state.countries.keys()


def capture(state):
    events = state.event_log[state.situation_cursor:]
    for event in events:
        kind = event["type"]
        if kind not in EVENT_NAMES and kind not in {"action_result", "agent_decision", "ruler_message"}:
            continue
        participants = {event.get(key) for key in ("country_id", "actor", "sender", "target", "attacker", "defender")}
        for item in active(state):
            if event["day"] < item["start_day"] or not participants.intersection(item["participants"]):
                continue
            if kind == "action_result":
                if not event.get("accepted") or event.get("action_type") == "NO_OP":
                    continue
                text = ACTION_NAMES.get(event["action_type"], "执行国家行动")
                effects = event.get("effects", {})
                if event["action_type"] == "SET_POLICY":
                    policy = effects.get('policy', '')
                    text += "：" + {"AGRICULTURE": "重农", "INDUSTRY": "工业", "RESEARCH": "科研", "TRADE": "贸易", "BALANCED": "均衡"}.get(policy, policy)
                country_id = event.get("actor")
                log_kind = "action"
            elif kind in {"agent_decision", "ruler_message"}:
                text = event.get("reason") if kind == "agent_decision" else event.get("text", event.get("message", ""))
                if not text:
                    continue
                country_id, log_kind = event.get("country_id"), "statement"
            else:
                text = EVENT_NAMES[kind]
                if kind == "research_completed":
                    text += "：" + event.get("name", "")
                elif kind == "construction_completed":
                    text += "：" + state.config["buildings"].get(event.get("building"), {}).get("name", "设施")
                elif kind == "trade_accepted":
                    text += f"（粮食 {event.get('food', 0):.1f}，财政 {event.get('treasury', 0):.1f}）"
                country_id = event.get("country_id", event.get("sender", event.get("attacker")))
                log_kind = "result"
            item["quote_count" if log_kind == "statement" else "action_count"] += 1
            add_log(state, item, log_kind, str(text)[:500], country_id=country_id,
                    source_sequence=event["sequence"], source_type=kind,
                    source_day=event["day"], evidence=deepcopy(event.get("effects", {})))
    state.situation_cursor = len(state.event_log)


def finish_day(state):
    from core.monthly import month_index
    capture(state)
    for item in list(active(state)):
        if any(cid not in state.countries for cid in item["participants"]):
            end(state, item["id"], "参与国家已退出世界")
        elif state.day_index >= item["end_day"]:
            end(state, item["id"], "持续时间届满")
        elif (state.time_unit=='month' and month_index(state.day_index)>month_index(state.day_index-1)) or (state.time_unit!='month' and ((state.day_index - item["start_day"]) % 5 == 0 or state.day_index == item["start_day"] + 1)):
            data = metrics(state, item)
            add_log(state, item, "observation", f"粮仓 {data['food']:.1f} · 国库 {data['treasury']:.1f} · 人口 {data['population']} · 稳定 {data['stability']:.1f}", metrics=data)


def snapshot(state, item, detailed=False):
    elapsed = max(0, (state.day_index if item["status"] == "active" else item["ended_day"]) - item["start_day"])
    duration = max(1, item["end_day"] - item["start_day"])
    result = {key: deepcopy(value) for key, value in item.items() if key != "history"}
    result.update(elapsed=elapsed, remaining_days=max(0, item["end_day"] - state.day_index) if item["status"] == "active" else 0,
                  progress=min(1., elapsed / duration) if item["status"] == "active" else 1.,
                  stage="已结束" if item["status"] != "active" else "已有相关结果" if "result" in item.get("milestones", {}) else "国家已有行动" if item["action_count"] else "影响持续" if elapsed else "刚刚施加",
                  latest=item["history"][-1] if item["history"] else None,
                  current=metrics(state, item) if item["status"] == "active" else item["final"])
    if detailed:
        result["history"] = deepcopy(item["history"])
    return result
