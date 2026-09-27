"""Every text/background token pair of both themes meets WCAG 2.x AA (≥ 4.5:1)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from polmon.client.theme import STATUS_GLYPHS, TOKENS  # noqa: E402

TEXT_ON_SURFACES = [
    (text, background)
    for text in ("text", "text_secondary", "text_muted")
    for background in ("bg", "surface", "surface_alt", "surface_hover")
]
PAIRS = [
    *TEXT_ON_SURFACES,
    ("text", "accent_soft"),  # selected rows and list items
    ("accent", "surface"),  # links, flat buttons
    ("accent", "bg"),
    *[("accent_text", fill) for fill in ("accent", "accent_hover", "accent_pressed")],
    *[(tone, "surface") for tone in ("success", "warning", "danger", "info")],
    *[(tone, f"{tone}_soft") for tone in ("success", "warning", "danger", "info")],
    *[("text", f"{tone}_soft") for tone in ("success", "warning", "danger", "info")],
    *[(text, "nav_bg") for text in ("nav_text", "nav_muted", "nav_text_active")],
    ("nav_text", "nav_hover"),
    ("nav_text_active", "nav_active"),
]


def luminance(hex_color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    red, green, blue = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_formula_matches_reference_values() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("theme", sorted(TOKENS))
@pytest.mark.parametrize(("text", "background"), PAIRS)
def test_text_pairs_meet_aa(theme: str, text: str, background: str) -> None:
    tokens = TOKENS[theme]
    ratio = contrast(tokens[text], tokens[background])
    assert ratio >= 4.5, f"{theme}: {text} on {background} is {ratio:.2f}:1"


def test_status_is_never_colour_only() -> None:
    """Each status tone has its own glyph, so state never relies on colour alone."""
    assert len(set(STATUS_GLYPHS.values())) == len(STATUS_GLYPHS)
