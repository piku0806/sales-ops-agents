"""Supervisor: runs the specialist agents in a fixed, auditable sequence.

    research_agent  ->  crm_agent  ->  email_agent  ->  supervisor submits send_email for approval

Design choice: the supervisor is a deterministic workflow, not a free-roaming planner LLM.
Each agent reasons and uses tools autonomously *within* its step, but the order of steps,
the hand-offs between agents and the approval gates are fixed in code. That keeps runs
predictable, easy to audit and easy to evaluate, which is what enterprise customers need
before they let agents touch a CRM or email their clients.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from salesops import crm_db
from salesops.agents import CRMAgent, EmailAgent, ResearchAgent
from salesops.config import Settings, get_settings
from salesops.governance import Gateway
from salesops.llm import get_llm
from salesops.tools import tool_runtime


async def run_account_workflow(account_name: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    crm_db.init_db(settings.crm_db)
    account = crm_db.get_account(settings.crm_db, account_name)
    if not account:
        raise ValueError(f"Unknown account {account_name!r}. Try: "
                         + ", ".join(a["name"] for a in crm_db.list_accounts(settings.crm_db)))
    account_name = account["name"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    llm = get_llm(settings)

    async with tool_runtime(settings) as registry:
        # System-level (trusted) read to build the recipient allowlist; agents cannot change it.
        contacts = json.loads(await registry.get("list_contacts").handler({"account_name": account_name}))
        scope = {"account_name": account_name, "allowed_recipients": {c["email"].lower() for c in contacts}}
        gw = Gateway(registry, run_id, scope, settings)
        gw.audit.log(run_id, "run_started", account=account_name, model=llm.name,
                     allowed_recipients=sorted(scope["allowed_recipients"]))

        brief = await ResearchAgent(llm, gw).run(
            f"Research {account_name} and produce a research brief.", {"account_name": account_name})

        crm = await CRMAgent(llm, gw).run(
            f"Update the CRM for {account_name} based on the research brief.",
            {"account_name": account_name, "research_brief": brief})

        draft = await EmailAgent(llm, gw).run(
            f"Draft an outreach email for {account_name}.",
            {"account_name": account_name, "research_brief": brief})

        email_result = None
        if draft.get("to") and draft.get("body"):
            email_result = await gw.call("supervisor", "send_email", {
                "to": draft["to"], "subject": draft.get("subject", ""), "body": draft["body"],
                "account_name": account_name}, rationale=draft.get("rationale"))

        report = {
            "run_id": run_id, "account": account_name, "model": llm.name,
            "research_brief": brief, "crm_update": crm, "email_draft": draft,
            "email_submission": email_result,
            "pending_approvals": gw.pending, "executed_actions": gw.executed, "guardrail_flags": gw.flags,
        }
        gw.audit.log(run_id, "run_finished", pending_approvals=gw.pending, flags=len(gw.flags))

    runs_dir = settings.data_dir / "runs"
    runs_dir.mkdir(exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps(report, indent=2, default=str))
    return report
