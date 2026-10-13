"use strict";
// Single-page form for POST /decide. No frameworks, no network calls except
// to this same server. Numeric fields: blank -> null; anything that is not a
// finite, non-negative number is blocked here so NaN/Infinity/strings are
// never sent.

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
}

$("#add-part").addEventListener("click", () => addPart().querySelector("input").focus());

// ------------------------------------------------------------------ fill / clear
function fill(data) {
  clearErrors();
  for (const name of SCALAR_FIELDS) {
    const el = form.elements[name];
    const v = data[name];
    el.value = v === null || v === undefined ? "" : String(v);
  }
  partsBody.replaceChildren();
  (data.parts || []).forEach(addPart);
}

function clearForm() {
  fill({ warranty_status: "unknown", customer_sentiment: "neutral", parts: [] });
  resultEl.innerHTML = '<p class="empty">Fill in a case or load an example, then choose <strong>Decide</strong>.</p>';
  statusEl.textContent = "";
  $("#case_id").focus();
}

document.querySelectorAll("[data-example]").forEach((btn) =>
  btn.addEventListener("click", () => {
    fill(EXAMPLES[btn.dataset.example]);
    statusEl.textContent = `Loaded example ${btn.dataset.example}.`;
  })
);
$("#clear-btn").addEventListener("click", clearForm);

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
  // list: [[inputElementOrNull, message], ...]
  const ul = summary.querySelector("ul");
  ul.replaceChildren();
  for (const [input, msg] of list) {
    const li = document.createElement("li");
    if (input) {
      input.setAttribute("aria-invalid", "true");
      const slot = document.getElementById(`err-${input.name || ""}`);
      if (slot && input.name) slot.textContent = msg;
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
  // FastAPI 422: [{loc: ["body", "parts", 0, "price"], msg: "..."}]
  return (Array.isArray(detail) ? detail : [{ loc: [], msg: String(detail) }]).map((d) => {
    const loc = (d.loc || []).filter((x) => x !== "body");
    let input = null;
    if (loc[0] === "parts" && typeof loc[1] === "number") input = document.getElementById(`parts-${loc[1]}-${loc[2]}`);
    else if (loc.length) input = form.elements[loc[0]] || null;
    const where = loc.length ? loc.join(".") : "request";
    return [input, `${where}: ${d.msg.replace(/^Value error, /, "")}`];
  });
}

// ------------------------------------------------------------------ result
const ICONS = {
  repair: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
  replace: '<path d="M4 4v6h6M20 20v-6h-6"/><path d="M20 10a8 8 0 0 0-14.9-3M4 14a8 8 0 0 0 14.9 3"/>',
  escalate: '<path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18h.01"/>',
};
const LABELS = { repair: "REPAIR", replace: "REPLACE", escalate: "ESCALATE — needs a person" };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const money = (v) => (v === null ? "Cannot compute" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

function renderResult(r) {
  const t = r.trace || {};
  const list = (items) => (items && items.length ? `<ul class="flags">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p class='note'>None.</p>");
  const checks = (t.checks || []).map((c) =>
    `<tr><td>${esc(c.rule)}</td><td>${esc(c.test)}</td><td>${esc(c.result === true ? "yes" : c.result === false ? "no" : c.result)}</td></tr>`).join("");
  const cb = t.cost_breakdown || {};
  const pct = Math.round(r.confidence * 100);
  resultEl.innerHTML = `
    <div class="badge ${esc(r.decision)}">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[r.decision] || ""}</svg>
      <span>${esc(LABELS[r.decision] || r.decision)}</span>
      ${t.rule ? `<span class="rule" title="Deciding rule">rule ${esc(t.rule)}</span>` : ""}
    </div>
    <dl class="facts">
      <dt>Case ID</dt><dd>${esc(r.case_id)}</dd>
      <dt>Estimated repair cost</dt><dd>${esc(money(r.estimated_repair_cost))}</dd>
      <dt>Confidence</dt><dd>${r.confidence.toFixed(2)}<div class="meter" aria-hidden="true"><span style="width:${pct}%"></span></div></dd>
    </dl>
    <p class="reason">${esc(r.reason)}</p>
    <p class="note">Confidence is a rule-based heuristic (lowered for unknown warranty, values within 2 percentage points of a threshold, and missing inputs), not a calibrated probability.</p>
    <details open><summary>Why: checks the engine ran</summary>
      <table class="checks"><thead><tr><th scope="col">Rule</th><th scope="col">Test</th><th scope="col">Result</th></tr></thead><tbody>${checks || "<tr><td colspan='3'>Escalation rules decided before cost-ratio rules ran.</td></tr>"}</tbody></table>
    </details>
    <details><summary>Cost breakdown and flags</summary>
      <dl class="facts">
        <dt>Parts</dt><dd>${esc(cb.parts ?? "unknown")}</dd>
        <dt>Labour</dt><dd>${esc(cb.labour ?? "unknown")}</dd>
        <dt>Travel</dt><dd>${esc(cb.travel ?? "unknown")}</dd>
        <dt>Cost / replacement</dt><dd>${t.cost_to_replacement_ratio == null ? "n/a" : (t.cost_to_replacement_ratio * 100).toFixed(1) + "%"}</dd>
      </dl>
      <strong>Near a threshold</strong>${list(t.near_threshold)}
      <strong>Missing inputs that did not change the decision</strong>${list(t.missing_inputs)}
      <strong>Safety hazards in text</strong>${list(t.safety_hazards)}
      <strong>Contradictions</strong>${list(t.contradictions)}
    </details>
    <details><summary>Raw JSON response</summary><pre>${esc(JSON.stringify(stripTrace(r), null, 2))}</pre></details>`;
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
  statusEl.textContent = "Deciding…";
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
      showErrors([[null, `Service error ${res.status}: ${data.detail || res.statusText}`]]);
      statusEl.textContent = "";
    } else {
      renderResult(data);
      statusEl.textContent = `Decision ready for ${data.case_id}.`;
    }
  } catch (err) {
    showErrors([[null, `Could not reach the service: ${err.message}. Is it running on this machine?`]]);
    statusEl.textContent = "";
  } finally {
    btn.disabled = false;
  }
});

fill({ warranty_status: "unknown", customer_sentiment: "neutral", parts: [] });
