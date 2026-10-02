"""A small SQLite-backed mock CRM.

Stands in for Salesforce / Dynamics 365. The MCP server (crm_server.py) is the only
component that talks to this module, the same way a real CRM would sit behind an
MCP server or API gateway in production.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

SEED_FILE = Path(__file__).parent / "seed" / "crm_seed.json"

# Fields an agent is ever allowed to change. Anything else is rejected at the data layer,
# as a second line of defence behind the governance gateway.
UPDATABLE_FIELDS = {"stage", "notes", "next_step", "arr_potential"}
VALID_STAGES = ["Prospect", "Qualified", "Proposal", "Negotiation", "Closed Won", "Closed Lost"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    industry TEXT, employees INTEGER, region TEXT,
    stage TEXT NOT NULL, owner TEXT, arr_potential INTEGER,
    notes TEXT DEFAULT '', next_step TEXT DEFAULT '',
    last_updated TEXT
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    name TEXT, title TEXT, email TEXT
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    type TEXT, summary TEXT, created_at TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path, reset: bool = False) -> None:
    if reset and db_path.exists():
        db_path.unlink()
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
            return
        seed = json.loads(SEED_FILE.read_text())
        for acct in seed["accounts"]:
            cur = conn.execute(
                "INSERT INTO accounts (name, industry, employees, region, stage, owner, arr_potential,"
                " notes, next_step, last_updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (acct["name"], acct["industry"], acct["employees"], acct["region"], acct["stage"],
                 acct["owner"], acct["arr_potential"], acct["notes"], acct["next_step"], "2026-09-01"),
            )
            aid = cur.lastrowid
            for c in acct["contacts"]:
                conn.execute("INSERT INTO contacts (account_id, name, title, email) VALUES (?,?,?,?)",
                             (aid, c["name"], c["title"], c["email"]))
            for a in acct["activities"]:
                conn.execute("INSERT INTO activities (account_id, type, summary, created_at) VALUES (?,?,?,?)",
                             (aid, a["type"], a["summary"], a["created_at"]))


def _account_row(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM accounts WHERE lower(name) = lower(?)", (name.strip(),)).fetchone()


def get_account(db_path: Path, name: str) -> dict | None:
    with connect(db_path) as conn:
        row = _account_row(conn, name)
        return dict(row) if row else None


def list_accounts(db_path: Path) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT name, stage, industry, owner FROM accounts ORDER BY name")]


def list_contacts(db_path: Path, account_name: str) -> list[dict]:
    with connect(db_path) as conn:
        row = _account_row(conn, account_name)
        if not row:
            return []
        return [dict(r) for r in conn.execute(
            "SELECT name, title, email FROM contacts WHERE account_id = ?", (row["id"],))]


def recent_activities(db_path: Path, account_name: str, limit: int = 10) -> list[dict]:
    with connect(db_path) as conn:
        row = _account_row(conn, account_name)
        if not row:
            return []
        return [dict(r) for r in conn.execute(
            "SELECT type, summary, created_at FROM activities WHERE account_id = ?"
            " ORDER BY created_at DESC, id DESC LIMIT ?", (row["id"], limit))]


def update_account(db_path: Path, account_name: str, fields: dict) -> dict:
    bad = set(fields) - UPDATABLE_FIELDS
    if bad:
        raise ValueError(f"Fields not updatable: {sorted(bad)}")
    if "stage" in fields and fields["stage"] not in VALID_STAGES:
        raise ValueError(f"Invalid stage {fields['stage']!r}; valid: {VALID_STAGES}")
    with connect(db_path) as conn:
        row = _account_row(conn, account_name)
        if not row:
            raise ValueError(f"Unknown account {account_name!r}")
        before = {k: row[k] for k in fields}
        sets = ", ".join(f"{k} = ?" for k in fields) + ", last_updated = ?"
        conn.execute(f"UPDATE accounts SET {sets} WHERE id = ?",
                     (*fields.values(), date.today().isoformat(), row["id"]))
        return {"account": row["name"], "before": before, "after": fields}


def log_activity(db_path: Path, account_name: str, type_: str, summary: str) -> dict:
    with connect(db_path) as conn:
        row = _account_row(conn, account_name)
        if not row:
            raise ValueError(f"Unknown account {account_name!r}")
        cur = conn.execute("INSERT INTO activities (account_id, type, summary, created_at) VALUES (?,?,?,?)",
                           (row["id"], type_, summary, date.today().isoformat()))
        return {"activity_id": cur.lastrowid, "account": row["name"]}
