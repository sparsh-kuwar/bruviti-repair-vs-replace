"use strict";
// Service Decision Desk: case intake on the left, recommendation on the right.
// Talks only to this same server (/decide, /health). Numeric fields: blank ->
// null; anything that is not a finite, non-negative number is blocked here, so
// NaN, Infinity and stray strings are never sent. Everything shown in the
// recommendation panel comes from the API response; nothing is invented.

const EXAMPLES = {
  "C-2001": {
    case_id: "C-2001", product_category: "washing_machine", product_age_months: 30,
    purchase_price: 38000, replacement_price: 36000, warranty_status: "out_of_warranty",
    fault_category: "motor_or_drive",
    parts: [{ sku: "WM-MTR-114", description: "Drive motor", price: 6200, lead_time_days: 4 }],
    labour_hours: 1.5, labour_rate_per_hour: 900, technician_travel_minutes: 40,
    prior_repairs_12m: 0, customer_sentiment: "neutral",
    symptom_text: "drum does not turn, motor hums",
  },
  "C-2002": {
    case_id: "C-2002", product_category: "refrigerator", product_age_months: 8,
    purchase_price: 52000, replacement_price: 49000, warranty_status: "in_warranty",
    fault_category: "not_cooling",
    parts: [{ sku: "RF-CMP-220", description: "Compressor", price: 14500, lead_time_days: 28 }],
    labour_hours: 2.0, labour_rate_per_hour: 900, technician_travel_minutes: 25,
    prior_repairs_12m: 0, customer_sentiment: "negative",
    symptom_text: "fridge warm for 3 days, food spoiled",
  },
  "C-2003": {
    case_id: "C-2003", product_category: "dishwasher", product_age_months: 50,
    purchase_price: 41000, replacement_price: null, warranty_status: "extended",
    fault_category: "water_leak",
    parts: [{ sku: "DW-PMP-031", description: "Drain pump", price: null, lead_time_days: 6 }],
    labour_hours: 1.0, labour_rate_per_hour: 900, technician_travel_minutes: 70,
    prior_repairs_12m: 2, customer_sentiment: "negative",
    symptom_text: "third leak this year, I want this sorted or taken away",
  },
};

const SCALAR_FIELDS = [
  "case_id", "product_category", "product_age_months", "purchase_price", "replacement_price",
  "warranty_status", "fault_category", "labour_hours", "labour_rate_per_hour",
  "technician_travel_minutes", "prior_repairs_12m", "customer_sentiment", "symptom_text",
];

const $ = (sel, root = document) => root.querySelector(sel);
const form = $("#case-form");
const partsBody = $("#parts-body");
const resultEl = $("#result");
const statusEl = $("#status");
const summary = $("#error-summary");
const staleEl = $("#stale");

let lastSubmitted = null; // JSON string of the body behind the current recommendation
let lastResult = null;

// ------------------------------------------------------------------ engine status (real /health)
async function checkHealth() {
  const pill = $("#engine-status");
  try {
    const res = await fetch("/health", { cache: "no-store" });
    const ok = res.ok && (await res.json()).status === "ok";
    pill.className = `pill ${ok ? "pill-ok" : "pill-down"}`;
    pill.textContent = ok ? "Policy engine online" : "Policy engine not ready";
  } catch {
    pill.className = "pill pill-down";
    pill.textContent = "Policy engine unreachable";
  }
}

// ------------------------------------------------------------------ parts
function addPart(part = {}) {
  const row = $("#part-row").content.firstElementChild.cloneNode(true);
  for (const input of row.querySelectorAll("[data-part]")) {
    const v = part[input.dataset.part];
    input.value = v === null || v === undefined ? "" : String(v);
  }
  row.querySelector("[data-remove]").addEventListener("click", () => {
    const next = row.nextElementSibling || row.previousElementSibling;
    row.remove();
    renumberParts();
    onInputChanged();
    (next ? next.querySelector("input") : $("#add-part")).focus();
  });
  partsBody.appendChild(row);
  renumberParts();
  return row;
}

function renumberParts() {
  [...partsBody.rows].forEach((row, i) => {
    for (const input of row.querySelectorAll("[data-part]")) {
      input.id = `parts-${i}-${input.dataset.part}`;
      const label = input.getAttribute("aria-label").replace(/^Part \d+: /, "");
      input.setAttribute("aria-label", `Part ${i + 1}: ${label}`);
    }
  });
  $("#empty-parts").hidden = partsBody.rows.length > 0;
}

$("#add-part").addEventListener("click", () => {
  addPart().querySelector("input").focus();
  onInputChanged();
});

// ------------------------------------------------------------------ fill / clear
function fill(data) {
  clearErrors();
  for (const name of SCALAR_FIELDS) {
    const v = data[name];
    form.elements[name].value = v === null || v === undefined ? "" : String(v);
  }
  partsBody.replaceChildren();
  (data.parts || []).forEach(addPart);
  renumberParts();
  updateCasebar();
}

function clearForm() {
  fill({ warranty_status: "unknown", customer_sentiment: "neutral", parts: [] });
  lastSubmitted = null;
  lastResult = null;
  staleEl.hidden = true;
  renderEmpty();
  statusEl.textContent = "";
  $("#case_id").focus();
}

document.querySelectorAll("[data-example]").forEach((btn) =>
  btn.addEventListener("click", () => {
    fill(EXAMPLES[btn.dataset.example]);
    onInputChanged();
    statusEl.textContent = `Loaded sample case ${btn.dataset.example}.`;
  })
);
$("#clear-btn").addEventListener("click", clearForm);

// ------------------------------------------------------------------ case bar + stale detection
function updateCasebar() {
  const v = (name) => {
    const el = form.elements[name];
    return el && el.value.trim() ? el.value.trim() : "—";
  };
  for (const span of document.querySelectorAll("[data-cb]")) {
    const name = span.dataset.cb;
    const val = v(name);
    span.textContent = name === "product_age_months" && val !== "—" ? `${val} months` : val;
  }
}

function onInputChanged() {
  updateCasebar();
  if (!lastSubmitted) return;
  const { body } = readForm();
  staleEl.hidden = JSON.stringify(body) === lastSubmitted;
}

form.addEventListener("input", onInputChanged);
form.addEventListener("change", onInputChanged);
$("#redo-btn").addEventListener("click", () => form.requestSubmit());

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    form.requestSubmit();
  }
});

// ------------------------------------------------------------------ read + validate
function readNumber(input, errors, label) {
  if (input.validity.badInput) {
    errors.push([input, `${label}: enter a number, or leave blank if unknown.`]);
    return undefined;
  }
  const raw = input.value.trim();
  if (raw === "") return null; // blank means "not provided", never 0
  const n = Number(raw);
  if (!Number.isFinite(n)) { errors.push([input, `${label}: must be a finite number.`]); return undefined; }
  if (n < 0) { errors.push([input, `${label}: must not be negative.`]); return undefined; }
  if (input.dataset.kind === "int" && !Number.isInteger(n)) {
    errors.push([input, `${label}: must be a whole number.`]); return undefined;
  }
  return n;
}

function labelFor(input) {
  const l = form.querySelector(`label[for="${input.id}"]`);
  return l ? l.firstChild.textContent.trim() : input.getAttribute("aria-label");
}

function readForm() {
  const errors = [];
  const body = {};
  for (const name of SCALAR_FIELDS) {
    const el = form.elements[name];
    if (el.dataset.kind) body[name] = readNumber(el, errors, labelFor(el));
    else if (el.tagName === "SELECT") body[name] = el.value === "" ? null : el.value;
    else body[name] = name === "symptom_text" ? el.value : el.value.trim();
  }
  if (!body.case_id) errors.push([form.elements.case_id, "Case ID: required."]);
  body.parts = [...partsBody.rows].map((row) => {
    const part = {};
    for (const input of row.querySelectorAll("[data-part]")) {
      part[input.dataset.part] = input.dataset.kind
        ? readNumber(input, errors, input.getAttribute("aria-label"))
        : input.value.trim();
    }
    return part;
  });
  return { body, errors };
}

// ------------------------------------------------------------------ errors
function clearErrors() {
  form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
  form.querySelectorAll(".err").forEach((el) => (el.textContent = ""));
  partsBody.querySelectorAll(".err-inline").forEach((el) => el.remove());
  summary.hidden = true;
}

function showErrors(list) {
  const ul = summary.querySelector("ul");
  ul.replaceChildren();
  for (const [input, msg] of list) {
    const li = document.createElement("li");
    if (input) {
      input.setAttribute("aria-invalid", "true");
      const slot = input.name ? document.getElementById(`err-${input.name}`) : null;
      if (slot) slot.textContent = msg;
      else {
        const p = document.createElement("p");
        p.className = "err err-inline";
        p.id = `${input.id}-err`;
        p.textContent = msg;
        input.setAttribute("aria-describedby", p.id);
        input.after(p);
      }
      const a = document.createElement("a");
      a.href = `#${input.id}`;
      a.textContent = msg;
      a.addEventListener("click", (e) => { e.preventDefault(); input.focus(); });
      li.appendChild(a);
    } else {
      li.textContent = msg;
    }
    ul.appendChild(li);
  }
  summary.hidden = false;
  summary.focus();
}

function apiErrorsToFields(detail) {
  // 422 body: {detail: [{loc: ["body", "parts", 0, "price"], msg: "..."}]}
  return (Array.isArray(detail) ? detail : [{ loc: [], msg: String(detail) }]).map((d) => {
    const loc = (d.loc || []).filter((x) => x !== "body");
    let input = null;
    if (loc[0] === "parts" && typeof loc[1] === "number") input = document.getElementById(`parts-${loc[1]}-${loc[2]}`);
    else if (loc.length) input = form.elements[loc[0]] || null;
    const where = loc.length ? loc.join(".") : "request";
    return [input, `${where}: ${String(d.msg).replace(/^Value error, /, "")}`];
  });
}

// ------------------------------------------------------------------ rendering helpers
const ICONS = {
  repair: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
  replace: '<path d="M4 4v6h6M20 20v-6h-6"/><path d="M20 10a8 8 0 0 0-14.9-3M4 14a8 8 0 0 0 14.9 3"/>',
  escalate: '<path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18h.01"/>',
};
const ACTION = { repair: "Repair", replace: "Replace", escalate: "Escalate to supervisor" };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const money = (v) => (v === null || v === undefined ? "Cannot compute"
  : Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pct = (r) => (r === null || r === undefined ? "n/a" : `${(r * 100).toFixed(1)}%`);

function renderEmpty() {
  resultEl.innerHTML = `
    <div class="assist-card empty-state">
      <p>Fill in the case, or load a sample case, then choose <strong>Get recommendation</strong>.</p>
      <h3>What the engine checks, in order</h3>
      <ol>
        <li><strong>Escalation checks (D5):</strong> safety hazards in the symptom text, text that conflicts with the fields, repeat repairs with negative sentiment, and whether the cost can be computed.</li>
        <li><strong>Travel override (D3):</strong> travel over 120 minutes with a cost over 40% of replacement.</li>
        <li><strong>Warranty mapping (D4):</strong> an unknown warranty is treated by product age.</li>
        <li><strong>Cost and age rule:</strong> D1 when in warranty or extended, D2 when out of warranty.</li>
      </ol>
    </div>`;
}

const STEP_ICON = { passed: "✓", stopped: "●", skipped: "○" };

function checkRow(state, title, detail, rule) {
  const icon = state === "ok" ? ["ck-ok", "✓", "passed"] : state === "hit" ? ["ck-hit", "!", "triggered"] : ["ck-unk", "?", "unknown"];
  return `<li>
      <span class="ck-icon ${icon[0]}" aria-hidden="true">${icon[1]}</span>
      <div><div>${esc(title)} <span class="sr">(${icon[2]})</span></div><div class="ck-detail">${esc(detail)}</div></div>
      <span class="ck-rule">${esc(rule)}</span>
    </li>`;
}

function caseNote(r) {
  const t = r.trace || {};
  const f = (n) => (form.elements[n].value.trim() || "not given");
  const path = (t.stages || []).map((s) => `${s.rule} ${s.stage.toLowerCase()}: ${s.detail}`).join("; ");
  return [
    `Case ${r.case_id} | ${f("product_category")} | age ${f("product_age_months")} months | ${f("warranty_status")} | ${f("fault_category")}`,
    `Recommendation: ${r.decision.toUpperCase()}${t.rule ? ` (rule ${t.rule})` : ""}`,
    `Estimated repair cost: ${money(r.estimated_repair_cost)}${t.cost_to_replacement_ratio != null ? ` (${pct(t.cost_to_replacement_ratio)} of replacement)` : ""}`,
    `Confidence: ${r.confidence.toFixed(2)} (rule-based heuristic)`,
    `Reason: ${r.reason}`,
    path ? `Decision path: ${path}` : "",
    `Recorded ${new Date().toLocaleString()} by the local policy engine.`,
  ].filter(Boolean).join("\n");
}

async function copyText(text, btn) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
  }
  const msg = btn.parentElement.querySelector(".copied");
  msg.textContent = ok ? "Copied to clipboard." : "Copy failed; select the text in Raw response instead.";
}

// ------------------------------------------------------------------ render result
function renderResult(r) {
  const t = r.trace || {};
  const conf = Math.round(r.confidence * 100);

  const path = (t.stages || []).map((s) => `
      <li class="${esc(s.status)}">
        <div class="p-head"><span aria-hidden="true">${STEP_ICON[s.status] || ""}</span>${esc(s.stage)}</div>
        <div class="p-rule">${esc(s.rule)}</div>
        <div class="p-detail">${esc(s.detail)} <span class="sr">(${esc(s.status)})</span></div>
      </li>`).join("");

  const escalationChecks = (t.escalation_checks || [])
    .map((c) => checkRow(c.triggered ? "hit" : "ok", c.check, c.detail, "D5")).join("");
  // Rule tests are questions ("cost > 60%?"), not pass/fail, so yes/no is shown
  // neutrally; only an unanswerable test (missing input) is marked "?".
  const ruleChecks = (t.checks || []).map((c) => {
    if (c.result !== true && c.result !== false) return checkRow("unk", c.test, String(c.result), c.rule);
    return `<li>
        <span class="ck-icon ck-yn" aria-hidden="true">${c.result ? "Y" : "N"}</span>
        <div><div>${esc(c.test)}</div><div class="ck-detail">${c.result ? "yes" : "no"}</div></div>
        <span class="ck-rule">${esc(c.rule)}</span>
      </li>`;
  }).join("");

  const attention = [...(t.near_threshold || []), ...(t.missing_inputs || [])];
  const cb = t.cost_breakdown || {};

  resultEl.innerHTML = `
    <div class="verdict ${esc(r.decision)}">
      <div class="verdict-top">
        <span class="verdict-label">Recommended action</span>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[r.decision] || ""}</svg>
        <span class="verdict-action">${esc(ACTION[r.decision] || r.decision)}</span>
        ${t.rule ? `<span class="rule-chip" title="Deciding rule">rule ${esc(t.rule)}</span>` : ""}
      </div>
      <p class="verdict-reason">${esc(r.reason)}</p>
    </div>

    <div class="kpis">
      <div class="kpi"><div class="kpi-k">Est. repair cost</div><div class="kpi-v">${esc(money(r.estimated_repair_cost))}</div><div class="kpi-s">Rule D0</div></div>
      <div class="kpi"><div class="kpi-k">Cost vs replacement</div><div class="kpi-v">${esc(pct(t.cost_to_replacement_ratio))}</div><div class="kpi-s">${t.cost_to_replacement_ratio == null ? "replacement price or cost missing" : "of replacement price"}</div></div>
      <div class="kpi"><div class="kpi-k">Confidence</div><div class="kpi-v">${r.confidence.toFixed(2)}</div>
        <div class="meter" aria-hidden="true"><span style="width:${conf}%"></span></div><div class="kpi-s">heuristic, not a probability</div></div>
    </div>

    <div class="assist-card">
      <h3>Decision path</h3>
      <ol class="path">${path}</ol>
    </div>

    ${attention.length ? `<div class="assist-card"><h3>Needs attention</h3><ul class="flags">${attention.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}

    <div class="assist-card">
      <h3>Policy checks</h3>
      <ul class="checks">${escalationChecks}${ruleChecks}</ul>
    </div>

    <div class="assist-card">
      <h3>Cost breakdown</h3>
      <table class="cost">
        <tr><td>Parts</td><td>${esc(money(cb.parts))}</td></tr>
        <tr><td>Labour</td><td>${esc(money(cb.labour))}</td></tr>
        <tr><td>Travel (one way, per D0)</td><td>${esc(money(cb.travel))}</td></tr>
        <tr class="total"><td>Estimated repair cost</td><td>${esc(money(r.estimated_repair_cost))}</td></tr>
      </table>
    </div>

    <div class="assist-card">
      <h3>Agent actions</h3>
      <div class="agent-actions">
        <button type="button" class="btn ghost sm" id="copy-note">Copy case note</button>
        <button type="button" class="btn ghost sm" id="copy-json">Copy JSON response</button>
        <span class="copied" aria-live="polite"></span>
      </div>
      <details style="margin-top:10px"><summary>Raw response</summary><pre>${esc(JSON.stringify(stripTrace(r), null, 2))}</pre></details>
    </div>`;

  $("#copy-note").addEventListener("click", (e) => copyText(caseNote(r), e.currentTarget));
  $("#copy-json").addEventListener("click", (e) => copyText(JSON.stringify(stripTrace(r), null, 2), e.currentTarget));
}

function renderError(title, detail) {
  resultEl.innerHTML = `<div class="assist-card error-card"><h3>${esc(title)}</h3><p style="margin:0">${esc(detail)}</p></div>`;
}

function stripTrace(r) { const { trace, ...rest } = r; return rest; }

// ------------------------------------------------------------------ submit
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearErrors();
  const { body, errors } = readForm();
  if (errors.length) { showErrors(errors); return; }

  const btn = $("#decide-btn");
  btn.disabled = true;
  statusEl.textContent = "Evaluating policy…";
  try {
    const res = await fetch("/decide?explain=true", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 422) {
      showErrors(apiErrorsToFields(data.detail));
      statusEl.textContent = "The service rejected the input.";
    } else if (!res.ok) {
      renderError(`Service error ${res.status}`, data.detail || res.statusText);
      statusEl.textContent = "";
    } else {
      lastSubmitted = JSON.stringify(body);
      lastResult = data;
      staleEl.hidden = true;
      renderResult(data);
      statusEl.textContent = `Recommendation ready for ${data.case_id}.`;
    }
  } catch (err) {
    renderError("Could not reach the policy engine", `${err.message}. Is the service running on this machine?`);
    statusEl.textContent = "";
    checkHealth();
  } finally {
    btn.disabled = false;
  }
});

// ------------------------------------------------------------------ start
fill({ warranty_status: "unknown", customer_sentiment: "neutral", parts: [] });
renderEmpty();
checkHealth();
setInterval(checkHealth, 30000);
