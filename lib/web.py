"""Shared request helpers for the Vercel Python functions."""

import json
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlparse

from lib import livesheet, neonstore
import server


def _default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError


def send_json(handler, code, body):
    data = json.dumps(body, default=_default, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def read_body(handler, limit=1_000_000):
    length = int(handler.headers.get("Content-Length") or 0)
    if length > limit:
        raise ValueError("That update is too large.")
    if length == 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ValueError("The update could not be read.")
    return body


def fail(handler, error):
    if isinstance(error, ValueError):
        send_json(handler, 400, {"error": str(error)})
        return
    if isinstance(error, PermissionError):
        send_json(handler, 401, {"error": str(error)})
        return
    send_json(handler, 500, {"error": "The database did not answer."})


def query(handler):
    return parse_qs(urlparse(handler.path).query)


def cards_get(handler):
    params = query(handler)
    try:
        page = int((params.get("page") or ["1"])[0])
        size = int((params.get("size") or ["2000"])[0])
    except ValueError as error:
        raise ValueError("The page request could not be read.") from error
    send_json(handler, 200, neonstore.page_cards(page, size))


def cards_post(handler):
    saved = neonstore.create_card(read_body(handler))
    send_json(handler, 201, saved)


def card_id(handler):
    params = query(handler)
    if params.get("id"):
        return int(params["id"][0])
    parts = [part for part in urlparse(handler.path).path.rstrip("/").split("/") if part]
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    raise ValueError("That job card could not be found.")


def card_patch(handler):
    saved = neonstore.update_card(card_id(handler), read_body(handler))
    if saved is None:
        send_json(handler, 404, {"error": "That job card is not on this copy."})
        return
    send_json(handler, 200, saved)


def card_delete(handler):
    if not neonstore.delete_card(card_id(handler)):
        send_json(handler, 404, {"error": "That job card is not on this copy."})
        return
    send_json(handler, 200, {"ok": True})


def sync_post(handler):
    try:
        dates = livesheet.read_dates(neonstore.latest_date())
        cards = livesheet.cards_on(dates)
        added = neonstore.add_new_cards(cards)
    except livesheet.LiveError as error:
        raise ValueError(str(error)) from error
    send_json(handler, 200, {"added": added})


def meta_get(handler):
    send_json(handler, 200, server.meta())


def fields_get(handler):
    if handler.headers.get("Authorization", "") != "Token " + server.TOKEN:
        raise PermissionError("The local token was not accepted.")
    send_json(handler, 200, server.field_list())


def rows_get(handler):
    if handler.headers.get("Authorization", "") != "Token " + server.TOKEN:
        raise PermissionError("The local token was not accepted.")
    params = query(handler)
    found = neonstore.read_page(params)
    start = (found["page"] - 1) * found["size"]
    nxt = None
    if start + found["size"] < found["total"]:
        query_values = {key: values[0] for key, values in params.items() if values}
        query_values["page"] = str(found["page"] + 1)
        query_values["size"] = str(found["size"])
        host = handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or "localhost"
        proto = handler.headers.get("X-Forwarded-Proto") or "https"
        nxt = f"{proto}://{host}/api/database/rows/table/{server.TABLE_ID}/?{urlencode(query_values)}"
    send_json(
        handler,
        200,
        {
            "count": found["total"],
            "next": nxt,
            "previous": None,
            "results": [_baserow(card) for card in found["rows"]],
        },
    )


def _baserow(item):
    vas = [server.choice("VAS Canvassed", name) for name in item["vas"]]
    return {
        "id": item["id"],
        "order": f"{item['id']}.00000000000000000000",
        "JC Number": item["jc_number"],
        "Date": item["on_date"],
        "Registration": item["registration"],
        "Customer Name": item["customer_name"],
        "Model": item["model"],
        "Branch": server.choice("Branch", item["branch"]),
        "Serviced At": server.choice("Serviced At", item["serviced_at"]),
        "Service Type": server.choice("Service Type", item["service_type"]),
        "Booking Source": server.choice("Booking Source", item["booking_source"]),
        "Adviser": item["adviser"],
        "Technician": item["technician"],
        "Status": server.choice("Status", item["status"]),
        "Final Inspection": server.choice("Final Inspection", item["final_inspection"]),
        "Claim": server.choice("Claim", item["claim"]),
        "Bill Number": item["bill_number"],
        "Labour": item["labour"],
        "Spares": item["spares"],
        "Bill Amount": item["bill_amount"],
        "Payment Mode": server.choice("Payment Mode", item["payment_mode"]),
        "VAS Canvassed": vas,
        "Items": item["items"],
        "Complaints / Remarks": item["remarks"],
        "Repeat Complaint": item["repeat_complaint"],
        "Day Serial": item["day_serial"],
        "Delivery Date": item["delivered_on"],
    }
