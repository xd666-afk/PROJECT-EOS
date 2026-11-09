"""Data-driven presets for the simple "paste one API key" setup flow."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROVIDERS = BASE_DIR / "config" / "llm_providers.json"


def load_provider_presets(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    source = Path(path) if path is not None else DEFAULT_PROVIDERS
    data = json.loads(source.read_text(encoding="utf-8"))
    providers = data.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("llm provider presets must contain a non-empty providers object")
    normalized: dict[str, dict[str, Any]] = {}
    for provider_id, raw in providers.items():
        if not isinstance(provider_id, str) or not provider_id:
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"provider {provider_id} preset must be an object")
        label = str(raw.get("label") or provider_id)
        base_url = str(raw.get("base_url") or "")
        model = str(raw.get("model") or "")
        if not base_url.startswith(("https://", "http://")) or not model:
            raise ValueError(f"provider {provider_id} needs HTTP(S) base_url and model")
        normalized[provider_id] = {
            "id": provider_id,
            "label": label,
            "base_url": base_url,
            "model": model,
            "docs_url": str(raw.get("docs_url") or ""),
            "timeout_seconds": float(raw.get("timeout_seconds", 45)),
            "retries": int(raw.get("retries", 0)),
            "max_output_tokens": int(raw.get("max_output_tokens", 4000)),
        }
    return normalized


def provider_payload(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Safe public presets for the local UI; never contains credentials."""
    return list(load_provider_presets(path).values())


def resolve_simple_settings(
    country_id: str,
    provider_id: str,
    path: str | Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Return preset plus the per-country env-var name for an in-memory key."""
    providers = load_provider_presets(path)
    preset = providers.get(provider_id)
    if preset is None:
        raise ValueError("unknown provider preset")
    env_name = f"EOS_AGENT_{country_id}_API_KEY"
    return preset, env_name
