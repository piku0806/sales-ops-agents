"""Tool registry.

Tools come from two places:
  * the CRM MCP server: discovered at runtime via MCP `list_tools`, never hardcoded
  * local tools: public-web research (a stand-in for web grounding) and the email outbox

Every tool call goes through the governance gateway (governance.py). Agents never call
these handlers directly.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from salesops.config import PROJECT_ROOT, Settings, get_settings

Handler = Callable[[dict], Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Handler
    source: str  # "mcp:crm" or "local"
    untrusted_output: bool = False  # output comes from outside the org (web, email, docs)

    def openai_schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def schemas(self, names: list[str]) -> list[dict]:
        return [self.tools[n].openai_schema() for n in names if n in self.tools]


# --------------------------------------------------------------------------- research
def _research_db(settings: Settings) -> dict:
    return json.loads(settings.research_data.read_text())["companies"]


def _research_tools(settings: Settings) -> list[Tool]:
    data = _research_db(settings)

    async def get_company_profile(args: dict) -> str:
        entry = data.get(args["company"].strip().lower())
        return json.dumps(entry["profile"] if entry else {"error": "No public profile found"}, indent=2)

    async def search_company_news(args: dict) -> str:
        entry = data.get(args["company"].strip().lower())
        return json.dumps(entry["news"] if entry else [], indent=2)

    company_param = {"type": "object", "properties": {"company": {"type": "string"}}, "required": ["company"]}
    return [
        Tool("get_company_profile", "Public profile of a company: description, tech stack, known pain points.",
             company_param, get_company_profile, "local", untrusted_output=True),
        Tool("search_company_news", "Recent public news about a company, with the buying signal each implies.",
             company_param, search_company_news, "local", untrusted_output=True),
    ]


# --------------------------------------------------------------------------- email
def _email_tools(settings: Settings) -> list[Tool]:
    async def send_email(args: dict) -> str:
        # Mock delivery: writes to data/outbox. Swap for Microsoft Graph `sendMail` in production.
        settings.outbox_dir.mkdir(parents=True, exist_ok=True)
        msg_id = uuid.uuid4().hex[:8]
        record = {**args, "message_id": msg_id, "sent_at": datetime.now(timezone.utc).isoformat()}
        (settings.outbox_dir / f"{msg_id}.json").write_text(json.dumps(record, indent=2))
        return json.dumps({"status": "sent", "message_id": msg_id, "to": args["to"]})

    return [Tool(
        "send_email", "Send an email to a customer contact.",
        {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"},
                                          "body": {"type": "string"}, "account_name": {"type": "string"}},
         "required": ["to", "subject", "body", "account_name"]},
        send_email, "local")]


# --------------------------------------------------------------------------- MCP
def _mcp_server_params() -> StdioServerParameters:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return StdioServerParameters(command=sys.executable, args=["-m", "salesops.crm_server"], env=env)


def _mcp_text(result: Any) -> str:
    return "\n".join(getattr(c, "text", str(c)) for c in result.content)


async def _mcp_tools(session: ClientSession) -> list[Tool]:
    listed = await session.list_tools()
    tools = []
    for t in listed.tools:
        async def handler(args: dict, _name: str = t.name) -> str:
            return _mcp_text(await session.call_tool(_name, args))
        tools.append(Tool(t.name, t.description or "", t.inputSchema, handler, "mcp:crm"))
    return tools


@asynccontextmanager
async def tool_runtime(settings: Settings | None = None):
    """Open the CRM MCP session and yield a fully populated ToolRegistry."""
    settings = settings or get_settings()
    async with stdio_client(_mcp_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            registry = ToolRegistry()
            for tool in [*await _mcp_tools(session), *_research_tools(settings), *_email_tools(settings)]:
                registry.add(tool)
            yield registry
