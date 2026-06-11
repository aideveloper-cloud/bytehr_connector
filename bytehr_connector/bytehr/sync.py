"""Pull ByteHR data into ERPNext (daily scheduled job, see hooks.py).

Ownership: ByteHR is the HR master. Everything here flows ONE way,
ByteHR -> ERPNext:
  - Employees  -> upserted as real Employee records (so projects, costing
    and approvals in ERPNext can reference real staff)
  - Timesheets -> mirrored read-only into the "ByteHR Timesheet" doctype.
    They are NOT posted as ERPNext Timesheets yet — attaching hours to the
    right Project needs a mapping decision first.

Request budget per daily run (191 staff, limit=100/page, verified live):
  employees 2 calls + timesheets 1-2 calls -> ~120 calls/month of the
  1,000/month cap. See client.py for the hard budget guard.

Verified against the live API (2026-06-11):
  - records sit in body["data"] (array), envelope has currentPage/limit/total
  - employee key field is employeeID (e.g. "58001"), plus systemID
  - /api/timesheets REQUIRES startDate + endDate and has no row id —
    rows are keyed by employeeID + dateOfWork

Extra Site Config keys (besides the client.py ones):
  bytehr_pull_timesheets -> 1 to also mirror timesheets (off by default)
  bytehr_pull_pages      -> pages per endpoint per run (default 3;
                            raise temporarily for the first backfill)
  bytehr_timesheet_days  -> how many days back each run covers (default 3)
"""

import frappe
from frappe.utils import add_days, nowdate

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
    days = int(frappe.conf.get("bytehr_timesheet_days") or 3)
    params = {
        "startDate": add_days(nowdate(), -days),
        "endDate": nowdate(),
    }
    for record in client.iter_list("/api/timesheets", max_pages=max_pages, params=params):
        _upsert_timesheet(record)


def _pick(record, *keys):
    for key in keys:
        if record.get(key):
            return record[key]
    return ""


def _employee_id(record):
    value = _pick(record, "employeeID", "employeeId", "employee_id", "systemID", "id")
    return str(value) if value else ""


def _employee_name(record):
    # Prefer Thai names (the working language); ByteHR uses "-"/"." fillers.
    first = str(_pick(record, "firstNameThai", "firstName", "first_name")).strip()
    last = str(_pick(record, "lastNameThai", "lastName", "last_name")).strip()
    parts = [p for p in (first, last) if p and p not in ("-", ".")]
    return " ".join(parts)


def _last_name(record):
    last = str(_pick(record, "lastNameThai", "lastName", "last_name")).strip()
    return last if last not in ("", "-", ".") else None


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
    employee.first_name = str(_pick(record, "firstNameThai", "firstName") or full_name).strip()
    employee.last_name = _last_name(record)
    employee.employee_number = bytehr_id
    employee.gender = _gender(record)
    employee.date_of_birth = str(record.get("birthDate") or "")[:10] or None
    employee.personal_email = record.get("email") or None
    employee.cell_number = record.get("phone") or None
    employee.status = "Active"
    employee.company = frappe.defaults.get_global_default("company")
    employee.bytehr_employee_id = bytehr_id
    employee.flags.ignore_permissions = True
    employee.insert(ignore_mandatory=True)


def _gender(record):
    # ByteHR sends bilingual values like "ชาย/Male", "หญิง/Female".
    raw = str(record.get("gender") or "")
    if "Male" in raw and "Female" not in raw:
        return "Male"
    if "Female" in raw:
        return "Female"
    return None


def _time_part(value):
    value = str(value or "")
    return value[11:16] if "T" in value else value


def _day_status(record):
    if record.get("absent"):
        return "Absent"
    if record.get("leave"):
        return f"Leave: {record.get('leaveName') or ''}".strip(": ")
    if record.get("holiday"):
        return "Holiday"
    if record.get("dayOff"):
        return "Day Off"
    return "Worked"


def _upsert_timesheet(record):
    # No row id in /api/timesheets — one row per employee per day.
    employee_id = _employee_id(record)
    work_date = str(record.get("dateOfWork") or "")[:10]
    if not employee_id or not work_date:
        return
    bytehr_id = f"{employee_id}-{work_date}"

    values = {
        "bytehr_employee_id": employee_id,
        "employee_name": _employee_name(record),
        "date": work_date,
        "clock_in": _time_part(record.get("signIn")),
        "clock_out": _time_part(record.get("signOut")),
        "hours": float(record.get("regularHours") or 0),
        "ot_hours": float(record.get("totalOTHours") or 0),
        "day_status": _day_status(record),
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
