# ByteHR Connector (ByteHR → ERPNext)

ดึงข้อมูลพนักงานและเวลาทำงานจาก ByteHR เข้า ERPNext อัตโนมัติวันละครั้ง
ByteHR เป็น "เจ้าของข้อมูล HR" — ข้อมูลไหลทางเดียวเข้า ERPNext เท่านั้น

| ข้อมูล | ปลายทางใน ERPNext | หมายเหตุ |
|---|---|---|
| พนักงาน (`/api/employees`) | Employee (upsert จริง) | จับคู่ด้วย ByteHR ID → ชื่อ ก่อนสร้างใหม่ |
| เวลาทำงาน (`/api/timesheets`) | ByteHR Timesheet (สำเนา read-only) | เปิดแยกด้วย config — ไว้ต่อยอดคิดต้นทุนแรงงานต่อ Project |

## ข้อจำกัดสำคัญ: โควต้า 1,000 requests/เดือน

ByteHR ตัด API key ทันทีที่ครบ 1,000 requests และใช้ไม่ได้จนกว่าจะขึ้นเดือนใหม่
แอปนี้จึงมี **ตัวนับ request ต่อเดือนแบบ persistent** หยุดเองที่ 900 (กันโควต้าไว้ทดสอบมือ)
และ scheduler รัน**รายวัน** (ไม่ใช่รายชั่วโมง) — ใช้จริงประมาณ 150–250 requests/เดือน

> API key มีอายุ 1 ปี — จดวันหมดอายุไว้ใน calendar ด้วย

## Site Config

| Key | Value |
|---|---|
| `bytehr_enabled` | `1` |
| `bytehr_api_key` | API key จาก Open API add-on |
| `bytehr_api_base` | base URL ที่ได้จาก ByteHR ตอนเปิด add-on |
| `bytehr_monthly_request_budget` | (ไม่บังคับ) ค่าเริ่มต้น `900` |
| `bytehr_pull_timesheets` | `1` เมื่อต้องการดึงเวลาทำงานด้วย (ปิดไว้โดย default) |
| `bytehr_pull_pages` | (ไม่บังคับ) หน้าต่อ endpoint ต่อรอบ ค่าเริ่มต้น `3` (×100 รายการ/หน้า) |

## ติดตั้ง (เหมือน flowaccount_connector)

1. push repo นี้ขึ้น GitHub
2. Frappe Cloud → Bench → Apps → Add App from GitHub → Deploy
3. Install ลง site (custom field `bytehr_employee_id` บน Employee สร้างให้อัตโนมัติ)
4. ใส่ Site Config ตามตาราง → รอรอบ scheduler เที่ยงคืน หรือเช็ค Error Log ถ้าไม่มา

## เช็คการใช้โควต้า

จำนวน request ที่ใช้ไปเดือนนี้เก็บใน DefaultValue key `bytehr_requests_YYYY-MM`
(ดูผ่าน bench console: `frappe.db.get_default("bytehr_requests_2026-06")`)

## หมายเหตุ field mapping

โครงสร้าง response จริงของ ByteHR ยังไม่มีตัวอย่างสาธารณะ — โค้ด unwrap แบบ defensive
(`data.list` / `data.items` / array ตรง ๆ) และเดาชื่อฟิลด์หลายแบบ (`id`/`employeeId`,
`firstName`/`first_name`) **รอบแรกที่ได้ API key จริง ให้เทสแล้วปรับ mapping ให้ตรง**
เหมือนที่ทำกับ FlowAccount connector
