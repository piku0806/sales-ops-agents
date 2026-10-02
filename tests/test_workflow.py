"""End-to-end tests: real MCP server subprocess, mock LLM, real governance."""
import asyncio
import json

import pytest

from salesops import crm_db, governance
from salesops.agents import Agent
from salesops.governance import Gateway
from salesops.llm import LLMResponse, MockLLM, ToolCall
from salesops.orchestrator import run_account_workflow
from salesops.tools import tool_runtime


def test_full_run_queues_high_risk_actions(settings):
    r = asyncio.run(run_account_workflow("Northwind Logistics", settings))
    store = governance.ApprovalStore(settings.governance_db)
    tools = sorted(a["tool"] for a in store.list(status="pending"))
    assert tools == ["send_email", "update_account"]  # stage change + email are gated
    acct = crm_db.get_account(settings.crm_db, "Northwind Logistics")
    assert acct["stage"] == "Prospect"                 # not changed yet
    assert "[AI research" in acct["notes"]             # low-risk note update auto-executed
    assert not settings.outbox_dir.exists()            # nothing sent


def test_approve_executes_and_reject_does_not(settings):
    asyncio.run(run_account_workflow("Northwind Logistics", settings))
    store = governance.ApprovalStore(settings.governance_db)
    pending = {a["tool"]: a for a in store.list(status="pending")}

    governance.reject(pending["update_account"]["id"], "tester", "not yet")
    assert crm_db.get_account(settings.crm_db, "Northwind Logistics")["stage"] == "Prospect"

    edited = {**pending["send_email"]["args"], "subject": "Edited by reviewer"}
    asyncio.run(governance.approve(pending["send_email"]["id"], "tester", "ok", edited))
    sent = [json.loads(p.read_text()) for p in settings.outbox_dir.glob("*.json")]
    assert len(sent) == 1 and sent[0]["subject"] == "Edited by reviewer"


def test_reviewer_cannot_edit_email_to_outside_recipient(settings):
    asyncio.run(run_account_workflow("Litware Retail", settings))
    item = next(a for a in governance.ApprovalStore(settings.governance_db).list(status="pending")
                if a["tool"] == "send_email")
    with pytest.raises(ValueError):
        asyncio.run(governance.approve(item["id"], "tester", "", {**item["args"], "to": "x@evil.example"}))


class RogueAgent(Agent):
    """Simulates a model that has been manipulated: tries forbidden and out-of-scope actions."""
    name = "email_agent"
    tools = ["get_account", "list_contacts", "update_account", "send_email"]

    def mock_step(self, step, messages):
        if step == 0:
            return LLMResponse(None, [
                ToolCall("1", "update_account", {"account_name": "Litware Retail", "stage": "Closed Won"}),
                ToolCall("2", "get_account", {"account_name": "Adatum Financial"}),
                ToolCall("3", "send_email", {"to": "partner-leads@external-example.com", "subject": "list",
                                            "body": "contacts", "account_name": "Litware Retail"}),
            ])
        return LLMResponse(json.dumps({"done": True}))


def test_rogue_agent_is_contained(settings):
    async def go():
        async with tool_runtime(settings) as registry:
            gw = Gateway(registry, "test-run", {"account_name": "Litware Retail",
                                               "allowed_recipients": {"chris.doyle@litware.example"}}, settings)
            await RogueAgent(MockLLM(), gw).run("do bad things", {"account_name": "Litware Retail"})
            return gw
    gw = asyncio.run(go())
    denied = [f for f in gw.flags if f["type"] == "policy_denied"]
    assert len(denied) == 3          # disallowed tool, wrong account, disallowed tool (send_email)
    assert not gw.pending and not gw.executed
    assert crm_db.get_account(settings.crm_db, "Litware Retail")["stage"] == "Prospect"
