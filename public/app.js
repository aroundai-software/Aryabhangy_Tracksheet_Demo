const COLORS = ["#d61f26", "#1d4ed8", "#0f766e", "#f59e0b", "#7c3aed", "#0891b2", "#be185d", "#65a30d"];
const ZERO_BILL = /^(FREE|Warranty|Coupon Punching|Camp)/i;
const DATE_LABELS = {
  today: "Today + open",
  yesterday: "Yesterday",
  "7d": "Last 7 days",
  month: "This month",
  "": "All time",
};
const FS_FIELDS = [
  { k: "JC Number", type: "text" },
  { k: "Date", type: "date" },
  { k: "Branch", type: "select" },
  { k: "Registration", type: "text" },
  { k: "Customer Name", type: "text" },
  { k: "Model", type: "select" },
  { k: "Service Type", type: "select" },
  { k: "Repeat Complaint", type: "bool" },
  { k: "Booking Source", type: "select" },
  { k: "Adviser", type: "select" },
  { k: "Technician", type: "select" },
  { k: "Final Inspection", type: "select" },
  { k: "Status", type: "select" },
  { k: "Bill Number", type: "text" },
  { k: "Labour", type: "number" },
  { k: "Spares", type: "number" },
  { k: "Total", type: "number" },
  { k: "Payment Mode", type: "select" },
  { k: "Items", type: "text" },
  { k: "Complaints / Remarks", type: "text" },
];

const state = {
  meta: null,
  cards: [],
  date: "today",
  branch: "",
  service: "",
  booking: "",
  status: "",
  adviser: "",
  search: "",
  sortKey: "Date",
  sortDir: "desc",
  fs: [],
  fsSortKey: "",
  fsSortDir: "asc",
  vasDraft: [],
  rev: 0,
};

const ROW_H = 40;
const view = { rows: [], counts: null, filter: "", rev: -1, start: -1, end: -1 };
let regIndex = new Map();
let regRev = -1;

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function toast(message, isError) {
  const node = $("toast");
  node.textContent = message;
  node.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = "toast"; }, 3200);
}

function markSync(text, kind) {
  const node = $("sync-status");
  node.textContent = text;
  node.className = "sync " + kind;
}

function todayIso() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function addDays(iso, days) {
  const date = new Date(iso + "T00:00:00");
  date.setDate(date.getDate() + days);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function showDate(iso) {
  if (!iso) return "";
  const date = new Date(iso + "T00:00:00");
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function money(value) {
  if (value == null || value === "") return "";
  return Number(value).toLocaleString("en-IN");
}

function totalOf(card) {
  if (card.bill_amount != null && card.bill_amount !== "") return card.bill_amount;
  if (card.labour == null && card.spares == null) return null;
  return (card.labour || 0) + (card.spares || 0);
}

function padJc(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (!digits || digits.length > 6) return "";
  return digits.padStart(6, "0");
}

function fieldValue(card, key) {
  const map = {
    "JC Number": card.jc_number,
    Date: card.on_date,
    Branch: card.branch,
    Registration: card.registration,
    "Customer Name": card.customer_name,
    Model: card.model,
    "Service Type": card.service_type,
    "Repeat Complaint": card.repeat_complaint,
    "Booking Source": card.booking_source,
    Adviser: card.adviser,
    Technician: card.technician,
    "Final Inspection": card.final_inspection,
    Status: card.status,
    "Bill Number": card.bill_number,
    Labour: card.labour,
    Spares: card.spares,
    Total: totalOf(card),
    "Payment Mode": card.payment_mode,
    Items: card.items,
    "Complaints / Remarks": card.remarks,
    "Day Serial": card.day_serial,
  };
  return map[key];
}

function serviceClass(service) {
  const text = service || "";
  if (/^FREE/i.test(text)) return "pill-free";
  if (/AMC/i.test(text)) return "pill-amc";
  if (text === "PAID") return "pill-paid";
  if (/Repair|Minor|Accident/i.test(text)) return "pill-repair";
  if (/Offer|Camp|Warranty/i.test(text)) return "pill-offer";
  return "pill-other";
}

function statusClass(status) {
  return {
    Received: "pill-received",
    Pending: "pill-progress",
    Delivered: "pill-delivered",
    Cancelled: "pill-cancelled",
  }[status] || "pill-other";
}

function namesFor(grouped, branch) {
  if (grouped && grouped[branch] && grouped[branch].length) return grouped[branch];
  const all = [];
  Object.values(grouped || {}).forEach((list) => {
    list.forEach((name) => { if (!all.includes(name)) all.push(name); });
  });
  return all;
}

function prepare(card) {
  card._hay = `${card.customer_name} ${card.registration} ${card.jc_number}`.toLowerCase();
  card._dateLabel = showDate(card.on_date);
  return card;
}

function inDatePreset(card, preset, today) {
  if (preset === "today") return card.on_date === today || card.status === "Received" || card.status === "Pending";
  if (preset === "yesterday") return card.on_date === addDays(today, -1);
  if (preset === "7d") return card.on_date >= addDays(today, -6) && card.on_date <= today;
  if (preset === "month") return card.on_date.slice(0, 7) === today.slice(0, 7);
  return true;
}

function matchesCondition(card, condition) {
  const spec = FS_FIELDS.find((field) => field.k === condition.field) || { type: "text" };
  const value = fieldValue(card, condition.field);
  const query = (condition.value || "").trim().toLowerCase();
  const text = String(value ?? "").toLowerCase();
  if (condition.op === "is empty") return value == null || text === "" || value === false;
  if (condition.op === "not empty") return !(value == null || text === "" || value === false);
  if (spec.type === "number") {
    const number = Number(value);
    const target = Number(condition.value);
    if (Number.isNaN(number) || Number.isNaN(target)) return false;
    if (condition.op === "≥") return number >= target;
    if (condition.op === "≤") return number <= target;
    return number === target;
  }
  if (spec.type === "date") {
    if (condition.op === "before") return String(value) < condition.value;
    if (condition.op === "after") return String(value) > condition.value;
    return String(value) === condition.value;
  }
  if (spec.type === "bool") return (value ? "yes" : "no") === (condition.value || "yes");
  if (condition.op === "is") return text === query;
  if (condition.op === "is not") return text !== query;
  return text.includes(query);
}

function filterStamp() {
  return [
    state.date, state.branch, state.service, state.booking, state.status, state.adviser,
    state.search.trim().toLowerCase(), state.sortKey, state.sortDir, state.fsSortKey, state.fsSortDir,
    JSON.stringify(state.fs),
  ].join("\n");
}

function computeView() {
  const today = todayIso();
  const search = state.search.trim().toLowerCase();
  const counts = { "": 0, Received: 0, Pending: 0, Delivered: 0, Cancelled: 0 };
  const rows = [];
  for (let i = 0; i < state.cards.length; i++) {
    const card = state.cards[i];
    if (!inDatePreset(card, state.date, today)) continue;
    if (state.branch && card.branch !== state.branch) continue;
    if (state.service && card.service_type !== state.service) continue;
    if (state.booking && card.booking_source !== state.booking) continue;
    if (state.adviser && card.adviser !== state.adviser) continue;
    if (search && !card._hay.includes(search)) continue;
    if (!state.fs.every((condition) => matchesCondition(card, condition))) continue;
    counts[""] += 1;
    counts[card.status] = (counts[card.status] || 0) + 1;
    if (!state.status || card.status === state.status) rows.push(card);
  }
  const key = state.fsSortKey || state.sortKey;
  const dir = state.fsSortKey ? state.fsSortDir : state.sortDir;
  const sign = dir === "desc" ? -1 : 1;
  rows.sort((a, b) => {
    const left = fieldValue(a, key);
    const right = fieldValue(b, key);
    let compared = 0;
    if (typeof left === "number" || typeof right === "number") compared = (left || 0) - (right || 0);
    else {
      const textLeft = left == null ? "" : String(left);
      const textRight = right == null ? "" : String(right);
      compared = textLeft < textRight ? -1 : textLeft > textRight ? 1 : 0;
    }
    if (compared === 0) compared = a.jc_number < b.jc_number ? -1 : a.jc_number > b.jc_number ? 1 : 0;
    return compared * sign;
  });
  return { rows, counts };
}

function visibleCards() {
  refreshView();
  return view.rows;
}

function fillSelect(select, options, blank, current) {
  const value = current == null ? select.value : current;
  select.innerHTML = (blank ? `<option value="">${esc(blank)}</option>` : "") +
    options.map((option) => `<option value="${esc(option)}">${esc(option)}</option>`).join("");
  if ([...select.options].some((option) => option.value === value)) select.value = value;
}

function fillFilters() {
  const meta = state.meta;
  fillSelect($("filter-branch"), meta.branches, "All branches", state.branch);
  fillSelect($("filter-service"), meta.services, "All service types", state.service);
  fillSelect($("filter-booking"), meta.bookings, "All booking sources", state.booking);
  fillSelect($("filter-status"), meta.statuses, "All status", state.status);
  fillSelect($("filter-adviser"), meta.all_advisers, "All advisers", state.adviser);
}

function renderKpis() {
  const cacheKey = state.branch + "\n" + state.rev;
  if (renderKpis.cache === cacheKey) return;
  renderKpis.cache = cacheKey;
  const today = todayIso();
  const opened = [];
  let pending = 0;
  let deliveredCount = 0;
  let sameDayCount = 0;
  for (let i = 0; i < state.cards.length; i++) {
    const card = state.cards[i];
    if (state.branch && card.branch !== state.branch) continue;
    if (card.on_date === today) opened.push(card);
    if (card.status === "Received" || card.status === "Pending") pending += 1;
    if (card.status === "Delivered" && card.delivered_on === today) {
      deliveredCount += 1;
      if (card.on_date === today) sameDayCount += 1;
    }
  }
  $("jcw-today").textContent = opened.length;
  $("jcw-open").textContent = pending;
  $("jcw-delivered").textContent = deliveredCount;
  $("jcw-delivered-pct").textContent = opened.length ? `${Math.round((sameDayCount / opened.length) * 100)}% of today's cards` : "—";
  $("jcw-sameday").textContent = sameDayCount;
  $("jcw-scope-label").textContent = state.branch ? " · " + state.branch : "";
  const counts = {};
  opened.forEach((card) => { counts[card.adviser || "—"] = (counts[card.adviser || "—"] || 0) + 1; });
  const parts = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const total = parts.reduce((sum, part) => sum + part[1], 0);
  if (!total) {
    $("jcw-pie").style.background = "#e2e8f0";
    $("jcw-pie-legend").textContent = "No cards today";
    return;
  }
  let cursor = 0;
  const stops = parts.map((part, index) => {
    const start = (cursor / total) * 360;
    cursor += part[1];
    const end = (cursor / total) * 360;
    return `${COLORS[index % COLORS.length]} ${start}deg ${end}deg`;
  });
  $("jcw-pie").style.background = `conic-gradient(${stops.join(",")})`;
  $("jcw-pie-legend").innerHTML = parts.map((part, index) =>
    `<div><span style="color:${COLORS[index % COLORS.length]}">●</span> ${esc(part[0])} · ${part[1]}</div>`
  ).join("");
}

function renderChips() {
  const counts = view.counts || { "": 0 };
  const chips = [["", "All"]].concat(state.meta.statuses.map((status) => [status, status]));
  $("status-strip").innerHTML = chips.map(([value, label]) =>
    `<button type="button" class="schip${state.status === value ? " on" : ""}" data-status="${esc(value)}">${esc(label)} <span class="n">${counts[value] || 0}</span></button>`
  ).join("");
}

function nextStatus(status) {
  if (status === "Received") return "Pending";
  if (status === "Pending") return "Delivered";
  return "";
}

function markSort() {
  const key = state.fsSortKey || state.sortKey;
  const dir = state.fsSortKey ? state.fsSortDir : state.sortDir;
  document.querySelectorAll("#grid-table th").forEach((header) => {
    header.classList.remove("sorted-asc", "sorted-desc");
    if (header.dataset.sort === key) header.classList.add(dir === "asc" ? "sorted-asc" : "sorted-desc");
  });
}

function rowHtml(card) {
  const locked = card.status === "Delivered";
  const classes = ["data-row"];
  if (card.status === "Delivered") classes.push("row-delivered", "row-locked");
  if (card.status === "Cancelled") classes.push("row-cancelled");
  const upcoming = nextStatus(card.status);
  const vas = (card.vas || []).map((name) => `<span class="tag">${esc(name)}</span>`).join("") || "—";
  const inspection = locked
    ? esc(card.final_inspection || "—")
    : `<button type="button" class="fi-btn${card.final_inspection === "OK" ? " fi-ok-on" : ""}" data-fi="OK">OK</button><button type="button" class="fi-btn${card.final_inspection === "Not OK" ? " fi-bad-on" : ""}" data-fi="Not OK">Not OK</button>`;
  const advance = upcoming && !locked ? `<button type="button" class="status-next" data-next="${esc(upcoming)}">${esc(upcoming)}</button>` : "";
  const cell = (field, html, extra) => {
    const title = field === "Items" && card.items ? ` title="${esc(card.items)}"` : "";
    return `<td class="cell${extra || ""}" data-field="${esc(field)}"${title}>${html}</td>`;
  };
  return `<tr class="${classes.join(" ")}" data-id="${card.id}">
      <td>${card.day_serial}</td>
      ${cell("JC Number", esc(card.jc_number))}
      ${cell("Date", esc(card._dateLabel || ""))}
      ${cell("Registration", esc(card.registration))}
      ${cell("Customer Name", esc(card.customer_name))}
      ${cell("Model", esc(card.model || "—"))}
      ${cell("Service Type", `<span class="pill ${serviceClass(card.service_type)}">${esc(card.service_type)}</span>`)}
      <td>${card.repeat_complaint ? '<span class="pill pill-repeat">RPT</span>' : ""}</td>
      ${cell("Booking Source", esc(card.booking_source || "—"))}
      ${cell("Adviser", esc(card.adviser || "—"))}
      ${cell("Technician", esc(card.technician || "—"))}
      <td>${inspection}</td>
      <td class="cell" data-field="Status"><span class="pill ${statusClass(card.status)}">${esc(card.status)}</span>${advance}</td>
      <td class="cell" data-field="VAS">${vas}</td>
      ${cell("Items", esc(card.items || "—"), " items")}
      ${cell("Bill Number", esc(card.bill_number || "—"))}
      ${cell("Labour", money(card.labour) || "—", " num")}
      ${cell("Spares", money(card.spares) || "—", " num")}
      ${cell("Payment Mode", esc(card.payment_mode || "—"))}
      <td class="num">${money(totalOf(card)) || "—"}</td>
      <td class="cell remarks" data-field="Complaints / Remarks" title="${esc(card.remarks)}">${esc(card.remarks || "—")}</td>
      <td>${locked ? "" : '<button type="button" class="jc-del" title="Delete">×</button>'}</td>
    </tr>`;
}

function padRow(height) {
  if (height <= 0) return "";
  return `<tr class="v-pad"><td colspan="22" style="height:${height}px"></td></tr>`;
}

function paintWindow(reset, force) {
  const scroller = $("grid-scroll");
  const rows = view.rows;
  const body = $("grid-body");
  if (!force && !reset && body.querySelector(".cell-edit")) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="22"><div class="loading">No job cards match these filters.</div></td></tr>`;
    view.start = -1;
    view.end = -1;
    $("grid-count").textContent = "0 job cards";
    return;
  }
  if (reset) scroller.scrollTop = 0;
  const height = scroller.clientHeight || 640;
  const start = Math.max(0, Math.floor(scroller.scrollTop / ROW_H) - 8);
  const end = Math.min(rows.length, start + Math.ceil(height / ROW_H) + 16);
  if (!force && !reset && start === view.start && end === view.end) return;
  view.start = start;
  view.end = end;
  const html = [padRow(start * ROW_H)];
  for (let i = start; i < end; i++) html.push(rowHtml(rows[i]));
  html.push(padRow((rows.length - end) * ROW_H));
  const saved = scroller.scrollTop;
  body.innerHTML = html.join("");
  if (!reset && scroller.scrollTop !== saved) scroller.scrollTop = saved;
  $("grid-count").textContent = `${rows.length} job card${rows.length === 1 ? "" : "s"}`;
}

function refreshView() {
  const stamp = filterStamp();
  if (stamp === view.filter && state.rev === view.rev) return;
  const computed = computeView();
  view.rows = computed.rows;
  view.counts = computed.counts;
  view.filter = stamp;
  view.rev = state.rev;
  view.start = -1;
}

function render() {
  if (!state.meta) return;
  const stamp = filterStamp();
  const filterChanged = stamp !== view.filter;
  refreshView();
  const branch = state.branch || "All branches";
  $("grid-subtitle").textContent = `${branch} • ${DATE_LABELS[state.date]} • Click any cell to edit`;
  $("grid-clear-all").style.display = (
    state.date !== "today" || state.branch || state.service || state.booking || state.status || state.adviser || state.search || state.fs.length
  ) ? "" : "none";
  const badge = $("fs-badge-grid");
  badge.textContent = state.fs.length ? String(state.fs.length) : "";
  badge.classList.toggle("on", state.fs.length > 0);
  renderKpis();
  renderChips();
  markSort();
  paintWindow(filterChanged, true);
}

async function send(url, method, body) {
  markSync("Saving…", "saving");
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    markSync("Not saved", "error");
    throw new Error(data.error || "Could not save the job card.");
  }
  markSync("Saved locally", "saved");
  return data;
}

function replaceCard(card) {
  prepare(card);
  const index = state.cards.findIndex((item) => item.id === card.id);
  if (index >= 0) state.cards[index] = card;
  else state.cards.push(card);
  state.rev += 1;
}

async function patchCard(id, body) {
  const card = await send("/api/local/cards/" + id, "PATCH", body);
  replaceCard(card);
  render();
  return card;
}

function cardById(id) {
  const wanted = Number(id);
  for (let i = 0; i < state.cards.length; i++) {
    if (state.cards[i].id === wanted) return state.cards[i];
  }
  return null;
}

function closePop() {
  const pop = document.querySelector(".vas-pop");
  if (pop) pop.remove();
}

function optionsFor(field, card) {
  const meta = state.meta;
  if (field === "Branch") return meta.branches;
  if (field === "Service Type") return meta.services;
  if (field === "Booking Source") return meta.bookings;
  if (field === "Status") return meta.statuses;
  if (field === "Payment Mode") return meta.payments;
  if (field === "Model") return meta.all_models;
  if (field === "Adviser") return namesFor(meta.advisers, card.branch);
  if (field === "Technician") return namesFor(meta.techs, card.branch);
  return null;
}

function payloadKey(field) {
  return {
    "JC Number": "jc_number",
    Date: "on_date",
    Registration: "registration",
    "Customer Name": "customer_name",
    Model: "model",
    "Service Type": "service_type",
    "Booking Source": "booking_source",
    Adviser: "adviser",
    Technician: "technician",
    Status: "status",
    Branch: "branch",
    "Bill Number": "bill_number",
    Labour: "labour",
    Spares: "spares",
    "Payment Mode": "payment_mode",
    Items: "items",
    "Complaints / Remarks": "remarks",
  }[field];
}

function startEdit(cell, card) {
  if (cell.querySelector(".cell-edit")) return;
  const field = cell.dataset.field;
  if (card.status === "Delivered") {
    toast("Delivered job cards are locked.", true);
    return;
  }
  if (field === "VAS") {
    openVas(cell, card);
    return;
  }
  const key = payloadKey(field);
  const options = optionsFor(field, card);
  const editor = document.createElement(field === "Items" ? "textarea" : options ? "select" : "input");
  editor.className = "cell-edit";
  if (field === "Items") editor.rows = 4;
  if (!options && field === "Date") editor.type = "date";
  if (field === "Labour" || field === "Spares") editor.type = "number";
  if (options) {
    editor.innerHTML = `<option value=""></option>` + options.map((option) => `<option>${esc(option)}</option>`).join("");
    editor.value = fieldValue(card, field) || "";
  } else if (field === "Date") editor.value = card.on_date;
  else if (field === "Labour" || field === "Spares") editor.value = card[key] == null ? "" : card[key];
  else editor.value = fieldValue(card, field) || "";
  cell.textContent = "";
  cell.appendChild(editor);
  editor.focus();
  let done = false;
  const commit = async () => {
    if (done) return;
    done = true;
    let value = editor.value;
    if (field === "Labour" || field === "Spares") value = value === "" ? null : Number(value);
    if (field === "JC Number") value = padJc(value);
    try {
      await patchCard(card.id, { [key]: value });
    } catch (error) {
      toast(error.message, true);
      render();
    }
  };
  editor.addEventListener("change", commit);
  editor.addEventListener("blur", commit);
  editor.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && field !== "Items") editor.blur();
    if (event.key === "Escape") {
      done = true;
      render();
    }
  });
}

function openVas(cell, card) {
  closePop();
  const pop = document.createElement("div");
  pop.className = "vas-pop";
  const selected = new Set(card.vas || []);
  pop.innerHTML = `<div class="chip-grid">${state.meta.vas.map((name) =>
    `<span class="chip${selected.has(name) ? " on" : ""}" data-vas="${esc(name)}">${esc(name)}</span>`
  ).join("")}</div>`;
  document.body.appendChild(pop);
  const rect = cell.getBoundingClientRect();
  pop.style.top = Math.min(rect.bottom + 6, window.innerHeight - pop.offsetHeight - 12) + "px";
  pop.style.left = Math.min(rect.left, window.innerWidth - pop.offsetWidth - 12) + "px";
  pop.addEventListener("click", async (event) => {
    const chip = event.target.closest("[data-vas]");
    if (!chip) return;
    const name = chip.dataset.vas;
    if (selected.has(name)) selected.delete(name);
    else selected.add(name);
    chip.classList.toggle("on");
    try {
      await patchCard(card.id, { vas: [...selected] });
      openVas(document.querySelector(`tr[data-id="${card.id}"] td[data-field="VAS"]`), cardById(card.id));
    } catch (error) {
      toast(error.message, true);
    }
  });
}

function ensureRegIndex() {
  if (regRev === state.rev) return;
  regIndex = new Map();
  for (let i = 0; i < state.cards.length; i++) {
    const card = state.cards[i];
    const list = regIndex.get(card.registration);
    if (list) list.push(card);
    else regIndex.set(card.registration, [card]);
  }
  regRev = state.rev;
}

function repeatNote(registration, onDate) {
  const reg = registration.replace(/[^a-z0-9]/gi, "").toUpperCase();
  if (reg.length < 5) return "";
  ensureRegIndex();
  const list = regIndex.get(reg);
  if (!list) return "";
  const date = onDate || todayIso();
  const right = new Date(date + "T00:00:00");
  for (let i = 0; i < list.length; i++) {
    const card = list[i];
    const left = new Date(card.on_date + "T00:00:00");
    if (Math.abs(left - right) / 86400000 <= 14) {
      return `Same vehicle was in on ${showDate(card.on_date)} (JC ${card.jc_number}). A remark is required.`;
    }
  }
  return "";
}

function refreshFormChoices() {
  const meta = state.meta;
  const branch = $("f-branch").value;
  fillSelect($("f-adv"), namesFor(meta.advisers, branch), "— Select —");
  fillSelect($("f-tech"), namesFor(meta.techs, branch), "Assign later");
  const bigwing = branch.indexOf("Bigwing") >= 0;
  const models = bigwing ? meta.models.Bigwing.concat(meta.models.Redwing) : meta.models.Redwing.concat(meta.models.Bigwing);
  fillSelect($("f-model"), models, "— Select —");
  const others = meta.branches.filter((name) => name !== branch);
  fillSelect($("f-svcat"), others, "This branch");
}

function openNew() {
  if (!state.meta) return;
  state.vasDraft = [];
  $("newjc-form").reset();
  $("f-jcdate").value = todayIso();
  fillSelect($("f-branch"), state.meta.branches, null, state.branch || "Aluva");
  fillSelect($("f-svc"), state.meta.services, "— Select —");
  fillSelect($("f-booking"), state.meta.bookings, null, "Walk-in");
  refreshFormChoices();
  drawVasChips();
  $("row-claim").style.display = "none";
  $("jc-dupe-banner").style.display = "none";
  $("modal-newjc").classList.add("on");
  $("f-jcno").focus();
}

function closeNew() {
  $("modal-newjc").classList.remove("on");
}

function drawVasChips() {
  $("vas-chips").innerHTML = state.meta.vas.map((name) =>
    `<span class="chip${state.vasDraft.includes(name) ? " on" : ""}" data-vas="${esc(name)}">${esc(name)}</span>`
  ).join("");
}

function openFs() {
  const fieldSelect = $("fs-sort-field");
  fieldSelect.innerHTML = `<option value="">Table sort</option>` + FS_FIELDS.map((field) => `<option>${esc(field.k)}</option>`).join("");
  fieldSelect.value = state.fsSortKey;
  $("fs-sort-dir").value = state.fsSortDir;
  drawFs();
  $("modal-fs").classList.add("on");
}

function drawFs() {
  $("fs-conds").innerHTML = state.fs.map((condition, index) => {
    const spec = FS_FIELDS.find((field) => field.k === condition.field) || FS_FIELDS[0];
    const ops = spec.type === "number" ? ["=", "≥", "≤"]
      : spec.type === "date" ? ["on", "before", "after"]
      : spec.type === "bool" ? ["is"]
      : spec.type === "select" ? ["is", "is not", "is empty", "not empty"]
      : ["contains", "is", "is not", "is empty", "not empty"];
    return `<div class="fs-line">
      <select data-fs="field" data-index="${index}">${FS_FIELDS.map((field) => `<option${field.k === condition.field ? " selected" : ""}>${esc(field.k)}</option>`).join("")}</select>
      <select data-fs="op" data-index="${index}">${ops.map((op) => `<option${op === condition.op ? " selected" : ""}>${esc(op)}</option>`).join("")}</select>
      <input data-fs="value" data-index="${index}" value="${esc(condition.value || "")}" ${/empty/.test(condition.op) ? "disabled" : ""}>
      <button type="button" data-fs-remove="${index}">×</button>
    </div>`;
  }).join("") || `<div class="hint" style="margin-bottom:10px;">Add a condition, or just choose a sort.</div>`;
}

function exportRows() {
  const rows = visibleCards();
  const headers = ["#", "JC", "Date", "Reg", "Customer", "Model", "Service", "RPT", "Booking", "Adviser", "Tech", "Final Insp", "Status", "VAS", "Items", "Bill #", "Labour", "Spares", "Pay", "Total", "Remarks"];
  const lines = [headers.join(",")];
  rows.forEach((card) => {
    const values = [
      card.day_serial, card.jc_number, card.on_date, card.registration, card.customer_name,
      card.model, card.service_type, card.repeat_complaint ? "Yes" : "", card.booking_source, card.adviser,
      card.technician, card.final_inspection, card.status, (card.vas || []).join("; "), card.items || "", card.bill_number,
      card.labour ?? "", card.spares ?? "", card.payment_mode, totalOf(card) ?? "", card.remarks,
    ];
    lines.push(values.map((value) => `"${String(value ?? "").replace(/"/g, '""')}"`).join(","));
  });
  const blob = new Blob(["\uFEFF" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "JobCards_" + todayIso() + ".csv";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function tick() {
  $("topbar-clock").textContent = new Date().toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function bind() {
  let searchTimer = 0;
  $("search").addEventListener("input", (event) => {
    state.search = event.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(render, 90);
  });
  const scroller = $("grid-scroll");
  let paintQueued = false;
  scroller.addEventListener("scroll", () => {
    if (paintQueued) return;
    paintQueued = true;
    requestAnimationFrame(() => {
      paintQueued = false;
      paintWindow(false);
    });
  }, { passive: true });
  window.addEventListener("resize", () => {
    view.start = -1;
    paintWindow(false);
  });
  ["date", "branch", "service", "booking", "status", "adviser"].forEach((name) => {
    $("filter-" + name).addEventListener("change", (event) => {
      state[name] = event.target.value;
      render();
    });
  });
  $("grid-clear-all").addEventListener("click", () => {
    state.date = "today";
    state.branch = state.service = state.booking = state.status = state.adviser = state.search = "";
    state.fs = [];
    state.fsSortKey = "";
    $("search").value = "";
    $("filter-date").value = "today";
    ["branch", "service", "booking", "status", "adviser"].forEach((name) => { $("filter-" + name).value = ""; });
    render();
  });
  $("status-strip").addEventListener("click", (event) => {
    const chip = event.target.closest(".schip");
    if (!chip) return;
    state.status = chip.dataset.status;
    $("filter-status").value = state.status;
    render();
  });
  $("grid-table").querySelector("thead").addEventListener("click", (event) => {
    const header = event.target.closest("th[data-sort]");
    if (!header) return;
    const key = header.dataset.sort;
    if (!state.fsSortKey && state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    else {
      state.sortKey = key;
      state.sortDir = "asc";
    }
    state.fsSortKey = "";
    render();
  });
  $("grid-body").addEventListener("click", async (event) => {
    const row = event.target.closest("tr[data-id]");
    if (!row) return;
    const card = cardById(row.dataset.id);
    if (!card) return;
    if (event.target.closest(".jc-del")) {
      if (!confirm("Delete JC " + card.jc_number + "? This removes it from the local copy only.")) return;
      try {
        await send("/api/local/cards/" + card.id, "DELETE");
        state.cards = state.cards.filter((item) => item.id !== card.id);
        state.rev += 1;
        render();
      } catch (error) {
        toast(error.message, true);
      }
      return;
    }
    const inspection = event.target.closest("[data-fi]");
    if (inspection) {
      try { await patchCard(card.id, { final_inspection: inspection.dataset.fi }); }
      catch (error) { toast(error.message, true); }
      return;
    }
    const advance = event.target.closest("[data-next]");
    if (advance) {
      try { await patchCard(card.id, { status: advance.dataset.next }); }
      catch (error) { toast(error.message, true); }
      return;
    }
    const cell = event.target.closest("td.cell");
    if (cell) startEdit(cell, card);
  });
  $("btn-new").addEventListener("click", openNew);
  $("btn-excel").addEventListener("click", exportRows);
  $("newjc-close").addEventListener("click", closeNew);
  $("newjc-cancel").addEventListener("click", closeNew);
  $("fs-btn-grid").addEventListener("click", openFs);
  $("fs-close").addEventListener("click", () => $("modal-fs").classList.remove("on"));
  $("f-branch").addEventListener("change", refreshFormChoices);
  $("f-svc").addEventListener("change", () => {
    $("row-claim").style.display = $("f-svc").value === "Accident" ? "" : "none";
  });
  $("f-jcno").addEventListener("input", () => {
    const padded = padJc($("f-jcno").value);
    const taken = padded && state.cards.some((card) => card.jc_number === padded);
    $("jcno-status").textContent = taken ? "This JC number is already used." : "Type the digits — zeros fill in front (e.g. 7153 → 007153)";
  });
  $("f-reg").addEventListener("input", () => {
    const note = repeatNote($("f-reg").value, $("f-jcdate").value);
    const banner = $("jc-dupe-banner");
    banner.style.display = note ? "block" : "none";
    banner.textContent = note;
    $("reg-status").textContent = note ? "Repeat complaint" : "Type to look up an existing vehicle";
  });
  $("vas-chips").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-vas]");
    if (!chip) return;
    const name = chip.dataset.vas;
    if (state.vasDraft.includes(name)) state.vasDraft = state.vasDraft.filter((item) => item !== name);
    else state.vasDraft.push(name);
    drawVasChips();
  });
  $("newjc-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = {
      branch: $("f-branch").value,
      serviced_at: $("f-svcat").value,
      jc_number: $("f-jcno").value,
      registration: $("f-reg").value,
      customer_name: $("f-name").value,
      model: $("f-model").value,
      service_type: $("f-svc").value,
      on_date: $("f-jcdate").value,
      claim: $("f-svc").value === "Accident" ? $("f-claim").value : "",
      adviser: $("f-adv").value,
      booking_source: $("f-booking").value,
      technician: $("f-tech").value,
      vas: state.vasDraft,
      remarks: $("f-remarks").value,
      status: "Received",
    };
    try {
      const card = await send("/api/local/cards", "POST", body);
      prepare(card);
      state.cards.push(card);
      state.rev += 1;
      closeNew();
      state.date = "";
      state.status = "";
      state.search = card.jc_number;
      $("filter-date").value = "";
      $("filter-status").value = "";
      $("search").value = card.jc_number;
      render();
      toast("Job card " + card.jc_number + " saved.");
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("fs-add").addEventListener("click", () => {
    state.fs.push({ field: "Customer Name", op: "contains", value: "" });
    drawFs();
  });
  $("fs-conds").addEventListener("input", syncFsDraft);
  $("fs-conds").addEventListener("change", syncFsDraft);
  $("fs-conds").addEventListener("click", (event) => {
    const button = event.target.closest("[data-fs-remove]");
    if (!button) return;
    state.fs.splice(Number(button.dataset.fsRemove), 1);
    drawFs();
  });
  $("fs-apply").addEventListener("click", () => {
    syncFsDraft();
    state.fs = state.fs.filter((condition) => condition.value || /empty/.test(condition.op));
    state.fsSortKey = $("fs-sort-field").value;
    state.fsSortDir = $("fs-sort-dir").value;
    $("modal-fs").classList.remove("on");
    render();
  });
  $("fs-reset").addEventListener("click", () => {
    state.fs = [];
    state.fsSortKey = "";
    $("modal-fs").classList.remove("on");
    render();
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".vas-pop") && !event.target.closest('td[data-field="VAS"]')) closePop();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeNew();
      closePop();
      $("modal-fs").classList.remove("on");
    }
  });
}

function syncFsDraft() {
  state.fs = [...$("fs-conds").querySelectorAll(".fs-line")].map((line) => ({
    field: line.querySelector('[data-fs="field"]').value,
    op: line.querySelector('[data-fs="op"]').value,
    value: line.querySelector('[data-fs="value"]').value,
  }));
}

async function fetchCards() {
  const response = await fetch("/api/local/cards?page=1&size=2000");
  if (!response.ok) throw new Error("The job cards could not be loaded.");
  const data = await response.json();
  if (Array.isArray(data)) return data;
  const cards = data.cards || [];
  const pages = Number(data.pages) || 1;
  if (pages < 2) return cards;
  const rest = await Promise.all(
    Array.from({ length: pages - 1 }, (_, index) =>
      fetch("/api/local/cards?page=" + (index + 2) + "&size=2000").then((item) => {
        if (!item.ok) throw new Error("The job cards could not be loaded.");
        return item.json();
      })
    )
  );
  rest.forEach((body) => cards.push(...(body.cards || [])));
  return cards;
}

async function load() {
  const [metaResponse, cards] = await Promise.all([
    fetch("/api/local/meta"),
    fetchCards(),
  ]);
  if (!metaResponse.ok) throw new Error("The job cards could not be loaded.");
  state.meta = await metaResponse.json();
  state.cards = cards.map(prepare);
  state.rev += 1;
  fillFilters();
  render();
  markSync("Local copy", "saved");
}

tick();
setInterval(tick, 30000);
bind();
load().catch((error) => {
  $("grid-body").innerHTML = `<tr><td colspan="22"><div class="loading">${esc(error.message)}</div></td></tr>`;
});
