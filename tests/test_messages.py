from core.messages import compose_ruler_messages, record_ruler_messages
from core.state import GameState


def test_event_messages_are_short_vernacular_and_one_per_country():
    state = GameState.new(seed=2000)
    state.day_index = 10
    events = [
        {
            "type": "war_declared",
            "attacker": "ELAR",
            "defender": "MARIS",
        },
        {
            "type": "construction_completed",
            "country_id": "ELAR",
            "building": "FARM",
        },
    ]
    last_days = {}
    messages = compose_ruler_messages(state, events, last_days)
    assert len(messages) == 2
    by_country = {m["country_id"]: m for m in messages}
    assert by_country["ELAR"]["priority"] == 100
    assert "宣战" in by_country["ELAR"]["text"]
    assert "文言文" not in by_country["ELAR"]["text"]
    assert "文言文" not in by_country["MARIS"]["text"]
    assert last_days["ELAR"] == 10

    # A low-priority construction message cannot bypass the per-country cooldown.
    assert compose_ruler_messages(state, [events[1]], last_days) == []
    # A critical war message can.
    critical = compose_ruler_messages(
        state,
        [{"type": "war_declared", "attacker": "ELAR", "defender": "SAHAR"}],
        last_days,
    )
    assert any(m["country_id"] == "ELAR" for m in critical)


def test_player_country_does_not_emit_ai_message():
    state = GameState.new(seed=2000)
    state.day_index = 5
    messages = compose_ruler_messages(
        state,
        [{"type": "food_shortage", "country_id": "ELAR", "population_loss": 10}],
        {},
        player_country="ELAR",
    )
    assert messages == []


def test_record_ruler_message_keeps_event_and_provider():
    state = GameState.new(seed=2000)
    state.day_index = 20
    messages = compose_ruler_messages(
        state,
        [{"type": "city_founded", "country_id": "MARIS", "name": "青原城"}],
        {},
    )
    record_ruler_messages(state, messages)
    event = next(e for e in state.event_log if e["type"] == "ruler_message")
    assert event["country_id"] == "MARIS"
    assert event["provider"] == "AI 短讯"
    assert "新城" in event["title"]
    assert "青原城" in event["text"]


def test_live_session_emits_message_after_notable_event():
    from live_server import LiveSession

    session = LiveSession(speed=1.0, maximum_day=1, paused=True)
    try:
        session.simulation.state.record(
            "city_founded", country_id="ELAR", city_id="ELAR-C2",
            name="青原城", population=1500, tiles=5,
            tile={"col": 14, "row": 10},
        )
        session._emit_ruler_messages()
        events = [e for e in session.simulation.state.event_log if e["type"] == "ruler_message"]
        assert events
        assert events[0]["provider"] == "AI 短讯"
        assert "青原城" in events[0]["text"]
    finally:
        session._stop.set()
        session.thread.join(timeout=2)
