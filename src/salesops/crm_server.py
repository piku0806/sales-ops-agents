"""MCP server exposing the CRM as tools.

Agents never touch the CRM database directly: they reach it through this MCP server,
which is how you'd wrap Salesforce or Dynamics 365 for a customer deployment.

Run locally over stdio (the default, used by the orchestrator):
    python -m salesops.crm_server

Or host it remotely so a Microsoft Foundry agent / Toolbox can register it:
    python -m salesops.crm_server --transport streamable-http
"""
from __future__ import annotations

import argparse
import json

from mcp.server.fastmcp import FastMCP

from salesops import crm_db
from salesops.config import get_settings

settings = get_settings()
crm_db.init_db(settings.crm_db)
DB = settings.crm_db

mcp = FastMCP("salesops-crm", log_level="WARNING")


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, default=str)


@mcp.tool()
def get_account(account_name: str) -> str:
    """Get a CRM account record (stage, owner, notes, next step, ARR potential) by name."""
    acct = crm_db.get_account(DB, account_name)
    return _dump(acct) if acct else _dump({"error": f"No account named {account_name!r}"})


@mcp.tool()
def list_contacts(account_name: str) -> str:
    """List the contacts (name, title, email) stored in the CRM for an account."""
    return _dump(crm_db.list_contacts(DB, account_name))


@mcp.tool()
def get_recent_activities(account_name: str, limit: int = 10) -> str:
    """List recent CRM activities (calls, emails, meetings) for an account, newest first."""
    return _dump(crm_db.recent_activities(DB, account_name, limit))


@mcp.tool()
def update_account(account_name: str, stage: str | None = None, notes: str | None = None,
                   next_step: str | None = None, arr_potential: int | None = None) -> str:
    """Update CRM fields on an account. Only stage, notes, next_step and arr_potential can change."""
    fields = {k: v for k, v in {"stage": stage, "notes": notes, "next_step": next_step,
                                "arr_potential": arr_potential}.items() if v is not None}
    if not fields:
        return _dump({"error": "No fields supplied"})
    try:
        return _dump(crm_db.update_account(DB, account_name, fields))
    except ValueError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def log_activity(account_name: str, activity_type: str, summary: str) -> str:
    """Log an activity (e.g. research, email, call) against an account."""
    try:
        return _dump(crm_db.log_activity(DB, account_name, activity_type, summary))
    except ValueError as e:
        return _dump({"error": str(e)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
