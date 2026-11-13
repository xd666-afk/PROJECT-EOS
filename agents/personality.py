"""Shared AI personality presets for rule agents and LLM prompts."""

from __future__ import annotations

from typing import Any

DEFAULT_PERSONALITY = "neutral"

PERSONALITIES: dict[str, dict[str, Any]] = {
    "aggressive": {
        "label": "激进",
        "tagline": "扩张、军备与威慑优先",
        "llm": (
            "激进扩张型统治者。优先扩充领土、军备与战略纵深，愿意为战争和开拓承担财政风险；"
            "对邻国保持威慑，少做无条件赠礼，贸易与协定必须换来实际利益；"
            "城市优先工矿、道路和军工，粮食只要不崩就继续向前推进。"
        ),
        "mock": {
            "recruit_day": 90,
            "recruit_first": 90.0,
            "recruit_extra": 130.0,
            "army_target": 8,
            "barracks": 3,
            "roads": 6,
            "units": ["CAVALRY", "CHARIOT", "SIEGE", "ARCHER", "HEAVY_INFANTRY", "MILITIA"],
            "peace_exhaustion": 14.0,
            "expand_actions": 3,
            "expand_reserve": 10.0,
            "expand_food": 0.0,
            "expand_after_buildings": 0,
            "gift_relation": 0,
            "gift_treasury": 300.0,
            "gift_max": 3.0,
            "pact_relation": 30,
            "war_relation": 55,
            "war_min_army": 2,
            "war_roll": 2,
            "trade_food": 280.0,
            "build_reserve": 0.0,
            "workers": {"agriculture": 0.45, "mining": 0.4, "construction": 0.15},
            "city_focus": "industry",
            "city_budget": "investment",
        },
    },
    "neutral": {
        "label": "中立",
        "tagline": "粮食、财政、军备与外交均衡",
        "llm": (
            "务实中立型统治者。粮食、财政、科技、军备和外交保持平衡；"
            "不主动挑起没有把握的战争，也不排斥在有利时扩张或结盟；"
            "根据邻国实力、财政和粮食状况灵活取舍，优先可持续增长。"
        ),
        "mock": {
            "recruit_day": 180,
            "recruit_first": 150.0,
            "recruit_extra": 220.0,
            "army_target": 4,
            "barracks": 2,
            "roads": 3,
            "units": ["CHARIOT", "ARCHER", "HEAVY_INFANTRY", "MILITIA", "CAVALRY", "SIEGE"],
            "peace_exhaustion": 9.0,
            "expand_actions": 4,
            "expand_reserve": 10.0,
            "expand_food": 0.0,
            "expand_after_buildings": 0,
            "gift_relation": 30,
            "gift_treasury": 80.0,
            "gift_max": 8.0,
            "pact_relation": 15,
            "war_relation": 25,
            "war_min_army": 3,
            "war_roll": 5,
            "trade_food": 220.0,
            "build_reserve": 20.0,
            "workers": {"agriculture": 0.6, "mining": 0.2, "construction": 0.2},
            "city_focus": None,
            "city_budget": None,
        },
    },
    "conservative": {
        "label": "保守",
        "tagline": "粮食、稳定、防御与外交优先",
        "llm": (
            "保守稳健型统治者。优先粮食安全、城市宜居、稳定度和防御纵深；"
            "避免远征、多线战争和透支财政，保留安全储备；"
            "更愿意通过赠礼、贸易和协定换取和平，只有在生存受到威胁时才诉诸战争；"
            "城市优先农业、粮仓、神庙和书库。"
        ),
        "mock": {
            "recruit_day": 240,
            "recruit_first": 120.0,
            "recruit_extra": 220.0,
            "army_target": 2,
            "barracks": 1,
            "roads": 1,
            "units": ["HEAVY_INFANTRY", "ARCHER", "MILITIA", "CHARIOT", "SIEGE", "CAVALRY"],
            "peace_exhaustion": 6.0,
            "expand_actions": 4,
            "expand_reserve": 10.0,
            "expand_food": 0.0,
            "expand_after_buildings": 0,
            "gift_relation": 55,
            "gift_treasury": 60.0,
            "gift_max": 6.0,
            # 15 is the floor `core.diplomacy` refuses below; a profile that asks for less
            # only earns a rejected action every planning cycle.
            "pact_relation": 15,
            "war_relation": 0,
            "war_min_army": 6,
            "war_roll": 9,
            "trade_food": 180.0,
            "build_reserve": 20.0,
            "workers": {"agriculture": 0.6, "mining": 0.2, "construction": 0.2},
            "city_focus": None,
            "city_budget": None,
        },
    },
}


def normalize_personality(value: object) -> str:
    key = str(value or DEFAULT_PERSONALITY).strip().lower()
    return key if key in PERSONALITIES else DEFAULT_PERSONALITY


def personality_definition(value: object) -> dict[str, Any]:
    return PERSONALITIES[normalize_personality(value)]


def personality_label(value: object) -> str:
    return personality_definition(value)["label"]
