"""Budgeted OpenAI-compatible JSON-action adapter with no third-party HTTP dependency."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
from urllib import error, request

from agents.base import CountryAgent
from agents.heuristic import HeuristicAgent


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass
class CallBudget:
    max_calls: int | None = None
    max_cost_usd: float | None = None
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unknown_usage_calls: int = 0
    unknown_cost_calls: int = 0
    known_cost_usd: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reserve(self) -> None:
        with self._lock:
            # Real paid calls are opt-in: both limits must be explicitly configured.
            if self.max_calls is None or self.max_cost_usd is None:
                raise BudgetExceeded("真实 API 调用需要同时设置 --max-calls 与 --max-cost-usd")
            if self.max_calls < 0 or self.max_cost_usd < 0:
                raise BudgetExceeded("调用与费用预算必须非负")
            if self.calls >= self.max_calls:
                raise BudgetExceeded("API 调用次数预算已用尽")
            if self.known_cost_usd >= self.max_cost_usd:
                raise BudgetExceeded("API 已知费用预算已用尽")
            self.calls += 1

    def record(
        self,
        usage: dict[str, Any] | None,
        input_price_per_million: float | None,
        output_price_per_million: float | None,
    ) -> float | None:
        with self._lock:
            prompt = usage.get("prompt_tokens") if usage else None
            completion = usage.get("completion_tokens") if usage else None
            valid_prompt = isinstance(prompt, int) and not isinstance(prompt, bool) and prompt >= 0
            valid_completion = isinstance(completion, int) and not isinstance(completion, bool) and completion >= 0
            if not valid_prompt or not valid_completion:
                self.unknown_usage_calls += 1
                self.unknown_cost_calls += 1
                return None
            self.input_tokens += prompt
            self.output_tokens += completion
            if input_price_per_million is None or output_price_per_million is None:
                self.unknown_cost_calls += 1
                return None
            cost = (
                prompt * input_price_per_million + completion * output_price_per_million
            ) / 1_000_000.0
            self.known_cost_usd += cost
            return cost

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": "llm_budget" if self.max_calls is not None or self.max_cost_usd is not None else "mock_only_or_unconfigured",
                "max_calls": self.max_calls,
                "max_cost_usd": self.max_cost_usd,
                "http_attempts": self.calls,
                "input_tokens_known_total": self.input_tokens,
                "output_tokens_known_total": self.output_tokens,
                "unknown_usage_calls": self.unknown_usage_calls,
                "unknown_cost_calls": self.unknown_cost_calls,
                "known_estimated_cost_usd": self.known_cost_usd,
                "cost_note": "费用仅按配置单价和供应商 usage 估算；unknown 不视为零费用",
            }


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    base_url: str
    api_key_env: str
    timeout_seconds: float = 20.0
    retries: int = 1
    max_output_tokens: int = 700
    input_price_per_million_usd: float | None = None
    output_price_per_million_usd: float | None = None

    @classmethod
    def from_dict(cls, country_id: str, data: dict[str, Any]) -> "LLMSettings":
        settings = cls(
            provider=str(data["provider"]),
            model=str(data["model"]),
            base_url=str(data["base_url"]),
            api_key_env=str(data.get("api_key_env", f"EOS_AGENT_{country_id}_API_KEY")),
            timeout_seconds=float(data.get("timeout_seconds", 20)),
            retries=int(data.get("retries", 1)),
            max_output_tokens=int(data.get("max_output_tokens", 700)),
            input_price_per_million_usd=data.get("input_price_per_million_usd"),
            output_price_per_million_usd=data.get("output_price_per_million_usd"),
        )
        if not settings.base_url.startswith(("https://", "http://")):
            raise ValueError("LLM base_url must use HTTP(S)")
        if not 0 < settings.timeout_seconds <= 120:
            raise ValueError("LLM timeout must be in (0, 120]")
        if not 0 <= settings.retries <= 3 or not 1 <= settings.max_output_tokens <= 4000:
            raise ValueError("invalid retry or output-token limit")
        return settings

    @property
    def endpoint(self) -> str:
        if self.base_url.rstrip("/").endswith("/chat/completions"):
            return self.base_url.rstrip("/")
        return self.base_url.rstrip("/") + "/chat/completions"


class OpenAICompatibleAgent(CountryAgent):
    def __init__(self, country_id: str, settings: LLMSettings, budget: CallBudget) -> None:
        self.country_id = country_id
        self.settings = settings
        self.budget = budget
        self._usage_events: list[dict[str, Any]] = []
        self._usage_lock = threading.Lock()

    def drain_usage_events(self) -> list[dict[str, Any]]:
        with self._usage_lock:
            events = self._usage_events
            self._usage_events = []
            return events

    def _usage_event(self, status: str, **payload: Any) -> None:
        event = {
            "provider": self.settings.provider,
            "model": self.settings.model,
            "status": status,
            **payload,
        }
        with self._usage_lock:
            self._usage_events.append(event)

    async def decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._decide_with_retries, observation)

    def _decision_request(self, observation: dict[str, Any]) -> dict[str, Any]:
        system = (
            "Output one json object only. 你是国家策略控制器。只返回一个 JSON 对象，不要 Markdown。"
            "结构为 country_id, world_day, actions, reason, diary。country_id 与 world_day 必须复制观察值。"
            "diary 必须是对象：{title: 不超过20字, mood: 2-6字, text: 120-260字第一人称统治日记}。"
            "text 要写清当前最关心的局势、为什么采取这些动作、放弃了什么、下一步计划；"
            "写公开的决策叙事，不要逐步推理链，不要编造观察中不存在的数字。"
            "actions 最多4项，只允许 BUILD(tile,building), SETTLE(tile) 用于开拓相邻无主地块, "
            "ALLOCATE_WORKERS(agriculture,mining,construction), SET_TAX(rate), "
            "SET_RESEARCH(field), SET_POLICY(priority), "
            "TRADE(operation,target,offer_food,request_treasury 或 operation,proposal_id), "
            "DIPLOMACY(GIFT/PROPOSE_PACT/ACCEPT_PACT/REJECT_PACT/DECLARE_WAR/PROPOSE_PEACE), "
            "MILITARY(RECRUIT/MARCH/ATTACK), "
            "SET_CITY_FOCUS(city_id,focus), SET_CITY_ZONE(city_id,tile,zone), "
            "SET_CITY_BUDGET(city_id,austerity|balanced|investment), NO_OP。"
            "不得输出代码、密钥或修改规则；无法决定时返回 NO_OP。"
        )
        return {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(observation, ensure_ascii=False, separators=(",", ":"))},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": self.settings.max_output_tokens,
        }

    def _post(self, observation: dict[str, Any]) -> dict[str, Any]:
        api_key = os.environ.get(self.settings.api_key_env) or os.environ.get("EOS_API_KEY")
        if not api_key:
            raise LLMError("未配置 API 密钥环境变量")
        req = request.Request(
            self.settings.endpoint,
            data=json.dumps(self._decision_request(observation), ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.settings.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _parse_response(response: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("供应商响应缺少 choices[0].message.content") from exc
        if not isinstance(content, str):
            raise LLMError("模型 content 不是字符串")
        stripped = content.strip()
        if stripped.startswith("```"):
            raise LLMError("模型返回了 Markdown 代码围栏而非纯 JSON")
        try:
            decision = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise LLMError("模型未返回有效 JSON") from exc
        if not isinstance(decision, dict) or not isinstance(decision.get("actions"), list):
            raise LLMError("模型决议缺少 actions 数组")
        if decision.get("country_id") != observation["country_id"]:
            raise LLMError("模型决议 country_id 不匹配")
        if decision.get("world_day") != observation["world_day"]:
            raise LLMError("模型决议 world_day 不匹配")
        return decision

    def _decide_with_retries(self, observation: dict[str, Any]) -> dict[str, Any]:
        if not (os.environ.get(self.settings.api_key_env) or os.environ.get("EOS_API_KEY")):
            self._usage_event("error", error_type="MissingAPIKey", retryable=False)
            raise LLMError("未配置 API 密钥环境变量")
        last_error: Exception | None = None
        for attempt in range(self.settings.retries + 1):
            started = time.perf_counter()
            usage = None
            cost = None
            try:
                self.budget.reserve()
                response = self._post(observation)
                if not isinstance(response, dict):
                    raise LLMError("供应商响应不是 JSON 对象")
                usage = response.get("usage") if isinstance(response.get("usage"), dict) else None
                # Record billable usage even when the model's decision is malformed.
                cost = self.budget.record(
                    usage,
                    self.settings.input_price_per_million_usd,
                    self.settings.output_price_per_million_usd,
                )
                decision = self._parse_response(response, observation)
                self._usage_event(
                    "success", attempt=attempt + 1,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    usage=usage if usage is not None else "unknown",
                    estimated_cost_usd=cost if cost is not None else "unknown",
                )
                return decision
            except (LLMError, error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                retryable = (
                    not isinstance(exc, BudgetExceeded)
                    and (not isinstance(exc, error.HTTPError) or exc.code == 429 or exc.code >= 500)
                )
                payload = {}
                if usage is not None or cost is not None:
                    payload = {
                        "usage": usage if usage is not None else "unknown",
                        "estimated_cost_usd": cost if cost is not None else "unknown",
                    }
                self._usage_event(
                    "error", attempt=attempt + 1,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    error_type=type(exc).__name__,
                    http_status=exc.code if isinstance(exc, error.HTTPError) else None,
                    retryable=retryable,
                    **payload,
                )
                if attempt >= self.settings.retries or not retryable:
                    break
                time.sleep(0.2 * (2 ** attempt))
        raise LLMError(f"LLM 决策失败: {type(last_error).__name__}") from last_error


def load_agents(path: str | Path, budget: CallBudget) -> dict[str, CountryAgent]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    agents: dict[str, CountryAgent] = {}
    for country_id, config in data["countries"].items():
        mode = config.get("mode", "mock")
        if mode == "mock":
            agents[country_id] = HeuristicAgent(country_id)
        elif mode == "openai_compatible":
            agents[country_id] = OpenAICompatibleAgent(
                country_id, LLMSettings.from_dict(country_id, config), budget
            )
        else:
            raise ValueError(f"unsupported agent mode: {mode}")
    return agents
