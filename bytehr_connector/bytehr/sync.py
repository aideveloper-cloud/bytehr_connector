"""Pull ByteHR data into ERPNext (daily scheduled job, see hooks.py).

Ownership: ByteHR is the HR master. Everything here flows ONE way,
ByteHR -> ERPNext:
  - Employees  -> upserted as real Employee records (so projects, costing
    and approvals in ERPNext can reference real staff)
  - Timesheets -> mirrored read-only into the "ByteHR Timesheet" doctype.
    They are NOT posted as ERPNext Timesheets yet — attaching hours to the
    right Project needs a mapping decision first.

Request budget per daily run (120 staff, limit=100/page):
  employees ~2 calls + timesheets ~3 calls -> ~150 calls/month of the
  1,000/month cap. See client.py for the hard budget guard.

Extra Site Config keys (besides the client.py ones):
  bytehr_pull_timesheets -> 1 to also mirror timesheets (off by default)
  bytehr_pull_pages      -> pages per endpoint per run (default 3;
                            raise temporarily for the first backfill)
"""

import frappe
from bytehr_connector.bytehr import client


def pull_all():
    if not frappe.conf.get("bytehr_enabled"):
        return

    max_pages = int(frappe.conf.get("bytehr_pull_pages") or 3)

    jobs = [("employees", lambda: pull_employees(max_pages))]
    if frappe.conf.get("bytehr_pull_timesheets"):
        jobs.append(("timesheets", lambda: pull_timesheets(max_pages)))

    for label, fn in jobs:
        try:
            fn()
            frappe.db.commit()
        except client.BudgetExhausted as e:
            frappe.db.commit()  # keep the counter bump
            frappe.log_error(title="ByteHR pull stopped: budget", message=str(e))
            return
        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                title=f"ByteHR pull failed: {label}",
                message=frappe.get_traceback(),
            )


def pull_employees(max_pages=3):
    for record in client.iter_list("/api/employees", max_pages=max_pages):
        _upsert_employee(record)


def pull_timesheets(max_pages=3):
    for record in client.iter_list("/api/timesheets", max_pages=max_pages):
        _upsert_timesheet(record)


def _employee_id(record):
    for key in ("id", "employeeId", "employee_id", "code", "employeeCode"):
        if record.get(key):
            return str(record[key])
    return ""


def _employee_name(record):
    full = (record.get("name") or record.get("fullName") or "").strip()
    if full:
        return full
    first = (record.get("firstName") or record.get("first_name") or "").strip()
    last = (record.get("lastName") or record.get("last_name") or "").strip()
    return f"{first} {last}".strip()


def _upsert_employee(record):
    bytehr_id = _employee_id(record)
    full_name = _employee_name(record)
    if not bytehr_id or not full_name:
        return

    existing = frappe.db.get_value("Employee", {"bytehr_employee_id": bytehr_id})
    if not existing:
        existing = frappe.db.get_value("Employee", {"employee_name": full_name})

    if existing:
        frappe.db.set_value(
            "Employee", existing,
            {"bytehr_employee_id": bytehr_id},
            update_modified=False,
        )
        return

    employee = frappe.new_doc("Employee")
    employee.first_name = (record.get("firstName") or record.get("first_name") or full_name).strip()
    employee.last_name = (record.get("lastName") or record.get("last_name") or "").strip() or None
    employee.status = "Active"
    employee.company = frappe.defaults.get_global_default("company")
    employee.bytehr_employee_id = bytehr_id
    employee.flags.ignore_permissions = True
    employee.insert(ignore_mandatory=True)


def _upsert_timesheet(record):
    bytehr_id = ""
    for key in ("id", "timesheetId", "timesheet_id"):
        if record.get(key):
            bytehr_id = str(record[key])
            break
    if not bytehr_id:
        return

    values = {
        "bytehr_employee_id": _employee_id(record) or str(record.get("employeeId") or ""),
        "employee_name": _employee_name(record),
        "date": (record.get("date") or record.get("workDate") or "")[:10] or None,
        "clock_in": record.get("clockIn") or record.get("checkIn") or "",
        "clock_out": record.get("clockOut") or record.get("checkOut") or "",
        "hours": float(record.get("hours") or record.get("totalHours") or 0),
        "payload": frappe.as_json(record),
        "last_synced": frappe.utils.now(),
    }

    existing = frappe.db.get_value("ByteHR Timesheet", {"bytehr_id": bytehr_id})
    if existing:
        frappe.db.set_value("ByteHR Timesheet", existing, values, update_modified=False)
        return

    mirror = frappe.new_doc("ByteHR Timesheet")
    mirror.bytehr_id = bytehr_id
    mirror.update(values)
    mirror.flags.ignore_permissions = True
    mirror.insert()
