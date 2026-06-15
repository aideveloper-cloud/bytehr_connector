"""Controlled, idempotent ingest endpoints — the entry point for n8n.

Architecture (per project directive 2026-06): n8n calls the ByteHR Open API
(no direct API calls from inside ERPNext), then POSTs the raw records here.
ERPNext owns the matching / mapping logic (reused from sync.py).

These REPLACE the in-ERPNext pull (sync.pull_all). When n8n is live, disable
it with Site Config `bytehr_enabled = 0` so the two don't both pull (ByteHR
has a hard 1,000 req/month cap — double-pulling wastes it fast).

Idempotent: upserts match existing records. Accepts a single record or a list.
Guarded: caller must hold a role in `bytehr_ingest_roles` (Site Config,
default "System Manager").
"""

import json

import frappe

from bytehr_connector.bytehr import sync


def _guard():
    roles = frappe.conf.get("bytehr_ingest_roles") or "System Manager"
    frappe.only_for([r.strip() for r in str(roles).split(",") if r.strip()])


def _records(payload):
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, dict):
        return [payload]
    return payload or []


@frappe.whitelist()
def ingest_employees(records):
    _guard()
    n = 0
    for rec in _records(records):
        sync._upsert_employee(rec)
        n += 1
    frappe.db.commit()
    return {"ingested": n}


@frappe.whitelist()
def ingest_timesheets(records):
    _guard()
    n = 0
    for rec in _records(records):
        sync._upsert_timesheet(rec)
        n += 1
    frappe.db.commit()
    return {"ingested": n}
