"""Job cards stored in Neon. Used by the Vercel site."""

import os
import re
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2.extras import Json, RealDictCursor, execute_values

import server

PAGE_SIZE = 2000


def connect():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg2.connect(url, connect_timeout=20)


def _iso(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10] if not isinstance(value, datetime) else value.date().isoformat()
    return value or None


def _money(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def as_card(row):
    vas = row["vas"] if isinstance(row["vas"], list) else []
    return {
        "id": row["id"],
        "jc_number": row["jc_number"],
        "on_date": _iso(row["on_date"]) or "",
        "registration": row["registration"],
        "customer_name": row["customer_name"],
        "model": row["model"] or "",
        "branch": row["branch"],
        "serviced_at": row["serviced_at"] or "",
        "service_type": row["service_type"] or "",
        "booking_source": row["booking_source"] or "",
        "adviser": row["adviser"] or "",
        "technician": row["technician"] or "",
        "status": row["status"],
        "final_inspection": row["final_inspection"] or "",
        "claim": row["claim"] or "",
        "bill_number": row["bill_number"] or "",
        "labour": _money(row["labour"]),
        "spares": _money(row["spares"]),
        "bill_amount": _money(row["bill_amount"]),
        "payment_mode": row["payment_mode"] or "",
        "vas": vas,
        "items": row["items"] or "",
        "remarks": row["remarks"] or "",
        "repeat_complaint": bool(row["repeat_complaint"]),
        "day_serial": row["day_serial"],
        "delivered_on": _iso(row["delivered_on"]),
    }


def page_cards(page, size):
    page = max(1, int(page or 1))
    size = min(PAGE_SIZE, max(1, int(size or PAGE_SIZE)))
    offset = (page - 1) * size
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM job_cards")
            total = cursor.fetchone()["total"]
            cursor.execute(
                """
                SELECT * FROM job_cards
                ORDER BY on_date DESC, branch, day_serial, id
                LIMIT %s OFFSET %s
                """,
                (size, offset),
            )
            rows = cursor.fetchall()
    pages = max(1, (total + size - 1) // size) if total else 1
    return {"cards": [as_card(row) for row in rows], "page": page, "pages": pages, "total": total}


def _kept(value, options, label, current, required=False):
    cleaned = server.text(value, 80)
    if current is not None and cleaned == server.text(current, 80):
        return cleaned
    return server.one_of(value, options, label, required=required)


def _clean(connection, payload, current=None):
    if current and current["status"] == "Delivered":
        raise ValueError("Delivered job cards are locked.")
    merged = dict(as_card(current) if current else {})
    merged.update(payload or {})
    item = {
        "jc_number": server.norm_jc(merged.get("jc_number")),
        "on_date": server.norm_date(merged.get("on_date")),
        "registration": server.norm_reg(merged.get("registration")),
        "customer_name": server.text(merged.get("customer_name"), 80),
        "model": _kept(merged.get("model"), server.ALL_MODELS, "Model", current["model"] if current else None),
        "branch": server.one_of(merged.get("branch"), server.BRANCHES, "Branch", required=True),
        "serviced_at": server.one_of(merged.get("serviced_at"), server.BRANCHES, "Serviced at"),
        "service_type": _kept(
            merged.get("service_type"), server.SERVICES, "Service type",
            current["service_type"] if current else None, required=True,
        ),
        "booking_source": _kept(
            merged.get("booking_source"), server.BOOKINGS, "Booking source",
            current["booking_source"] if current else None,
        ),
        "status": server.one_of(merged.get("status") or "Received", server.STATUSES, "Status", required=True),
        "final_inspection": server.one_of(merged.get("final_inspection"), server.INSPECTIONS, "Final inspection"),
        "claim": server.one_of(merged.get("claim"), server.CLAIMS, "Claim type"),
        "bill_number": server.text(merged.get("bill_number"), 40),
        "labour": server.money(merged.get("labour")),
        "spares": server.money(merged.get("spares")),
        "payment_mode": server.one_of(merged.get("payment_mode"), server.PAYMENTS, "Payment mode"),
        "remarks": server.text(merged.get("remarks"), 2000),
        "items": server.item_text(merged.get("items"), 4000),
        "repeat_complaint": bool(merged.get("repeat_complaint")),
    }
    if not item["customer_name"]:
        raise ValueError("Customer name is required.")
    if item["serviced_at"] == item["branch"]:
        item["serviced_at"] = ""
    adviser = server.text(merged.get("adviser"), 80)
    current_adviser = current["adviser"] if current else None
    if not (current is not None and adviser == server.text(current_adviser, 80)):
        if adviser and adviser not in server.names_for(server.ADVISERS, item["branch"]):
            raise ValueError("Pick an adviser for this branch.")
        if not adviser:
            raise ValueError("Adviser is required.")
    item["adviser"] = adviser
    technician = server.text(merged.get("technician"), 80)
    current_tech = current["technician"] if current else None
    if not (current is not None and technician == server.text(current_tech, 80)):
        if technician and technician not in server.names_for(server.TECHS, item["branch"]):
            raise ValueError("Pick a technician for this branch.")
    item["technician"] = technician
    if item["service_type"] == "Accident" and not item["claim"]:
        raise ValueError("Accident job cards need a claim type.")
    if item["service_type"] != "Accident":
        item["claim"] = ""
    vas = []
    for name in merged.get("vas") or []:
        cleaned = server.one_of(name, server.VAS_OPTIONS, "VAS")
        if cleaned and cleaned not in vas:
            vas.append(cleaned)
    item["vas"] = vas
    own_id = current["id"] if current else None
    if _is_repeat(connection, item["registration"], item["on_date"], own_id):
        item["repeat_complaint"] = True
    if item["repeat_complaint"] and not item["remarks"]:
        raise ValueError("A remark is required for a repeat complaint.")
    if item["labour"] is None and item["spares"] is None:
        item["bill_amount"] = _money(current["bill_amount"]) if current else None
    else:
        item["bill_amount"] = (item["labour"] or 0) + (item["spares"] or 0)
    if item["status"] == "Delivered":
        problems = server.delivery_problems(item)
        if problems:
            raise ValueError("To deliver, fill: " + ", ".join(problems) + ".")
        if current and current["delivered_on"]:
            item["delivered_on"] = _iso(current["delivered_on"])
        else:
            item["delivered_on"] = date.today().isoformat()
    else:
        item["delivered_on"] = None
    return item


def _is_repeat(connection, registration, on_date, own_id):
    current = datetime.strptime(on_date, "%Y-%m-%d").date()
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            "SELECT id, on_date FROM job_cards WHERE registration = %s AND id <> %s",
            (registration, own_id or 0),
        )
        rows = cursor.fetchall()
    for row in rows:
        other = row["on_date"]
        if hasattr(other, "year"):
            other_date = other if not isinstance(other, datetime) else other.date()
        else:
            other_date = datetime.strptime(str(other), "%Y-%m-%d").date()
        if abs((current - other_date).days) <= 14:
            return True
    return False


def _renumber(cursor, branch, on_date):
    cursor.execute(
        """
        UPDATE job_cards AS card
        SET day_serial = ranked.serial
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY jc_number, id) AS serial
            FROM job_cards
            WHERE branch = %s AND on_date = %s
        ) AS ranked
        WHERE card.id = ranked.id
        """,
        (branch, on_date),
    )


def _write(cursor, item, card_id=None):
    values = (
        item["jc_number"], item["on_date"], item["registration"], item["customer_name"],
        item["model"], item["branch"], item["serviced_at"], item["service_type"],
        item["booking_source"], item["adviser"], item["technician"], item["status"],
        item["final_inspection"], item["claim"], item["bill_number"], item["labour"],
        item["spares"], item["bill_amount"], item["payment_mode"], Json(item["vas"]),
        item["items"], item["remarks"], item["repeat_complaint"], item["delivered_on"],
    )
    if card_id is None:
        cursor.execute(
            """
            INSERT INTO job_cards (
                jc_number, on_date, registration, customer_name, model, branch,
                serviced_at, service_type, booking_source, adviser, technician, status,
                final_inspection, claim, bill_number, labour, spares, bill_amount,
                payment_mode, vas, items, remarks, repeat_complaint, delivered_on
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            values,
        )
        return cursor.fetchone()["id"]
    cursor.execute(
        """
        UPDATE job_cards SET
            jc_number = %s, on_date = %s, registration = %s, customer_name = %s,
            model = %s, branch = %s, serviced_at = %s, service_type = %s,
            booking_source = %s, adviser = %s, technician = %s, status = %s,
            final_inspection = %s, claim = %s, bill_number = %s, labour = %s,
            spares = %s, bill_amount = %s, payment_mode = %s, vas = %s, items = %s,
            remarks = %s, repeat_complaint = %s, delivered_on = %s, updated_at = NOW()
        WHERE id = %s
        """,
        values + (card_id,),
    )
    return card_id


def _load(cursor, card_id):
    cursor.execute("SELECT * FROM job_cards WHERE id = %s", (card_id,))
    return cursor.fetchone()


def create_card(payload):
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            item = _clean(connection, payload)
            card_id = _write(cursor, item)
            _renumber(cursor, item["branch"], item["on_date"])
            saved = _load(cursor, card_id)
        connection.commit()
    return as_card(saved)


def update_card(card_id, payload):
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            current = _load(cursor, card_id)
            if current is None:
                return None
            previous = (current["branch"], _iso(current["on_date"]))
            item = _clean(connection, payload, current)
            _write(cursor, item, card_id)
            _renumber(cursor, item["branch"], item["on_date"])
            if previous != (item["branch"], item["on_date"]):
                _renumber(cursor, previous[0], previous[1])
            saved = _load(cursor, card_id)
        connection.commit()
    return as_card(saved)


def delete_card(card_id):
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            current = _load(cursor, card_id)
            if current is None:
                return False
            if current["status"] == "Delivered":
                raise ValueError("Delivered job cards are locked.")
            cursor.execute("DELETE FROM job_cards WHERE id = %s", (card_id,))
            _renumber(cursor, current["branch"], _iso(current["on_date"]))
        connection.commit()
    return True


def latest_date():
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT MAX(on_date) FROM job_cards")
            found = cursor.fetchone()[0]
    if isinstance(found, datetime):
        return found.date()
    return found


def add_new_cards(cards):
    """Insert cards the demo does not already have. Existing rows are not changed."""
    if not cards:
        return 0
    values = [
        (
            card["source_row_id"], card["jc_number"], card["on_date"], card["registration"],
            card["customer_name"], card["model"], card["branch"], card["service_type"],
            card["booking_source"], card["adviser"], card["technician"],
            card["final_inspection"], card["repeat_complaint"],
        )
        for card in cards
    ]
    with connect() as connection:
        with connection.cursor() as cursor:
            inserted = execute_values(
                cursor,
                """
                INSERT INTO job_cards (
                    source_row_id, jc_number, on_date, registration, customer_name,
                    model, branch, service_type, booking_source, adviser, technician,
                    final_inspection, repeat_complaint, status
                ) VALUES %s
                ON CONFLICT (source_row_id) DO NOTHING
                RETURNING branch, on_date
                """,
                values,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Received')",
                fetch=True,
            )
            seen = set()
            for branch, on_date in inserted:
                key = (branch, _iso(on_date))
                if key in seen or not key[0] or not key[1]:
                    continue
                seen.add(key)
                _renumber(cursor, key[0], key[1])
        connection.commit()
    return len(inserted)


def changed_cards(since):
    since = (since or "").strip()
    if len(since) > 40:
        raise ValueError("The update check could not be read.")
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT NOW() AS now")
            now = cursor.fetchone()["now"]
            rows = []
            if since:
                cursor.execute(
                    """
                    SELECT * FROM job_cards
                    WHERE updated_at > %s
                    ORDER BY updated_at, id
                    LIMIT 2001
                    """,
                    (since,),
                )
                rows = cursor.fetchall()
    more = len(rows) > 2000
    return {
        "cards": [as_card(row) for row in rows[:2000]],
        "now": _iso_stamp(now),
        "more": more,
    }


def _iso_stamp(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def read_page(params):
    try:
        size = min(200, max(1, int((params.get("size") or ["200"])[0])))
        page = max(1, int((params.get("page") or ["1"])[0]))
    except ValueError as error:
        raise ValueError("The page request could not be read.") from error
    clauses = []
    args = []
    for key, values in params.items():
        if not values:
            continue
        matched = re.fullmatch(r"filter__field_(\d+)__([a-z_]+)", key)
        if not matched:
            continue
        field_id = int(matched.group(1))
        operator = matched.group(2)
        raw = values[0]
        if field_id == server.DATE_FIELD and operator == "date_equal":
            clauses.append("on_date = %s")
            args.append(raw)
        elif field_id == server.JC_FIELD and operator == "equal":
            try:
                clauses.append("jc_number = %s")
                args.append(server.norm_jc(raw))
            except ValueError:
                clauses.append("1 = 0")
        else:
            clauses.append("1 = 0")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    offset = (page - 1) * size
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM job_cards {where}", args)
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"""
                SELECT * FROM job_cards
                {where}
                ORDER BY on_date DESC, branch, day_serial, id
                LIMIT %s OFFSET %s
                """,
                args + [size, offset],
            )
            rows = [as_card(row) for row in cursor.fetchall()]
    return {"total": total, "page": page, "size": size, "rows": rows}
