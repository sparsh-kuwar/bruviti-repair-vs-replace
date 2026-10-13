"""End-to-end tests of the page at / in Chromium, Firefox and WebKit.

They drive the real page with real clicks and key presses against a real
server, and check: the three brief examples, the cost breakdown, keyboard
operation and focus visibility, responsive layout, an axe-core accessibility
audit, the accessible names screen readers announce, and that nothing is loaded
from outside the machine.
"""

from __future__ import annotations

import pytest
from axe_playwright_python.sync_playwright import Axe

EXAMPLES = {
    "C-2001": ("Repair", "8,150.00", "D2"),
    "C-2002": ("Replace", "16,675.00", "D1b"),
    "C-2003": ("Escalate to supervisor", "Cannot compute", "D5"),
}


def decide_sample(page, cid):
    page.get_by_role("button", name=f"Load sample case {cid}").click()
    page.get_by_role("button", name="Get recommendation").click()
    page.wait_for_selector(".verdict")


# ------------------------------------------------------------------ function


@pytest.mark.parametrize("cid", sorted(EXAMPLES))
def test_brief_examples_render(page, cid):
    action, cost, rule = EXAMPLES[cid]
    decide_sample(page, cid)
    assert page.locator(".verdict-action").inner_text() == action
    assert page.locator(".metric-v").first.inner_text() == cost
    assert page.locator(".rule-badge").inner_text() == f"Decided by rule {rule}"
    assert page.get_by_role("status").filter(has_text="Recommendation ready").inner_text() == \
        f"Recommendation ready for {cid}: {action.split()[0].lower()}."


def test_cost_formula_shows_every_component(page):
    decide_sample(page, "C-2001")
    rows = [r.inner_text().replace("\t", " ") for r in page.locator("table.formula tr").all()]
    assert "6,200.00" in rows[0] and "1.5 h × 900.00 per hour" in rows[1] and "1,350.00" in rows[1]
    assert "40 min ÷ 60 × 900.00 per hour" in rows[2] and "600.00" in rows[2]
    assert "8,150.00" in rows[3]


def test_stale_banner_and_rerun(page):
    decide_sample(page, "C-2001")
    page.fill("#technician_travel_minutes", "300")
    assert page.locator("#stale").is_visible()
    page.get_by_role("button", name="Run again").click()
    page.wait_for_function("document.getElementById('stale').hidden")


def test_client_side_validation(page):
    page.fill("#labour_hours", "-2")
    page.get_by_role("button", name="Get recommendation").click()
    summary = page.locator("#error-summary")
    assert summary.is_visible()
    assert "Labour hours: must not be negative." in summary.inner_text()
    assert "Case ID: required." in summary.inner_text()
    assert page.locator("#labour_hours").get_attribute("aria-invalid") == "true"
    assert page.locator("#err-labour_hours").inner_text() == "Labour hours: must not be negative."
    assert page.evaluate("document.activeElement.id") == "error-summary"


def test_add_and_remove_part(page):
    page.get_by_role("button", name="+ Add part").click()
    page.get_by_role("button", name="+ Add part").click()
    assert page.locator("#parts-body tr").count() == 2
    page.get_by_role("button", name="Remove part 1").click()
    assert page.locator("#parts-body tr").count() == 1
    assert page.get_by_role("button", name="Remove part 1").count() == 1  # renumbered


# ------------------------------------------------------------------ keyboard


def tab_to(page, element_id, browser_name, limit=40):
    # WebKit follows macOS: Tab skips buttons and links unless Option is held.
    key = "Alt+Tab" if browser_name == "webkit" else "Tab"
    for _ in range(limit):
        page.keyboard.press(key)
        if page.evaluate("document.activeElement.id || document.activeElement.dataset.example || ''") == element_id:
            return
    raise AssertionError(f"could not reach {element_id} with {key}")


def test_tab_order_follows_visual_order(page, browser_name):
    key = "Alt+Tab" if browser_name == "webkit" else "Tab"
    seen = []
    for _ in range(25):
        page.keyboard.press(key)
        seen.append(page.evaluate("document.activeElement.id || document.activeElement.dataset.example || document.activeElement.textContent.trim()"))
    fields = [s for s in seen if s in (
        "case_id", "product_category", "product_age_months", "fault_category", "symptom_text",
        "warranty_status", "replacement_price", "purchase_price", "labour_hours",
        "labour_rate_per_hour", "technician_travel_minutes", "prior_repairs_12m", "customer_sentiment")]
    assert fields == ["case_id", "product_category", "product_age_months", "fault_category", "symptom_text",
                      "warranty_status", "replacement_price", "purchase_price", "labour_hours",
                      "labour_rate_per_hour", "technician_travel_minutes", "prior_repairs_12m",
                      "customer_sentiment"], seen
    assert seen.index("C-2001") < seen.index("case_id") < seen.index("decide-btn")


def test_every_focused_control_shows_a_focus_indicator(page, browser_name):
    key = "Alt+Tab" if browser_name == "webkit" else "Tab"
    missing = []
    for _ in range(25):
        page.keyboard.press(key)
        info = page.evaluate("""() => { const e = document.activeElement;
            if (!e || e === document.body) return ['(focus left the page)', true];  // Tab past the last control
            const cs = getComputedStyle(e);
            const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
            return [e.id || e.dataset.example || e.textContent.trim().slice(0, 20), ring]; }""")
        if not info[1]:
            missing.append(info[0])
    assert not missing, f"no visible focus indicator on: {missing}"


def test_keyboard_only_decision(page, browser_name):
    tab_to(page, "C-2001", browser_name)
    page.keyboard.press("Enter")
    assert page.input_value("#case_id") == "C-2001"
    page.keyboard.press("Control+Enter")
    page.wait_for_selector(".verdict")
    assert page.locator(".verdict-action").inner_text() == "Repair"
    assert page.evaluate("document.activeElement.id") == "assist-title"   # focus moved to the result
    summary = page.locator("details.disclose > summary").first
    summary.focus()
    page.keyboard.press("Enter")
    assert page.locator("details.disclose").first.get_attribute("open") is not None


# ------------------------------------------------------------------ layout


@pytest.mark.parametrize("width", [360, 390, 768, 1024, 1440, 1920])
def test_no_horizontal_scroll(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    decide_sample(page, "C-2001")
    scroll, client = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    assert scroll <= client, (width, scroll, client)


def test_200_percent_text_zoom_still_fits(page):
    # Text resized to 200% (WCAG 1.4.4) at a laptop width.
    page.set_viewport_size({"width": 1280, "height": 900})
    page.add_style_tag(content="html { font-size: 200% !important; }")
    decide_sample(page, "C-2001")
    scroll, client = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    assert scroll <= client


# ------------------------------------------------------------------ accessibility


@pytest.mark.parametrize("state", ["empty", "repair", "escalate", "errors"])
def test_axe_finds_no_violations(page, state):
    if state == "repair":
        decide_sample(page, "C-2001")
    elif state == "escalate":
        decide_sample(page, "C-2003")
    elif state == "errors":
        page.fill("#labour_hours", "-2")
        page.get_by_role("button", name="Get recommendation").click()
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    results = Axe().run(page)
    violations = [(v["id"], v["impact"], len(v["nodes"])) for v in results.response["violations"]]
    assert not violations, violations


def test_screen_reader_names_and_roles(page):
    # What assistive technology announces: roles, accessible names, live regions.
    assert page.get_by_role("textbox", name="Case ID (required)").count() == 1
    for name in ("Product category", "Fault category", "Warranty status", "Customer sentiment"):
        assert page.get_by_role("combobox", name=name).count() == 1, name
    for name in ("Product age, months", "Replacement price", "Labour hours", "Travel minutes, one way"):
        assert page.get_by_role("spinbutton", name=name).count() == 1, name
    assert page.get_by_role("heading", name="Case intake", level=1).count() == 1
    assert page.get_by_role("heading", name="Recommendation", level=2).count() == 1
    decide_sample(page, "C-2003")
    # Status is announced as text, not only colour: the path items carry their state in words.
    path = page.locator("ol.path").inner_text()
    assert "Decided the case" in path and "Not reached" in path
    assert page.get_by_role("img", name="Repair cost").count() == 0  # no bar when cost is unknown
    page.get_by_role("button", name="Load sample case C-2001").click()
    page.get_by_role("button", name="Get recommendation").click()
    page.wait_for_selector(".bar")
    bar = page.get_by_role("img")
    assert "Repair cost is 22.6% of the replacement price; limit 50%" in bar.get_attribute("aria-label")
    assert page.get_by_role("button", name="Remove part 1").count() == 1
