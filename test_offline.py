"""Offline harness: stubs frappe/requests, then exercises client.iter_list
unwrapping, the budget guard, and sync field-picking. Run: python test_offline.py
"""
import sys
import types

defaults_store = {}

frappe = types.ModuleType("frappe")
frappe.conf = {"bytehr_api_key": "k", "bytehr_enabled": 1}
frappe.utils = types.SimpleNamespace(
    cint=lambda v: int(v or 0),
    nowdate=lambda: "2026-06-11",
    now=lambda: "2026-06-11 12:00:00",
)
frappe.db = types.SimpleNamespace(
    get_default=lambda k: defaults_store.get(k),
    set_default=lambda k, v: defaults_store.__setitem__(k, v),
)
frappe.throw = lambda msg: (_ for _ in ()).throw(Exception(msg))
frappe.log_error = lambda **kw: None
sys.modules["frappe"] = frappe
sys.modules["frappe.utils"] = frappe.utils

requests_mod = types.ModuleType("requests")
sys.modules["requests"] = requests_mod

sys.path.insert(0, ".")
from bytehr_connector.bytehr import client, sync

calls = []

def fake_get(url, headers=None, params=None, timeout=None):
    calls.append((url, dict(params)))
    page = params["currentpage"]
    style = fake_get.style
    if style == "pascal":
        body = {"StatusCode": 200, "Message": None,
                "Data": [{"Id": i, "FirstName": f"A{i}", "LastName": "B"} for i in range(3)]}
    elif style == "camel_nested":
        body = {"data": {"list": [{"id": i, "name": f"emp{i}"} for i in range(3)]}}
    elif style == "raw_array":
        body = [{"employeeId": i, "fullName": f"emp{i}"} for i in range(3)]
    elif style == "paged":
        n = 2 if page == 1 else 1
        body = {"Data": [{"Id": (page - 1) * 2 + i} for i in range(n)]}
    resp = types.SimpleNamespace(ok=True, status_code=200, text="", json=lambda: body)
    return resp

requests_mod.get = fake_get

failures = []

def check(label, got, want):
    status = "PASS" if got == want else "FAIL"
    if status == "FAIL":
        failures.append(label)
    print(f"{status} {label}: got={got!r} want={want!r}")

fake_get.style = "pascal"
recs = list(client.iter_list("/api/employees", page_size=100, max_pages=2))
check("pascal envelope unwrap", len(recs), 3)
check("pascal stops after short page", len(calls), 1)

fake_get.style = "camel_nested"
recs = list(client.iter_list("/api/employees", page_size=100))
check("camel data.list unwrap", len(recs), 3)

fake_get.style = "raw_array"
recs = list(client.iter_list("/api/employees", page_size=100))
check("raw array unwrap", len(recs), 3)

calls.clear()
fake_get.style = "paged"
recs = list(client.iter_list("/api/employees", page_size=2, max_pages=10))
check("pagination follows full pages", len(recs), 3)
check("pagination request count", len(calls), 2)
check("currentpage increments", [c[1]["currentpage"] for c in calls], [1, 2])

used_before = client.used_this_month()
check("counter persisted across calls", used_before > 0, True)
defaults_store[client._counter_key()] = 900
try:
    client.get("/api/employees")
    check("budget guard raises at 900", "no exception", "BudgetExhausted")
except client.BudgetExhausted:
    check("budget guard raises at 900", "BudgetExhausted", "BudgetExhausted")
check("budget guard did not call API", defaults_store[client._counter_key()], 900)

check("employee id PascalCase", sync._employee_id({"Id": 7}), "7")
check("employee id camelCase", sync._employee_id({"employeeId": 8}), "8")
check("employee name from First/Last", sync._employee_name({"FirstName": "Somchai", "LastName": "Dee"}), "Somchai Dee")
check("employee name from fullName", sync._employee_name({"fullName": "Somsri Jai"}), "Somsri Jai")
check("timesheet date trim", str(sync._pick({"Date": "2026-06-11T08:00:00"}, "date", "Date"))[:10], "2026-06-11")

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL TESTS PASSED")
sys.exit(1 if failures else 0)
