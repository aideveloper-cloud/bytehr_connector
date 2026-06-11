"""Low-level ByteHR Open API client.

Docs: https://developer.byte-hr.com/ (all endpoints are read-only GETs).
Auth: x-api-key header. The key expires after 1 year — diarise the renewal.

ByteHR enforces a HARD cap of 1,000 requests/month per API key; once hit,
the key is dead until next month. This client therefore keeps a persistent
per-month counter (DefaultValue table, survives restarts) and refuses to go
past a configurable budget so there is always headroom for manual testing.

Site Config keys:
  bytehr_enabled                 -> 1 to turn the integration on
  bytehr_api_key                 -> API key from the Open API add-on
  bytehr_api_base                -> base URL from ByteHR onboarding,
                                    e.g. https://xxx.byte-hr.com (no public default)
  bytehr_monthly_request_budget  -> optional, default 900 (of the 1,000 cap)
"""

import frappe
import requests
from frappe.utils import cint, nowdate


class BudgetExhausted(Exception):
    """Raised when the self-imposed monthly request budget is used up."""


def _conf(key, default=None):
    return frappe.conf.get(key, default)


def _counter_key():
    return "bytehr_requests_" + nowdate()[:7]


def used_this_month():
    return cint(frappe.db.get_default(_counter_key()))


def budget():
    return cint(_conf("bytehr_monthly_request_budget") or 900)


def get(path, params=None):
    used = used_this_month()
    if used >= budget():
        raise BudgetExhausted(
            f"ByteHR monthly request budget reached ({used}/{budget()})"
        )

    base = (_conf("bytehr_api_base") or "").rstrip("/")
    api_key = _conf("bytehr_api_key")
    if not base or not api_key:
        frappe.throw("Set bytehr_api_base and bytehr_api_key in Site Config")

    frappe.db.set_default(_counter_key(), used + 1)

    resp = requests.get(
        f"{base}{path}",
        headers={"x-api-key": api_key},
        params=params,
        timeout=60,
    )

    if not resp.ok:
        frappe.log_error(
            title=f"ByteHR API failed: GET {path}",
            message=f"HTTP {resp.status_code}\n{resp.text}",
        )
        resp.raise_for_status()

    return resp.json()


def iter_list(path, page_size=100, max_pages=5, params=None):
    """Yield records from a paginated endpoint (?limit=&currentpage=).

    limit maxes out at 100 per ByteHR docs — always use 100 to stretch the
    monthly quota. Wrapper shape isn't documented, so unwrap defensively.
    """
    page = 1
    while page <= max_pages:
        query = dict(params or {})
        query.update({"limit": page_size, "currentpage": page})
        body = get(path, params=query)

        data = body.get("data") if isinstance(body, dict) else body
        if isinstance(data, dict):
            batch = data.get("list") or data.get("items") or data.get("records") or []
        else:
            batch = data or []

        for record in batch:
            yield record
        if len(batch) < page_size:
            break
        page += 1
