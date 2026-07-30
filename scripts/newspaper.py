
import json
import os
from datetime import date

import typeset

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "..", "data", "feed.json")
OUT = os.path.join(HERE, "..", "newspaper.svg")

esc = typeset.escape

PANEL_WIDTH = 486
PAGE_MARGIN = 18
GUTTER = 18
LEAD_X = PAGE_MARGIN
LEAD_COL_WIDTH = typeset.LEAD_COL_WIDTH
LEAD_COL_CHARS = typeset.LEAD_COL_CHARS
SIDEBAR_X = PAGE_MARGIN + LEAD_COL_WIDTH + GUTTER
SIDEBAR_COL_WIDTH = typeset.SIDEBAR_COL_WIDTH
SIDEBAR_COL_CHARS = typeset.SIDEBAR_COL_CHARS
RULE_X1 = PAGE_MARGIN
RULE_X2 = PANEL_WIDTH - PAGE_MARGIN
TICKER_CHARS = 90
HEADLINE_CHARS = 30

PAPER = "#f4f1ea"
INK = "#1a1a1a"
BODY_FONT = "Georgia, 'Times New Roman', Times, serif"

MASTHEAD_SIZE = 42
DATELINE_SIZE = 9
HEADLINE_SIZE = 17
DECK_SIZE = 11
BODY_SIZE = 12
BODY_LEADING = 16
SIDEBAR_SIZE = 11
SIDEBAR_LEADING = 14
TICKER_SIZE = 9
TICKER_LEADING = 13
OUTAGE_SIZE = 10
OUTAGE_LEADING = 14


def text(x, y, s, size, anchor="start", weight="normal", style="normal",
         letter_spacing=None, text_length=None):
    attrs = (f'x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
             f'font-weight="{weight}" font-style="{style}"')
    if letter_spacing is not None:
        attrs += f' letter-spacing="{letter_spacing}"'
    if text_length is not None:
        attrs += f' textLength="{text_length:.1f}" lengthAdjust="spacing"'
    return f'<text {attrs}>{s}</text>'


def rule(y, x1=RULE_X1, x2=RULE_X2, width=1):
    return f'<line x1="{x1}" y1="{y:.1f}" x2="{x2}" y2="{y:.1f}" stroke="{INK}" stroke-width="{width}"/>'


def format_dateline(iso_date):
    d = date.fromisoformat(iso_date)
    return d.strftime("%a %d %b %Y").upper()


def wrapped_lines(raw, chars, x, size, leading, y, weight="normal", style="normal"):
    """Left-aligned (not justified) wrapped block. Returns (svg_parts, next_y)."""
    parts = []
    for line in typeset.wrap_text(raw, chars):
        parts.append(text(x, y, esc(line), size, weight=weight, style=style))
        y += leading
    return parts, y


def build(feed):
    parts = [""]  # index 0: background rect, filled in once height is known

    y = PAGE_MARGIN + MASTHEAD_SIZE * 0.8
    parts.append(text(PANEL_WIDTH / 2, y, "THE DAILY COMMIT", MASTHEAD_SIZE,
                       anchor="middle", weight="bold", letter_spacing=4))
    y += MASTHEAD_SIZE * 0.5

    parts.append(rule(y))
    parts.append(rule(y + 3))
    y += 3 + 11

    dateline_y = y + DATELINE_SIZE
    parts.append(text(LEAD_X, dateline_y, f"No. {feed['edition']}", DATELINE_SIZE,
                       letter_spacing=1.5))
    parts.append(text(RULE_X2, dateline_y, format_dateline(feed["generated"]),
                       DATELINE_SIZE, anchor="end", letter_spacing=1.5))
    y = dateline_y + 6
    parts.append(rule(y, width=0.5))
    y += 14

    content_top = y

    # -- lead column --------------------------------------------------------
    ly = content_top + HEADLINE_SIZE
    lead = feed["lead"]
    headline = typeset.truncate(lead["headline"].upper(), HEADLINE_CHARS)
    parts.append(text(LEAD_X, ly, esc(headline), HEADLINE_SIZE, weight="bold"))
    ly += HEADLINE_SIZE + 4
    parts.append(rule(ly, x1=LEAD_X, x2=LEAD_X + LEAD_COL_WIDTH, width=0.5))
    ly += 14

    dp, ly = wrapped_lines(lead["deck"], LEAD_COL_CHARS, LEAD_X, DECK_SIZE,
                            DECK_SIZE + 5, ly, style="italic")
    parts += dp
    ly += 8

    ly += BODY_SIZE  # first baseline
    for line in typeset.layout_paragraph(lead["body"], LEAD_COL_CHARS, LEAD_COL_WIDTH):
        parts.append(text(LEAD_X, ly, esc(line["text"]), BODY_SIZE,
                           text_length=line["text_length"]))
        ly += BODY_LEADING
    ly += 6
    parts.append(text(LEAD_X, ly, f"— {esc(lead['source'])}", DATELINE_SIZE,
                       style="italic"))
    ly += DATELINE_SIZE

    # -- sidebar column -------------------------------------------------------
    sy = content_top + DATELINE_SIZE
    parts.append(text(SIDEBAR_X, sy, "ALSO INSIDE", DATELINE_SIZE, weight="bold",
                       letter_spacing=1))
    sy += 6
    parts.append(rule(sy, x1=SIDEBAR_X, x2=SIDEBAR_X + SIDEBAR_COL_WIDTH, width=0.5))
    sy += SIDEBAR_SIZE + 8

    for brief in feed["briefs"]:
        raw = f"{brief['title']} — {brief['meta']}"
        lines = typeset.wrap_text(raw, SIDEBAR_COL_CHARS - 2)
        for i, line in enumerate(lines):
            prefix = "· " if i == 0 else ""
            x = SIDEBAR_X if i == 0 else SIDEBAR_X + 8
            parts.append(text(x, sy, prefix + esc(line), SIDEBAR_SIZE))
            sy += SIDEBAR_LEADING
        sy += 4

    y = max(ly, sy) + 10
    parts.append(rule(y))
    y += 16

    # -- footer ticker (degrades to nothing when empty) -----------------------
    ticker = feed.get("ticker", [])
    if ticker:
        raw = "ALSO: " + " · ".join(ticker)
        line = typeset.truncate(raw, TICKER_CHARS)
        parts.append(text(LEAD_X, y, esc(line), TICKER_SIZE, letter_spacing=0.5))
        y += TICKER_LEADING + 8

    # -- outages box (degrades to nothing when empty) --------------------------
    outages = feed.get("outages", [])
    if outages:
        box_h = 12 + len(outages) * OUTAGE_LEADING
        parts.append(f'<rect x="{PAGE_MARGIN}" y="{y:.1f}" width="{PANEL_WIDTH - 2*PAGE_MARGIN}" '
                      f'height="{box_h}" fill="none" stroke="{INK}" stroke-width="0.5"/>')
        oy = y + 8 + OUTAGE_SIZE * 0.7
        for outage in outages:
            line = f"{outage['name'].upper()}: {outage['status']}"
            parts.append(text(LEAD_X + 8, oy, esc(line), OUTAGE_SIZE))
            oy += OUTAGE_LEADING
        y += box_h

    y += PAGE_MARGIN
    height = round(y)

    parts[0] = f'<rect width="{PANEL_WIDTH}" height="{height}" fill="{PAPER}"/>'
    header = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{PANEL_WIDTH}" height="{height}" '
              f'viewBox="0 0 {PANEL_WIDTH} {height}" font-family="{BODY_FONT}" fill="{INK}">')
    return header + "".join(parts) + "</svg>"


if __name__ == "__main__":
    with open(FEED, encoding="utf-8") as f:
        feed = json.load(f)
    svg = build(feed)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote", OUT, len(svg), "bytes")
