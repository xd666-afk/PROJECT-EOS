import json
import os

from agents.providers import load_provider_presets, provider_payload, resolve_simple_settings
from live_server import LiveSession


def test_provider_presets_cover_requested_companies():
    providers = load_provider_presets()
    assert {"deepseek", "doubao", "qwen", "kimi", "glm", "minimax"} <= set(providers)
    assert providers["doubao"]["base_url"].startswith("https://ark.cn-beijing.volces.com/")
    assert providers["qwen"]["base_url"].startswith("https://dashscope.aliyuncs.com/")
    assert providers["kimi"]["base_url"].startswith("https://api.moonshot.cn/")
    assert providers["glm"]["base_url"].startswith("https://open.bigmodel.cn/")
    assert providers["minimax"]["base_url"].startswith("https://api.minimax.cn/")
    public = provider_payload()
    assert all("api_key" not in item for item in public)
    assert all(item["model"] for item in public)
    preset, env_name = resolve_simple_settings("ELAR", "qwen")
    assert preset["model"] == "qwen-plus"
    assert env_name == "EOS_AGENT_ELAR_API_KEY"


def test_simple_provider_key_stays_in_process_memory(monkeypatch):
    monkeypatch.delenv("EOS_AGENT_ELAR_API_KEY", raising=False)
    monkeypatch.delenv("EOS_API_KEY", raising=False)
    session = LiveSession(speed=1.0, maximum_day=1, paused=True)
    try:
        missing = session.configure_agent(
            "ELAR", {"mode": "openai_compatible", "provider_id": "qwen"}
        )
        assert not missing["ok"] and "API Key" in missing["error"]
        result = session.configure_agent(
            "ELAR",
            {
                "mode": "openai_compatible",
                "provider_id": "qwen",
                "api_key": "unit-test-secret-key",
            },
        )
        assert result["ok"]
        assert session.agent_meta["ELAR"]["provider_id"] == "qwen"
        assert session.agent_meta["ELAR"]["provider"] == "阿里千问"
        assert os.environ["EOS_AGENT_ELAR_API_KEY"] == "unit-test-secret-key"
        payload = json.dumps(session.agent_payload(), ensure_ascii=False)
        assert "unit-test-secret-key" not in payload
        assert "providers" in session.agent_payload()
        switched = session.configure_agent(
            "ELAR", {"mode": "openai_compatible", "provider_id": "doubao"}
        )
        assert not switched["ok"] and "重新填写" in switched["error"]
    finally:
        session._stop.set()
        session.thread.join(timeout=2)
        monkeypatch.delenv("EOS_AGENT_ELAR_API_KEY", raising=False)
