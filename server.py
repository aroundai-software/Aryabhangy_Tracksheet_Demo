"""Local Job Cards website for testing.

Serves the page and a read API shaped like the live Tracksheet. All rows stay in
trackdemo.db next to this file. Get new job cards is the only live read, and it
never writes to the live site.
"""

import gzip
import json
import re
import sqlite3
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "public"
DB_PATH = ROOT / "trackdemo.db"
HOST = "127.0.0.1"
PORT = 8765
TOKEN = "local-trackdemo-token"
TABLE_ID = 561
DATE_FIELD = 5256
JC_FIELD = 5253

BRANCHES = [
    "Aluva",
    "Angamaly",
    "Kalady",
    "Perumbavoor",
    "Paravur",
    "Varapuzha",
    "Cherai",
    "Bigwing Aluva",
    "Bigwing Angamaly",
]
SERVICES = [
    "FREE 01",
    "FREE 02",
    "FREE 03",
    "Coupon Charge (FSC)",
    "AMC (new)",
    "AMC (renewal)",
    "AMC (old)",
    "PAID",
    "Repair Job",
    "Minor",
    "Accident",
    "Warranty",
    "Camp",
    "Offer",
    "Quick Delivery",
    "Coupon Punching Only",
    "Complaint Revisit",
]
BOOKINGS = [
    "Walk-in",
    "Booked (Call Center)",
    "Booked (CRE)",
    "BW Booking",
    "Late Booking",
    "Camp",
    "Breakdown",
    "Insurance Claim",
]
STATUSES = ["Received", "Pending", "Delivered", "Cancelled"]
INSPECTIONS = ["OK", "Not OK"]
PAYMENTS = [
    "Cash",
    "ICICI Card",
    "ICICI UPI",
    "Google Pay (UPI)",
    "PhonePe (UPI)",
    "Bank Transfer",
    "Mixed",
    "FOC",
]
CLAIMS = ["Insurance", "Third party"]
VAS_OPTIONS = [
    "AMC",
    "EW+",
    "Teflon",
    "Anti-Rust",
    "Silencer Coating",
    "Bottom Painting",
    "Full Painting",
    "Chain Lube",
    "Injector Cleaning",
    "Quick DC",
    "Mileage Tuning",
    "Pivot Arm Greasing",
    "Fork Oil Change",
    "Carburetor Overhaul",
    "Decarbonising",
    "Battery",
    "Tyre",
    "Teflon (Outside)",
    "Anti-Rust (Outside)",
    "Silencer Coating (Outside)",
]
MODELS = {
    "Redwing": [
        "Activa",
        "Activa 125",
        "Dio",
        "Dio 125",
        "Shine 100",
        "Shine 125",
        "SP125",
        "SP160",
        "Unicorn",
        "Grazia",
        "Aviator",
        "Livo",
        "CD 110 Dream",
        "X-Blade",
        "CB Hornet 160R",
        "Other (Redwing)",
    ],
    "Bigwing": [
        "H'ness CB350",
        "CB350",
        "CB350RS",
        "CB300R",
        "CB300F",
        "CB200X",
        "Hornet 2.0",
        "NX200",
        "NX500",
        "CB650R",
        "XL750 Transalp",
        "Africa Twin",
        "Gold Wing",
        "Other (Bigwing)",
    ],
}
ADVISERS = {
    "Aluva": ["Sathya", "Roshan", "Abhiram", "Nidheesh", "Manikandan", "Delsy", "Alfiya"],
    "Bigwing Aluva": ["Adhil", "Sreekumar"],
    "Kalady": ["Akhil", "Seljo", "Hamdan", "Unnimaya"],
    "Perumbavoor": ["Nakul", "Jibin"],
    "Paravur": ["Sonal", "Bibin", "Lakshmi"],
    "Varapuzha": ["Mani", "Arun", "Soumya"],
}
TECHS = {
    "Aluva": ["Achu", "Vipin", "Kishore", "Sanoj", "Vimal", "Inlal", "Kiran", "Sreejith", "Rohith"],
    "Bigwing Aluva": ["Sreekuttan", "Anas", "Rahul"],
    "Kalady": ["Anandhu", "Sudeep", "Vishnu", "Sahal", "Shibin"],
    "Perumbavoor": ["Jayan", "Lijo", "Ajas", "Satheesh", "Nobin"],
    "Paravur": ["Riithul", "Jose", "Vijay K S", "Hashmi", "Tp Rithin", "Adarsh"],
}
ZERO_BILL = re.compile(r"^(FREE|Warranty|Coupon Punching|Camp)", re.IGNORECASE)

SELECTS = {
    "Branch": BRANCHES,
    "Service Type": SERVICES,
    "Booking Source": BOOKINGS,
    "Status": STATUSES,
    "Final Inspection": INSPECTIONS,
    "Payment Mode": PAYMENTS,
    "Claim": CLAIMS,
    "Serviced At": BRANCHES,
    "VAS Canvassed": VAS_OPTIONS,
}


def all_names(grouped):
    names = []
    for group in grouped.values():
        for name in group:
            if name not in names:
                names.append(name)
    return names


ALL_ADVISERS = all_names(ADVISERS)
ALL_TECHS = all_names(TECHS)
ALL_MODELS = MODELS["Redwing"] + MODELS["Bigwing"]


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS job_cards (
                id INTEGER PRIMARY KEY,
                jc_number TEXT NOT NULL UNIQUE,
                on_date TEXT NOT NULL,
                registration TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                branch TEXT NOT NULL,
                serviced_at TEXT NOT NULL DEFAULT '',
                service_type TEXT NOT NULL,
                booking_source TEXT NOT NULL DEFAULT '',
                adviser TEXT NOT NULL DEFAULT '',
                technician TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                final_inspection TEXT NOT NULL DEFAULT '',
                claim TEXT NOT NULL DEFAULT '',
                bill_number TEXT NOT NULL DEFAULT '',
                labour INTEGER,
                spares INTEGER,
                bill_amount INTEGER,
                payment_mode TEXT NOT NULL DEFAULT '',
                vas TEXT NOT NULL DEFAULT '[]',
                items TEXT NOT NULL DEFAULT '',
                remarks TEXT NOT NULL DEFAULT '',
                repeat_complaint INTEGER NOT NULL DEFAULT 0,
                day_serial INTEGER NOT NULL DEFAULT 1,
                delivered_on TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in con.execute("PRAGMA table_info(job_cards)")}
        if "items" not in columns:
            con.execute("ALTER TABLE job_cards ADD COLUMN items TEXT NOT NULL DEFAULT ''")
        if "source_row_id" not in columns:
            con.execute("ALTER TABLE job_cards ADD COLUMN source_row_id INTEGER")
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS job_cards_source_row ON job_cards(source_row_id)"
        )


def renumber(con, branch, on_date):
    rows = con.execute(
        """
        SELECT id FROM job_cards
        WHERE branch = ? AND on_date = ?
        ORDER BY jc_number, id
        """,
        (branch, on_date),
    ).fetchall()
    for serial, row in enumerate(rows, start=1):
        con.execute("UPDATE job_cards SET day_serial = ? WHERE id = ?", (serial, row["id"]))


def latest_on_date():
    with connect() as con:
        found = con.execute("SELECT MAX(on_date) FROM job_cards").fetchone()[0]
    if not found:
        return None
    return datetime.strptime(found, "%Y-%m-%d").date()


def add_live_cards(cards):
    """Insert cards this local copy does not already have. Existing rows stay as they are."""
    if not cards:
        return 0
    added = 0
    touched = set()
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as con:
        for card in cards:
            cursor = con.execute(
                """
                INSERT INTO job_cards (
                    source_row_id, jc_number, on_date, registration, customer_name,
                    customer_phone, model, branch, serviced_at, service_type,
                    booking_source, adviser, technician, status, final_inspection,
                    claim, bill_number, labour, spares, bill_amount, payment_mode,
                    vas, items, remarks, repeat_complaint, day_serial, delivered_on,
                    updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, '', ?, ?, '', ?, ?, ?, ?, 'Received', ?,
                    '', '', NULL, NULL, NULL, '', '[]', '', '', ?, 1, NULL, ?
                )
                ON CONFLICT (source_row_id) DO NOTHING
                """,
                (
                    card["source_row_id"], card["jc_number"], card["on_date"],
                    card["registration"], card["customer_name"], card["model"],
                    card["branch"], card["service_type"], card["booking_source"],
                    card["adviser"], card["technician"], card["final_inspection"],
                    1 if card["repeat_complaint"] else 0, now,
                ),
            )
            if cursor.rowcount:
                added += 1
                touched.add((card["branch"], card["on_date"]))
        for branch, on_date in touched:
            renumber(con, branch, on_date)
        con.commit()
    return added


def row_dict(row):
    vas = json.loads(row["vas"] or "[]")
    return {
        "id": row["id"],
        "jc_number": row["jc_number"],
        "on_date": row["on_date"],
        "registration": row["registration"],
        "customer_name": row["customer_name"],
        "model": row["model"],
        "branch": row["branch"],
        "serviced_at": row["serviced_at"],
        "service_type": row["service_type"],
        "booking_source": row["booking_source"],
        "adviser": row["adviser"],
        "technician": row["technician"],
        "status": row["status"],
        "final_inspection": row["final_inspection"],
        "claim": row["claim"],
        "bill_number": row["bill_number"],
        "labour": row["labour"],
        "spares": row["spares"],
        "bill_amount": row["bill_amount"],
        "payment_mode": row["payment_mode"],
        "vas": vas,
        "items": row["items"] or "",
        "remarks": row["remarks"],
        "repeat_complaint": bool(row["repeat_complaint"]),
        "day_serial": row["day_serial"],
        "delivered_on": row["delivered_on"],
    }


def choice(field, value):
    if not value:
        return None
    options = SELECTS.get(field) or []
    index = options.index(value) + 1 if value in options else 0
    return {"id": index, "value": value, "color": "blue"}


def baserow_row(row):
    item = row_dict(row)
    vas = [choice("VAS Canvassed", name) for name in item["vas"]]
    return {
        "id": item["id"],
        "order": f"{item['id']}.00000000000000000000",
        "JC Number": item["jc_number"],
        "Date": item["on_date"],
        "Registration": item["registration"],
        "Customer Name": item["customer_name"],
        "Model": item["model"],
        "Branch": choice("Branch", item["branch"]),
        "Serviced At": choice("Serviced At", item["serviced_at"]),
        "Service Type": choice("Service Type", item["service_type"]),
        "Booking Source": choice("Booking Source", item["booking_source"]),
        "Adviser": item["adviser"],
        "Technician": item["technician"],
        "Status": choice("Status", item["status"]),
        "Final Inspection": choice("Final Inspection", item["final_inspection"]),
        "Claim": choice("Claim", item["claim"]),
        "Bill Number": item["bill_number"],
        "Labour": item["labour"],
        "Spares": item["spares"],
        "Bill Amount": item["bill_amount"],
        "Payment Mode": choice("Payment Mode", item["payment_mode"]),
        "VAS Canvassed": vas,
        "Items": item["items"],
        "Complaints / Remarks": item["remarks"],
        "Repeat Complaint": item["repeat_complaint"],
        "Day Serial": item["day_serial"],
        "Delivery Date": item["delivered_on"],
    }


def field_list():
    specs = [
        (5253, "JC Number", "text", None),
        (5256, "Date", "date", None),
        (5257, "Registration", "text", None),
        (5258, "Customer Name", "text", None),
        (5260, "Model", "text", None),
        (5261, "Branch", "single_select", BRANCHES),
        (5262, "Serviced At", "single_select", BRANCHES),
        (5263, "Service Type", "single_select", SERVICES),
        (5264, "Booking Source", "single_select", BOOKINGS),
        (5265, "Adviser", "text", None),
        (5266, "Technician", "text", None),
        (5267, "Status", "single_select", STATUSES),
        (5268, "Final Inspection", "single_select", INSPECTIONS),
        (5269, "Claim", "single_select", CLAIMS),
        (5270, "Bill Number", "text", None),
        (5271, "Labour", "number", None),
        (5272, "Spares", "number", None),
        (5273, "Bill Amount", "number", None),
        (5274, "Payment Mode", "single_select", PAYMENTS),
        (5275, "VAS Canvassed", "multiple_select", VAS_OPTIONS),
        (5278, "Items", "long_text", None),
        (5276, "Complaints / Remarks", "long_text", None),
        (5277, "Repeat Complaint", "boolean", None),
    ]
    fields = []
    for field_id, name, kind, options in specs:
        field = {"id": field_id, "name": name, "type": kind, "table_id": TABLE_ID}
        if options is not None:
            field["select_options"] = [
                {"id": index, "value": value, "color": "blue"}
                for index, value in enumerate(options, start=1)
            ]
        fields.append(field)
    return fields


def meta():
    return {
        "branches": BRANCHES,
        "services": SERVICES,
        "bookings": BOOKINGS,
        "statuses": STATUSES,
        "inspections": INSPECTIONS,
        "payments": PAYMENTS,
        "claims": CLAIMS,
        "vas": VAS_OPTIONS,
        "models": MODELS,
        "advisers": ADVISERS,
        "techs": TECHS,
        "all_advisers": ALL_ADVISERS,
        "all_techs": ALL_TECHS,
        "all_models": ALL_MODELS,
    }


def text(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def item_text(value, limit):
    cleaned = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join(line.strip() for line in cleaned.split("\n"))
    return cleaned.strip()[:limit]


def norm_jc(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits or len(digits) > 6:
        raise ValueError("Enter a JC number of up to 6 digits.")
    return digits.zfill(6)


def norm_reg(value):
    reg = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    if len(reg) < 5:
        raise ValueError("Enter the registration.")
    return reg


def norm_date(value):
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise ValueError("Enter the JC date.") from error


def money(value):
    if value is None or value == "":
        return None
    number = float(value)
    if number < 0 or number > 10000000:
        raise ValueError("Enter a valid amount.")
    return int(round(number))


def one_of(value, options, label, required=False):
    cleaned = text(value, 80)
    if not cleaned:
        if required:
            raise ValueError(f"{label} is required.")
        return ""
    if cleaned not in options:
        raise ValueError(f"{label} is not one of the Tracksheet options.")
    return cleaned


def names_for(grouped, branch):
    return grouped.get(branch) or all_names(grouped)


def zero_bill(service):
    return bool(ZERO_BILL.search(service or ""))


def delivery_problems(item):
    missing = []
    checks = [
        ("on_date", "Date"),
        ("registration", "Registration"),
        ("customer_name", "Customer name"),
        ("model", "Model"),
        ("service_type", "Service type"),
        ("booking_source", "Booking source"),
        ("adviser", "Adviser"),
        ("technician", "Technician"),
        ("final_inspection", "Final inspection"),
        ("payment_mode", "Payment mode"),
    ]
    for key, label in checks:
        if not item.get(key):
            missing.append(label)
    if not zero_bill(item.get("service_type")):
        if not item.get("bill_number"):
            missing.append("Bill number")
        if item.get("labour") is None or item.get("spares") is None:
            missing.append("Labour and spares")
    return missing


def is_repeat(con, registration, on_date, own_id):
    current = datetime.strptime(on_date, "%Y-%m-%d").date()
    rows = con.execute(
        "SELECT id, on_date FROM job_cards WHERE registration = ? AND id != ?",
        (registration, own_id or 0),
    ).fetchall()
    for row in rows:
        other = datetime.strptime(row["on_date"], "%Y-%m-%d").date()
        if abs((current - other).days) <= 14:
            return True
    return False


def clean_payload(con, payload, current=None):
    if current and current["status"] == "Delivered":
        raise ValueError("Delivered job cards are locked.")
    base = row_dict(current) if current else {}
    merged = dict(base)
    merged.update(payload or {})
    item = {
        "jc_number": norm_jc(merged.get("jc_number")),
        "on_date": norm_date(merged.get("on_date")),
        "registration": norm_reg(merged.get("registration")),
        "customer_name": text(merged.get("customer_name"), 80),
        "customer_phone": "",
        "model": one_of(merged.get("model"), ALL_MODELS, "Model"),
        "branch": one_of(merged.get("branch"), BRANCHES, "Branch", required=True),
        "serviced_at": one_of(merged.get("serviced_at"), BRANCHES, "Serviced at"),
        "service_type": one_of(merged.get("service_type"), SERVICES, "Service type", required=True),
        "booking_source": one_of(merged.get("booking_source"), BOOKINGS, "Booking source"),
        "status": one_of(merged.get("status") or "Received", STATUSES, "Status", required=True),
        "final_inspection": one_of(merged.get("final_inspection"), INSPECTIONS, "Final inspection"),
        "claim": one_of(merged.get("claim"), CLAIMS, "Claim type"),
        "bill_number": text(merged.get("bill_number"), 40),
        "labour": money(merged.get("labour")),
        "spares": money(merged.get("spares")),
        "payment_mode": one_of(merged.get("payment_mode"), PAYMENTS, "Payment mode"),
        "remarks": text(merged.get("remarks"), 2000),
        "items": item_text(merged.get("items"), 4000),
        "repeat_complaint": bool(merged.get("repeat_complaint")),
    }
    if not item["customer_name"]:
        raise ValueError("Customer name is required.")
    if item["serviced_at"] == item["branch"]:
        item["serviced_at"] = ""
    adviser = text(merged.get("adviser"), 80)
    if adviser and adviser not in names_for(ADVISERS, item["branch"]):
        raise ValueError("Pick an adviser for this branch.")
    if not adviser:
        raise ValueError("Adviser is required.")
    item["adviser"] = adviser
    technician = text(merged.get("technician"), 80)
    if technician and technician not in names_for(TECHS, item["branch"]):
        raise ValueError("Pick a technician for this branch.")
    item["technician"] = technician
    if item["service_type"] == "Accident" and not item["claim"]:
        raise ValueError("Accident job cards need a claim type.")
    if item["service_type"] != "Accident":
        item["claim"] = ""
    vas = []
    for name in merged.get("vas") or []:
        cleaned = one_of(name, VAS_OPTIONS, "VAS")
        if cleaned and cleaned not in vas:
            vas.append(cleaned)
    item["vas"] = vas
    own_id = current["id"] if current else None
    if is_repeat(con, item["registration"], item["on_date"], own_id):
        item["repeat_complaint"] = True
    if item["repeat_complaint"] and not item["remarks"]:
        raise ValueError("A remark is required for a repeat complaint.")
    if item["labour"] is None and item["spares"] is None:
        item["bill_amount"] = current["bill_amount"] if current else None
    else:
        item["bill_amount"] = (item["labour"] or 0) + (item["spares"] or 0)
    if item["status"] == "Delivered":
        problems = delivery_problems(item)
        if problems:
            raise ValueError("To deliver, fill: " + ", ".join(problems) + ".")
        if current and current["delivered_on"]:
            item["delivered_on"] = current["delivered_on"]
        else:
            item["delivered_on"] = date.today().isoformat()
    else:
        item["delivered_on"] = None
    return item


def save_row(con, item, own_id=None):
    values = dict(item)
    values["vas"] = json.dumps(item["vas"])
    values["repeat_complaint"] = 1 if item["repeat_complaint"] else 0
    values["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if own_id is None:
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        try:
            cursor = con.execute(
                f"INSERT INTO job_cards ({columns}) VALUES ({marks})",
                list(values.values()),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("This JC number is already on a job card.") from error
        own_id = cursor.lastrowid
    else:
        assignments = ", ".join(f"{key} = ?" for key in values)
        try:
            con.execute(
                f"UPDATE job_cards SET {assignments} WHERE id = ?",
                list(values.values()) + [own_id],
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("This JC number is already on a job card.") from error
    renumber(con, item["branch"], item["on_date"])
    return con.execute("SELECT * FROM job_cards WHERE id = ?", (own_id,)).fetchone()


def _amount(value):
    if value is None or value == "":
        return None
    number = float(str(value).replace(",", "").strip())
    if number < 0 or number > 10000000:
        raise ValueError("Enter a valid amount.")
    return round(number, 2)


def _vas_names(value):
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r"[,;]", str(value or ""))
    names = []
    for part in parts:
        name = re.sub(r"\s+", " ", str(part)).strip()
        if name and name not in names:
            names.append(name[:80])
    return names


def _compact_reg(value):
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


# Same plate spelling the compare uses: KL7DC1448 and KL07DC1448 are one registration.
_PLATE = re.compile(r"^([A-Z]{2})(\d{1,2})([A-Z]{1,3})(\d{1,4})$")


def _plate_key(value):
    compact = _compact_reg(value)
    match = _PLATE.fullmatch(compact)
    if not match:
        return compact
    state, district, letters, serial = match.groups()
    return f"{state}{district.zfill(2)}{letters}{serial}"


def fill_cards(con, cards):
    """Write Bill, Labour, Spares, Total, VAS, and Items onto matching practice rows.

    Delivered rows stay locked. Other columns are left as they are.
    """
    results = []
    updated = 0
    for card in cards or []:
        jc_text = str(card.get("jc_number") or card.get("job_card") or "")
        key = str(card.get("key") or "")
        try:
            count = _fill_one(con, card)
        except ValueError as error:
            results.append({"job_card": jc_text, "key": key, "ok": False, "error": str(error)})
            continue
        updated += count
        results.append({"job_card": jc_text, "key": key, "ok": True, "rows": count})
    return {"updated": updated, "results": results}


def _fill_one(con, card):
    jc = norm_jc(card.get("jc_number") or card.get("job_card"))
    raw_reg = str(card.get("registration") or card.get("vehicle") or "")
    regs = []
    for part in re.split(r"\s+and\s+", raw_reg, flags=re.IGNORECASE):
        compact = _compact_reg(part)
        if len(compact) >= 5:
            regs.append(_plate_key(part))
    rows = con.execute("SELECT * FROM job_cards WHERE jc_number = ?", (jc,)).fetchall()
    if regs:
        rows = [row for row in rows if _plate_key(row["registration"]) in regs]
    else:
        plates = {_plate_key(row["registration"]) for row in rows}
        plates.discard("")
        if len(plates) > 1:
            raise ValueError(f"JC {jc} is on more than one vehicle.")
    open_rows = [row for row in rows if row["status"] != "Delivered"]
    if not open_rows:
        if rows:
            raise ValueError(f"JC {jc} is delivered and locked.")
        raise ValueError(f"JC {jc} is not on the Tracksheet.")
    bill = text(card.get("bill_number") or card.get("bill"), 40)
    labour = _amount(card.get("labour"))
    spares = _amount(card.get("spares"))
    total = _amount(card.get("total"))
    vas = json.dumps(_vas_names(card.get("vas")))
    items = item_text(card.get("items"), 4000)
    now = datetime.now().isoformat(timespec="seconds")
    for row in open_rows:
        con.execute(
            """
            UPDATE job_cards
            SET bill_number = ?, labour = ?, spares = ?, bill_amount = ?, vas = ?, items = ?, updated_at = ?
            WHERE id = ?
            """,
            (bill, labour, spares, total, vas, items, now, row["id"]),
        )
    return len(open_rows)


def list_rows(where="", args=()):
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT * FROM job_cards
            {where}
            ORDER BY on_date DESC, branch, day_serial, id
            """,
            args,
        ).fetchall()
    return rows


def filtered_rows(params):
    clauses = []
    args = []
    for key, values in params.items():
        match = re.fullmatch(r"filter__field_(\d+)__([a-z_]+)", key)
        if not match or not values:
            continue
        field_id = int(match.group(1))
        operator = match.group(2)
        raw = values[0]
        if field_id == DATE_FIELD and operator == "date_equal":
            clauses.append("on_date = ?")
            args.append(raw)
        elif field_id == JC_FIELD and operator == "equal":
            try:
                clauses.append("jc_number = ?")
                args.append(norm_jc(raw))
            except ValueError:
                clauses.append("1 = 0")
        else:
            clauses.append("1 = 0")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return list_rows(where, args)


class Handler(BaseHTTPRequestHandler):
    server_version = "TrackDemo/1.0"

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if method == "GET" and path in ("/", "/index.html", "/app.css", "/app.js", "/config.js"):
                self.static("/index.html" if path == "/" else path)
                return
            if method == "GET" and path == f"/api/database/fields/table/{TABLE_ID}/":
                self.require_token()
                self.send_json(200, field_list())
                return
            if method == "GET" and path == f"/api/database/rows/table/{TABLE_ID}/":
                self.require_token()
                self.send_rows(parse_qs(parsed.query))
                return
            if method == "GET" and path == "/api/local/meta":
                self.send_json(200, meta())
                return
            if method == "GET" and path == "/api/local/cards":
                self.send_json(200, [row_dict(row) for row in list_rows()])
                return
            if method == "POST" and path == "/api/local/cards":
                self.create_card()
                return
            if method == "POST" and path == "/api/local/fill":
                self.fill_request()
                return
            if method == "POST" and path == "/api/local/sync":
                self.sync_new_cards()
                return
            card_match = re.fullmatch(r"/api/local/cards/(\d+)", path)
            if card_match and method == "PATCH":
                self.update_card(int(card_match.group(1)))
                return
            if card_match and method == "DELETE":
                self.delete_card(int(card_match.group(1)))
                return
            self.send_json(404, {"error": "Not found"})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except PermissionError as error:
            self.send_json(401, {"error": str(error)})

    def require_token(self):
        if self.headers.get("Authorization", "") != "Token " + TOKEN:
            raise PermissionError("The local token was not accepted.")

    def read_body(self, limit=1_000_000):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ValueError("That update is too large.")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("The update could not be read.") from error
        if not isinstance(body, dict):
            raise ValueError("The update could not be read.")
        return body

    def fill_request(self):
        body = self.read_body(limit=8_000_000)
        cards = body.get("cards") if isinstance(body, dict) else None
        if not isinstance(cards, list) or not cards:
            raise ValueError("Choose at least one job card.")
        if len(cards) > 2000:
            raise ValueError("That update is too large.")
        with connect() as con:
            summary = fill_cards(con, cards)
            con.commit()
        self.send_json(200, summary)

    def sync_new_cards(self):
        from lib import livesheet

        try:
            dates = livesheet.read_dates(latest_on_date())
            cards = livesheet.cards_on(dates)
            added = add_live_cards(cards)
        except livesheet.LiveError as error:
            raise ValueError(str(error)) from error
        self.send_json(200, {"added": added})

    def create_card(self):
        body = self.read_body()
        with connect() as con:
            item = clean_payload(con, body)
            saved = save_row(con, item)
            con.commit()
        self.send_json(201, row_dict(saved))

    def update_card(self, card_id):
        body = self.read_body()
        with connect() as con:
            current = con.execute("SELECT * FROM job_cards WHERE id = ?", (card_id,)).fetchone()
            if current is None:
                self.send_json(404, {"error": "That job card is not on this copy."})
                return
            previous = (current["branch"], current["on_date"])
            item = clean_payload(con, body, current)
            saved = save_row(con, item, card_id)
            if previous != (item["branch"], item["on_date"]):
                renumber(con, previous[0], previous[1])
            con.commit()
            saved = con.execute("SELECT * FROM job_cards WHERE id = ?", (card_id,)).fetchone()
        self.send_json(200, row_dict(saved))

    def delete_card(self, card_id):
        with connect() as con:
            current = con.execute("SELECT * FROM job_cards WHERE id = ?", (card_id,)).fetchone()
            if current is None:
                self.send_json(404, {"error": "That job card is not on this copy."})
                return
            if current["status"] == "Delivered":
                raise ValueError("Delivered job cards are locked.")
            con.execute("DELETE FROM job_cards WHERE id = ?", (card_id,))
            renumber(con, current["branch"], current["on_date"])
            con.commit()
        self.send_json(200, {"ok": True})

    def send_rows(self, params):
        try:
            size = min(200, max(1, int((params.get("size") or ["200"])[0])))
            page = max(1, int((params.get("page") or ["1"])[0]))
        except ValueError as error:
            raise ValueError("The page request could not be read.") from error
        matched = filtered_rows(params)
        start = (page - 1) * size
        chunk = matched[start : start + size]
        nxt = None
        if start + size < len(matched):
            query = {key: values[0] for key, values in params.items() if values}
            query["page"] = str(page + 1)
            query["size"] = str(size)
            host = self.headers.get("Host", f"{HOST}:{PORT}")
            nxt = f"http://{host}/api/database/rows/table/{TABLE_ID}/?{urlencode(query)}"
        self.send_json(
            200,
            {
                "count": len(matched),
                "next": nxt,
                "previous": None,
                "results": [baserow_row(row) for row in chunk],
            },
        )

    def static(self, name):
        path = (STATIC / name.lstrip("/")).resolve()
        if STATIC not in path.parents or not path.is_file():
            self.send_json(404, {"error": "Not found"})
            return
        kind = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(path.suffix, "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, body):
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoding = ""
        if len(data) > 2048 and "gzip" in (self.headers.get("Accept-Encoding") or "").lower():
            data = gzip.compress(data, compresslevel=3)
            encoding = "gzip"
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Local Job Cards site")
    print(f"http://{HOST}:{PORT}")
    print("Get new job cards reads the live site and does not write to it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
