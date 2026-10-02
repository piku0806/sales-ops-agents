"""LLM clients.

* AzureFoundryLLM: calls a model deployed in your Microsoft Foundry project (Azure OpenAI
  chat-completions API with tool calling). Auth is API key or, preferably, Microsoft Entra ID
  (keyless, via DefaultAzureCredential).
* MockLLM: deterministic, offline. Each agent provides a scripted policy, so the whole
  workflow (tool calls, approvals, guardrails) can be demoed and tested without an API key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from salesops.config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    def as_message(self) -> dict:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": tc.id, "type": "function",
                                  "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                                 for tc in self.tool_calls]
        return msg


class LLM(Protocol):
    name: str

    def chat(self, messages: list[dict], tools: list[dict], agent: Any) -> LLMResponse: ...


class AzureFoundryLLM:
    def __init__(self, settings: Settings):
        from openai import AzureOpenAI

        if not (settings.azure_endpoint and settings.azure_deployment):
            raise RuntimeError("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT (see .env.example)")
        if settings.azure_api_key:
            self.client = AzureOpenAI(azure_endpoint=settings.azure_endpoint, api_key=settings.azure_api_key,
                                      api_version=settings.azure_api_version)
        else:  # keyless: Entra ID via `az login`, managed identity, etc.
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            token_provider = get_bearer_token_provider(DefaultAzureCredential(),
                                                       "https://cognitiveservices.azure.com/.default")
            self.client = AzureOpenAI(azure_endpoint=settings.azure_endpoint, azure_ad_token_provider=token_provider,
                                      api_version=settings.azure_api_version)
        self.deployment = settings.azure_deployment
        self.name = f"azure:{self.deployment}"

    def chat(self, messages: list[dict], tools: list[dict], agent: Any) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": self.deployment, "messages": messages, "temperature": 0.2}
        if tools:
            kwargs["tools"] = tools
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens} \
            if resp.usage else {}
        return LLMResponse(msg.content, calls, usage)


class MockLLM:
    name = "mock"

    def chat(self, messages: list[dict], tools: list[dict], agent: Any) -> LLMResponse:
        step = sum(1 for m in messages if m["role"] == "assistant")
        return agent.mock_step(step, messages)


def get_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "azure":
        return AzureFoundryLLM(settings)
    return MockLLM()
