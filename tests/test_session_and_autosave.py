from pathlib import Path

from app.security import session_is_expired


def test_session_timeout_helper_uses_inactivity_window():
    assert not session_is_expired(None, now_ts=1_000, timeout_seconds=1_800)
    assert not session_is_expired(900, now_ts=1_000, timeout_seconds=1_800)
    assert session_is_expired(0, now_ts=1_801, timeout_seconds=1_800)
    assert not session_is_expired(0, now_ts=10_000, timeout_seconds=0)
    assert session_is_expired("broken", now_ts=10_000, timeout_seconds=1_800)


def test_new_requisition_forms_expose_autosave_markers():
    requisition_form = Path("app/templates/requisitions/form.html").read_text(encoding="utf-8")
    procurement_form = Path("app/templates/procurement/form.html").read_text(encoding="utf-8")
    app_js = Path("app/static/js/app.js").read_text(encoding="utf-8")

    assert 'data-autosave-form="stock-requisition-new"' in requisition_form
    assert 'data-autosave-form="procurement-non-stock-new"' in procurement_form
    assert "function initAutosaveForms()" in app_js
    assert "window.localStorage.setItem" in app_js


def test_non_stock_estimated_budget_input_is_optional():
    procurement_form = Path("app/templates/procurement/form.html").read_text(encoding="utf-8")

    assert 'name="estimated_budget"' in procurement_form
    assert 'name="estimated_budget" type="number" min="0" step="0.01" required' not in procurement_form
