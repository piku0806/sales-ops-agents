"""Command-line interface.

    python -m salesops init                      # reset the demo CRM and governance state
    python -m salesops accounts                  # list CRM accounts
    python -m salesops run "Northwind Logistics" # run the multi-agent workflow
    python -m salesops approvals                 # list pending approvals
    python -m salesops approve <id> --reviewer sam --note "looks good"
    python -m salesops reject  <id> --reviewer sam --note "wrong contact"
    python -m salesops audit <run_id>            # show the audit trail for a run
    python -m salesops ui                        # approval queue web UI on http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import textwrap

from salesops import crm_db, governance
from salesops.config import get_settings


def _hr(title: str = "") -> None:
    print(f"\n── {title} " + "─" * max(0, 70 - len(title)))


def cmd_init(_args) -> None:
    s = get_settings()
    for p in (s.governance_db, s.audit_log):
        p.unlink(missing_ok=True)
    for d in (s.outbox_dir, s.data_dir / "runs"):
        shutil.rmtree(d, ignore_errors=True)
    crm_db.init_db(s.crm_db, reset=True)
    print(f"Demo data reset in {s.data_dir}")


def cmd_accounts(_args) -> None:
    s = get_settings()
    crm_db.init_db(s.crm_db)
    for a in crm_db.list_accounts(s.crm_db):
        print(f"  {a['name']:<26} {a['stage']:<12} {a['industry']:<20} {a['owner']}")


def cmd_run(args) -> None:
    from salesops.orchestrator import run_account_workflow

    r = asyncio.run(run_account_workflow(args.account))
    _hr(f"Run {r['run_id']} · {r['account']} · model={r['model']}")
    b = r["research_brief"]
    print(textwrap.fill(b.get("summary", ""), 88))
    for sgl in b.get("buying_signals", []):
        print(f"  • [{sgl['signal']}] {sgl['evidence']}")
    for risk in b.get("risks", []):
        print(f"  ⚠ {risk}")

    _hr("CRM agent")
    for a in r["crm_update"].get("actions", []):
        print(f"  {a['status']:<17} {a['tool']} ({a['detail']})")

    _hr("Email draft (not sent: awaiting approval)")
    d = r["email_draft"]
    print(f"  To: {d.get('contact_name')} <{d.get('to')}>\n  Subject: {d.get('subject')}\n")
    print(textwrap.indent(d.get("body", ""), "  "))

    _hr("Governance")
    for f in r["guardrail_flags"]:
        print(f"  ⚑ {f['type']}: {f.get('matches') or f.get('reason')}")
    print(f"  Pending approvals: {', '.join(r['pending_approvals']) or 'none'}")
    print("  Review them with:  python -m salesops approvals   or   python -m salesops ui")


def cmd_approvals(args) -> None:
    store = governance.ApprovalStore(get_settings().governance_db)
    items = store.list(status=None if args.all else "pending")
    if not items:
        print("No pending approvals." if not args.all else "No approvals yet.")
        return
    for it in items:
        _hr(f"{it['id']} · {it['status']} · {it['tool']} · {it['context']['account_name']}")
        print(f"  requested by: {it['agent']}   risk: {it['risk']}   why: {it['reason']}")
        for fl in it["flags"] or []:
            print(f"  ⚑ {fl}")
        args_ = {k: v for k, v in it["args"].items() if k != "account_name"}
        if it["tool"] == "send_email":
            print(f"  To: {args_['to']}\n  Subject: {args_['subject']}\n" + textwrap.indent(args_["body"], "  | "))
        else:
            print("  " + json.dumps(args_))
        if it["status"] != "pending":
            print(f"  decided by {it['reviewer']}: {it['rationale'] or ''}")


def cmd_approve(args) -> None:
    res = asyncio.run(governance.approve(args.id, args.reviewer, args.note))
    print(f"Approved and executed {res['id']}: {res['result']}")


def cmd_reject(args) -> None:
    governance.reject(args.id, args.reviewer, args.note)
    print(f"Rejected {args.id}")


def cmd_audit(args) -> None:
    for e in governance.AuditLog(get_settings().audit_log).read(args.run_id):
        extra = {k: v for k, v in e.items() if k not in ("ts", "run_id", "event")}
        print(f"{e['ts']}  {e['event']:<19} {json.dumps(extra, default=str)[:150]}")


def cmd_ui(args) -> None:
    import uvicorn

    uvicorn.run("salesops.approvals_ui:app", host=args.host, port=args.port)


def main() -> None:
    p = argparse.ArgumentParser(prog="salesops", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("accounts").set_defaults(fn=cmd_accounts)
    r = sub.add_parser("run"); r.add_argument("account"); r.set_defaults(fn=cmd_run)
    a = sub.add_parser("approvals"); a.add_argument("--all", action="store_true"); a.set_defaults(fn=cmd_approvals)
    for name, fn in (("approve", cmd_approve), ("reject", cmd_reject)):
        x = sub.add_parser(name); x.add_argument("id"); x.add_argument("--reviewer", required=True)
        x.add_argument("--note", default=""); x.set_defaults(fn=fn)
    au = sub.add_parser("audit"); au.add_argument("run_id", nargs="?"); au.set_defaults(fn=cmd_audit)
    u = sub.add_parser("ui"); u.add_argument("--host", default="127.0.0.1"); u.add_argument("--port", type=int, default=8000)
    u.set_defaults(fn=cmd_ui)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
