from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "web" / "css" / "style.css").read_text(encoding="utf-8")
JS = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")


def test_chart_canvas_is_wrapped_in_fixed_frame():
    assert "chart-frame" in JS
    assert "chart-frame" in CSS
    assert ".chart-frame" in CSS
    assert "height: 220px" in CSS
    assert "max-height: 220px" in CSS


def test_css_does_not_set_canvas_height():
    assert ".chart-card canvas { width: 100%; height: 220px; }" not in CSS
    assert "chart-frame canvas" in CSS
