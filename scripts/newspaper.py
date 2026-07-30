"""Typeset data/feed.json into an animated newspaper front page (newspaper.svg).

The panel is displayed in the README through an <img>, which puts the SVG in a
restricted context: CSS @keyframes, SMIL and prefers-color-scheme all work, but
<a> links, <script> and :hover do not. So every effect here is time-driven and
autonomous -- the page performs itself once on load, then settles into a slow
idle. Per-headline links live in the README markdown instead, written by
scripts/readme_index.py from the same feed.

Layout is a three-column grid at 860px, matching the width of the other README
panels. The lead story spans columns 1-2 with its body flowing across both;
column 3 carries the briefs.
"""

import json
import math
import os
import re
from datetime import date

import typeset

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "..", "data", "feed.json")
OUT = os.path.join(HERE, "..", "newspaper.svg")

esc = typeset.escape

# ---- grid -------------------------------------------------------------------
# The grid is solved so the canvas lands on exactly 1000: three 304px columns
# + two 24px gutters = 960 content, + 2x14 page margin = 988 paper, + 2x6 pad.
# CANVAS_PAD is the only non-printing space -- it holds the drop shadow and the
# travel of the idle float, so shrinking it further would clip both.
# 1000 is wider than GitHub's README column, and GitHub puts max-width:100% on
# markdown images, so the panel scales down to fill the column edge to edge on
# any viewport instead of leaving a band beside it.
CANVAS_PAD = 6
PAGE_MARGIN = 14
GUTTER = 24
COL_W = typeset.COL_WIDTH
COL_CHARS = typeset.COL_CHARS
COL_X = [PAGE_MARGIN + i * (COL_W + GUTTER) for i in range(3)]
CONTENT_WIDTH = 3 * COL_W + 2 * GUTTER
PANEL_WIDTH = CONTENT_WIDTH + 2 * PAGE_MARGIN          # 840
RULE_X1 = PAGE_MARGIN
RULE_X2 = PAGE_MARGIN + CONTENT_WIDTH
LEAD_SPAN = 2 * COL_W + GUTTER                          # headline/deck measure
VRULE_X = COL_X[2] - GUTTER / 2

BODY_FONT = "Georgia, 'Times New Roman', Times, serif"

MASTHEAD_SIZE = 68       # sized to fit CONTENT_WIDTH once textLength stretches it
DATELINE_SIZE = 10
HEADLINE_SIZE = 24
DECK_SIZE = 12
BODY_SIZE = 12
BODY_LEADING = 16
SIDEBAR_SIZE = 11
SIDEBAR_LEADING = 14
META_SIZE = 9
BANNER_SIZE = 10
TICKER_SIZE = 9
SECTION_SIZE = 10        # section heads, small caps
STANDFIRST_SIZE = 8.5    # the italic line under each section head
STANDFIRST_CHARS = 46    # a generated note must not overrun its column
DESC_CHARS = 44          # per-item description, sharing a line with the metric
KICKER_SIZE = 9

# Section heads. The second element is a *fallback* standfirst: fetch.py writes
# a live one into feed["notes"] describing what that run actually retrieved
# ("Top 4 of 19 stories"), and these are only used when that key is absent.
# Either way the line has to stay true to what fetch.py does -- "+28★" under
# GITHUB TRENDING means nothing unless the reader knows it is a delta.
# The emoji from the spec live in the README index instead -- colour glyphs
# clash with a monochrome serif page, and an <img>-embedded SVG can't load a
# font, so they'd render differently on every viewer's OS.
HEADS = {
    "ai": ("AI WIRE", "The day's biggest AI stories"),
    "trending": ("GITHUB TRENDING", "Stars gained since yesterday"),
    "hn": ("HACKER NEWS", "Top-voted, past 24 hours"),
    "launches": ("LAUNCHES", "Show HN and new repos this week"),
}

HEADLINE_CHARS = 44
DECK_CHARS = 98
BANNER_CHARS = 95

# ---- animation timeline (seconds) -----------------------------------------
# Edit here, not at the call sites. The whole performance is over by ~4.5s;
# after that only the ticker, the LIVE dot, the float and the grain keep going.
T_UNFOLD = 0.00
T_SHADOW = 0.30
T_MASTHEAD = 0.50
T_DATELINE = 0.78
T_RULES = 0.90
T_BANNER = 1.10
T_HEADLINE = 1.30
T_DECK = 1.75
T_BODY = 1.95
T_BODY_STEP = 0.055      # per printed line
T_COL2_OFFSET = 0.03     # right-hand body column trails the left, like a press
T_AI = 2.55              # AI Wire, alongside the lead story
T_TIER2 = 3.05           # the three lower sections
T_TIER2_STEP = 0.18      # per lower column, left to right
T_ITEM_STEP = 0.11       # per item within a section
T_COUNT = 3.05           # metrics start counting once their section is in
T_COUNT_STEP = 0.075     # per count-up frame
T_FOOTER = 4.15
T_TICKER = 4.45
T_LIVE = 4.70

COUNT_STEPS = 5
TICKER_SPEED = 34        # px per second


# ==== svg primitives =========================================================

def a(delay=None, **css):
    """style="..." carrying an animation delay and any inline custom props."""
    bits = []
    if delay is not None:
        bits.append(f"animation-delay:{delay:.2f}s")
    bits += [f"{k.replace('_', '-')}:{v}" for k, v in css.items()]
    return f' style="{";".join(bits)}"' if bits else ""


def text(x, y, s, size, anchor="start", weight="normal", style="normal",
         letter_spacing=None, text_length=None, cls=None, extra=""):
    attrs = (f'x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
             f'font-weight="{weight}" font-style="{style}"')
    if letter_spacing is not None:
        attrs += f' letter-spacing="{letter_spacing}"'
    if text_length is not None:
        attrs += f' textLength="{text_length:.1f}" lengthAdjust="spacing"'
    if cls:
        attrs += f' class="{cls}"'
    return f'<text {attrs}{extra}>{s}</text>'


def rule(y, delay, x1=RULE_X1, x2=RULE_X2, width=1, dur=None):
    """A rule that draws itself left to right via stroke-dashoffset."""
    css = {"--len": f"{x2 - x1}px"}
    if dur:
        css["animation-duration"] = f"{dur}s"
    return (f'<line class="rule" x1="{x1}" y1="{y:.1f}" x2="{x2}" y2="{y:.1f}" '
            f'stroke-width="{width}"{a(delay, **css)}/>')


def rule_v(x, y1, y2, delay, width=0.5, dur=0.9):
    """The column rule between the lead story and the briefs, drawn downward."""
    css = {"--len": f"{y2 - y1}px", "animation-duration": f"{dur}s"}
    return (f'<line class="rule" x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" '
            f'y2="{y2:.1f}" stroke-width="{width}"{a(delay, **css)}/>')


def wipe_reveal(inner, clip_id, box, delay, dur=0.5):
    """Wrap `inner` in a clip and slide a paper-coloured cover off it.

    Pure transform + static clip geometry -- no animated SVG attributes, which
    is the combination that renders identically across browsers inside an <img>.
    """
    x, y, w, h = box
    cover = (f'<rect class="wipe" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}"'
             + a(delay, **{"--w": f"{w:.1f}px", "animation-duration": f"{dur}s"}) + "/>")
    return (f'<clipPath id="{clip_id}"><rect x="{x:.1f}" y="{y:.1f}" '
            f'width="{w:.1f}" height="{h:.1f}"/></clipPath>'
            f'<g clip-path="url(#{clip_id})">{inner}{cover}</g>')


def format_dateline(iso_date):
    return date.fromisoformat(iso_date).strftime("%a %d %b %Y").upper()


# ==== count-up ===============================================================

def countup_frames(meta, steps=COUNT_STEPS):
    """Intermediate display values for a metric, or None if it isn't numeric.

    SVG can't animate the text content of a <text> node without script, so a
    count-up is really N stacked labels flicking through their turn. Handles
    the three shapes the feed produces: "819 pts", "7.4k★" and "+1,240★".
    """
    m = re.match(r"^(\+?)([\d,]+(?:\.[\d]+)?)(.*)$", meta.strip())
    if not m:
        return None
    sign, digits, suffix = m.groups()
    value = float(digits.replace(",", ""))
    decimals = 1 if "." in digits else 0
    grouped = "," in digits
    frames = []
    for i in range(1, steps):
        eased = 1 - (1 - i / steps) ** 3
        shown = f"{value * eased:,.{decimals}f}" if grouped else f"{value * eased:.{decimals}f}"
        frames.append(f"{sign}{shown}{suffix}")
    return frames


def counted_metric(x, y, meta, delay):
    """Right-aligned metric that counts up to its real value."""
    parts = []
    frames = countup_frames(meta)
    if frames:
        for i, frame in enumerate(frames):
            parts.append(text(x, y, esc(frame), META_SIZE, anchor="end", cls="meta tickframe",
                              extra=a(delay + i * T_COUNT_STEP,
                                      **{"animation-duration": f"{T_COUNT_STEP}s"})))
        delay += len(frames) * T_COUNT_STEP
    parts.append(text(x, y, esc(meta), META_SIZE, anchor="end", cls="meta ink",
                      extra=a(delay)))
    return parts


# ==== ticker =================================================================

def ticker_items(feed):
    """The Market rail: star movers first, then EOL warnings, CNBC-style.

    Market is empty until a second run has a baseline to diff against, and the
    EOL ticker is empty most days, so the rail falls back to the section items
    -- otherwise the one piece of permanent motion would usually be missing.
    """
    items = [f"{m['name']}  ▲ +{m['gained']:,}" for m in feed.get("market", [])]
    items += list(feed.get("ticker", []))
    if not items:
        for section in feed.get("sections", {}).values():
            for item in section:
                name = item["title"].split("/")[-1]
                items.append(f"{typeset.truncate(name, 38)}  ▲ {item['meta']}")
    return items


# ==== sections ===============================================================

def section_block(x, y, head, items, base, count_base):
    """One titled column of briefs. `head` is (label, standfirst).

    Returns (svg_parts, next_y).
    """
    label, standfirst = head
    parts = [text(x, y, label, SECTION_SIZE, weight="bold", letter_spacing=1.4,
                  cls="fade", extra=a(base))]
    y += 7
    parts.append(rule(y, base + 0.1, x1=x, x2=x + COL_W, width=0.5, dur=0.4))
    y += STANDFIRST_SIZE + 4
    parts.append(text(x, y, esc(standfirst), STANDFIRST_SIZE, style="italic",
                      cls="fade dim", extra=a(base + 0.15)))
    y += SIDEBAR_SIZE + 8

    for n, item in enumerate(items):
        rows = []
        for i, line in enumerate(typeset.wrap_text(item["title"], COL_CHARS - 2)):
            prefix = "· " if i == 0 else ""
            rows.append(text(x if i == 0 else x + 9, y, prefix + esc(line), SIDEBAR_SIZE))
            y += SIDEBAR_LEADING
        parts.append(f'<g class="slide"{a(base + 0.25 + n * T_ITEM_STEP)}>'
                     f'{"".join(rows)}</g>')
        # the description shares the metric's baseline -- left of the number,
        # so the extra context costs the page no height at all
        if item.get("desc"):
            parts.append(text(x + 9, y, esc(typeset.truncate(item["desc"], DESC_CHARS)),
                              META_SIZE, style="italic", cls="fade dim",
                              extra=a(base + 0.3 + n * T_ITEM_STEP)))
        parts += counted_metric(x + COL_W, y, item["meta"], count_base + n * T_ITEM_STEP)
        y += META_SIZE + 9
    return parts, y


# ==== page ===================================================================

def build(feed):
    defs = []
    parts = [""]        # slot 0: paper + shadow, filled once the height is known
    VRULE_SLOT = 1
    parts.append("")    # slot 1: the column rule, needs the final content height

    # -- masthead -------------------------------------------------------------
    y = PAGE_MARGIN + MASTHEAD_SIZE * 0.85
    # locked to the measure: the nameplate spans the full grid width exactly,
    # letting textLength open the tracking rather than guessing at letter-spacing
    parts.append(text(RULE_X1, y, "THE DAILY COMMIT", MASTHEAD_SIZE,
                      weight="bold", text_length=CONTENT_WIDTH,
                      cls="mast ink", extra=a(T_MASTHEAD)))
    y += MASTHEAD_SIZE * 0.42

    parts.append(rule(y, T_RULES))
    parts.append(rule(y + 3.5, T_RULES + 0.08))
    y += 3.5 + 12

    # -- dateline row ---------------------------------------------------------
    dateline_y = y + DATELINE_SIZE
    parts.append(text(RULE_X1, dateline_y, f"No. {feed['edition']}", DATELINE_SIZE,
                      letter_spacing=1.5, cls="stamp", extra=a(T_DATELINE)))
    parts.append(text(RULE_X2, dateline_y, format_dateline(feed["generated"]),
                      DATELINE_SIZE, anchor="end", letter_spacing=1.5,
                      cls="fade", extra=a(T_DATELINE + 0.1)))
    mid = PAGE_MARGIN + CONTENT_WIDTH / 2
    parts.append(f'<circle class="live-dot" cx="{mid - 22:.1f}" cy="{dateline_y - 3:.1f}" '
                 f'r="2.8"{a(T_LIVE)}/>')
    parts.append(text(mid - 14, dateline_y, "LIVE", DATELINE_SIZE, weight="bold",
                      letter_spacing=1.5, cls="fade accent", extra=a(T_LIVE)))
    y = dateline_y + 7
    parts.append(rule(y, T_RULES + 0.16, width=0.5))
    y += 13

    # -- infrastructure banner (only when something major actually broke) ------
    infra = feed.get("infra", [])
    if infra:
        banner = typeset.truncate(" · ".join(
            f"{i['name'].upper()} {i['minutes']}MIN"
            + (" ONGOING" if i["ongoing"] else "") for i in infra), BANNER_CHARS)
        bh = BANNER_SIZE + 11
        parts.append(f'<g class="banner"{a(T_BANNER)}>'
                     f'<rect x="{PAGE_MARGIN}" y="{y:.1f}" width="{CONTENT_WIDTH}" '
                     f'height="{bh}" class="banner-bg"/>'
                     + text(RULE_X1 + 9, y + bh - 7, "INFRASTRUCTURE", BANNER_SIZE, weight="bold",
                            letter_spacing=1.5, cls="banner-fg")
                     + text(RULE_X2 - 9, y + bh - 7, esc(banner), BANNER_SIZE,
                            anchor="end", letter_spacing=0.5, cls="banner-fg")
                     + "</g>")
        y += bh + 13

    content_top = y

    # -- tier 1: the lead story spans columns 1-2, AI Wire takes column 3 ------
    lead = feed["lead"]
    parts.append(text(COL_X[0], content_top + KICKER_SIZE, "FRONT PAGE", KICKER_SIZE,
                      weight="bold", letter_spacing=1.6, cls="fade dim",
                      extra=a(T_HEADLINE - 0.15)))
    ly = content_top + KICKER_SIZE + 8 + HEADLINE_SIZE
    headline = typeset.truncate(lead["headline"].upper(), HEADLINE_CHARS)
    parts.append(wipe_reveal(
        text(COL_X[0], ly, esc(headline), HEADLINE_SIZE, weight="bold"),
        "clipHead",
        (COL_X[0] - 2, ly - HEADLINE_SIZE - 3, LEAD_SPAN + 4, HEADLINE_SIZE + 10),
        T_HEADLINE, dur=0.6))
    ly += 10
    parts.append(rule(ly, T_HEADLINE + 0.55, x1=COL_X[0], x2=COL_X[0] + LEAD_SPAN,
                      width=0.5, dur=0.4))
    ly += 18

    deck_lines = typeset.wrap_text(lead["deck"], DECK_CHARS)
    deck_leading = DECK_SIZE + 6
    deck_svg = "".join(
        text(COL_X[0], ly + i * deck_leading, esc(line), DECK_SIZE, style="italic")
        for i, line in enumerate(deck_lines))
    parts.append(wipe_reveal(deck_svg, "clipDeck",
                             (COL_X[0] - 2, ly - DECK_SIZE - 3, LEAD_SPAN + 4,
                              len(deck_lines) * deck_leading + 5),
                             T_DECK, dur=0.75))
    ly += len(deck_lines) * deck_leading + 10

    # -- lead body flows across columns 1 and 2 --------------------------------
    body = typeset.layout_paragraph(lead["body"], COL_CHARS, COL_W)
    half = math.ceil(len(body) / 2)
    body_top = ly + BODY_SIZE
    for col, chunk in enumerate((body[:half], body[half:])):
        by = body_top
        for i, line in enumerate(chunk):
            parts.append(text(COL_X[col], by, esc(line["text"]), BODY_SIZE,
                              text_length=line["text_length"], cls="ink",
                              extra=a(T_BODY + i * T_BODY_STEP + col * T_COL2_OFFSET)))
            by += BODY_LEADING
    ly = body_top + half * BODY_LEADING
    body_end = T_BODY + half * T_BODY_STEP

    if lead.get("source"):
        ly += 4
        parts.append(text(COL_X[0], ly, f"— {esc(lead['source'])}", DATELINE_SIZE,
                          style="italic", cls="fade dim", extra=a(body_end + 0.2)))
        ly += DATELINE_SIZE

    sections = feed.get("sections", {})
    notes = feed.get("notes", {})

    def head(key):
        label, fallback = HEADS[key]
        return label, typeset.truncate(notes.get(key) or fallback, STANDFIRST_CHARS)

    ai_parts, ai_y = section_block(COL_X[2], content_top + SECTION_SIZE, head("ai"),
                                   sections.get("ai", []), T_AI, T_COUNT)
    parts += ai_parts

    tier1_bottom = max(ly, ai_y)
    parts[VRULE_SLOT] = rule_v(VRULE_X, content_top - 4, tier1_bottom, T_AI - 0.15)

    # -- tier 2: the remaining sections, one per column ------------------------
    # Empty sections are skipped rather than left as a hole, so trending and
    # market simply aren't there on day one until a star baseline exists.
    tier2 = [(head(key), sections.get(key, []))
             for key in ("trending", "hn", "launches") if sections.get(key)]

    y = tier1_bottom + 14
    if tier2:
        parts.append(rule(y, T_TIER2 - 0.25, width=0.5))
        y += 16
        tier2_top = y
        tier2_bottom = y
        for col, (col_head, items) in enumerate(tier2):
            base = T_TIER2 + col * T_TIER2_STEP
            block, end_y = section_block(COL_X[col], y + SECTION_SIZE, col_head, items,
                                         base, base)
            parts += block
            tier2_bottom = max(tier2_bottom, end_y)
        for col in range(1, len(tier2)):
            parts.append(rule_v(COL_X[col] - GUTTER / 2, tier2_top - 2, tier2_bottom,
                                T_TIER2 + col * T_TIER2_STEP - 0.15))
        y = tier2_bottom

    y += 12
    parts.append(rule(y, T_FOOTER))
    y += 9

    # -- ticker rail ----------------------------------------------------------
    items = ticker_items(feed)
    if items:
        rail_h = TICKER_SIZE + 13
        run = "   ·   ".join(items) + "   ·   "
        span = len(run) * TICKER_SIZE * 0.52          # estimated run width
        duration = max(span / TICKER_SPEED, 12)
        baseline = y + rail_h - 9
        defs.append(f'<clipPath id="clipRail"><rect x="{PAGE_MARGIN}" y="{y:.1f}" '
                    f'width="{CONTENT_WIDTH}" height="{rail_h}"/></clipPath>')
        # textLength pins each copy to exactly `span`, so the second abuts the
        # first and the loop is seamless -- an estimated width leaves a visible
        # gap or an overlap at the wrap point.
        tape = (text(0, baseline, esc(run), TICKER_SIZE, text_length=span)
                + text(span, baseline, esc(run), TICKER_SIZE, text_length=span))
        parts.append(
            f'<g class="fade" clip-path="url(#clipRail)"{a(T_TICKER - 0.25)}>'
            f'<rect x="{PAGE_MARGIN}" y="{y:.1f}" width="{CONTENT_WIDTH}" '
            f'height="{rail_h}" class="rail-bg"/>'
            f'<g class="rail"{a(T_TICKER, **{"--span": f"-{span:.1f}px", "animation-duration": f"{duration:.1f}s"})}>'
            f'<g transform="translate({PAGE_MARGIN},0)">{tape}</g></g></g>')
        y += rail_h

    y += PAGE_MARGIN
    height = round(y)
    canvas_w = PANEL_WIDTH + CANVAS_PAD * 2
    canvas_h = height + CANVAS_PAD * 2

    parts[0] = (f'<rect class="shade" x="1" y="2" width="{PANEL_WIDTH}" height="{height}"'
                + a(T_SHADOW) + "/>"
                + f'<rect class="paper" width="{PANEL_WIDTH}" height="{height}"/>')
    parts.append(f'<rect class="grain" width="{PANEL_WIDTH}" height="{height}"'
                 f' filter="url(#grain)"/>')

    # sigma is tuned to CANVAS_PAD: a wider blur would be clipped by the canvas
    defs.append('<filter id="soft" x="-20%" y="-20%" width="140%" height="140%">'
                '<feGaussianBlur stdDeviation="2.2"/></filter>')
    defs.append('<filter id="grain" x="0" y="0" width="100%" height="100%">'
                '<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" '
                'stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" '
        f'viewBox="0 0 {canvas_w} {canvas_h}" font-family="{BODY_FONT}">'
        f'<defs>{"".join(defs)}</defs>'
        f"<style>{STYLE}</style>"
        f'<g class="float"><g transform="translate({CANVAS_PAD},{CANVAS_PAD})">'
        f'<g class="unfold">{"".join(parts)}</g></g></g>'
        "</svg>"
    )


STYLE = """
:root{
  --paper:#f4f1ea; --ink:#1a1a1a; --dim:#6b6560; --accent:#8b2500;
  --shadow:rgba(20,16,10,.22); --rail:#e9e4d8;
}
@media (prefers-color-scheme:dark){
  :root{
    --paper:#15140f; --ink:#e8e3d5; --dim:#8d8578; --accent:#e08a52;
    --shadow:rgba(0,0,0,.5); --rail:#1e1c16;
  }
}
text{fill:var(--ink)}
.paper{fill:var(--paper)}
.shade{fill:var(--shadow);filter:url(#soft);animation:fade .6s ease-out both}
.grain{opacity:.05;mix-blend-mode:multiply;pointer-events:none;
  animation:breathe 9s ease-in-out infinite}
.rule{stroke:var(--ink);stroke-dasharray:var(--len);
  animation:draw .55s cubic-bezier(.22,.61,.36,1) both}
.wipe{fill:var(--paper);animation:wipe .5s cubic-bezier(.4,0,.2,1) both}
.ink{animation:ink .5s ease-out both}
.fade{animation:fade .5s ease-out both}
.mast{animation:ink .9s ease-out both}
.stamp{transform-box:fill-box;transform-origin:0 50%;animation:stamp .5s cubic-bezier(.2,1.5,.4,1) both}
.slide{animation:slide .45s cubic-bezier(.22,.61,.36,1) both}
.tickframe{opacity:0;animation:tick .08s linear both}
.meta{fill:var(--dim);font-style:italic}
.dim{fill:var(--dim)}
.accent{fill:var(--accent)}
.live-dot{fill:var(--accent);opacity:0;animation:pulse 2.2s ease-in-out infinite}
.banner{transform-box:fill-box;transform-origin:50% 0;
  animation:drop .55s cubic-bezier(.3,1.4,.5,1) both}
.banner-bg{fill:var(--accent)}
.banner-fg{fill:var(--paper)}
.rail-bg{fill:var(--rail)}
.rail{animation-name:marquee;animation-timing-function:linear;
  animation-iteration-count:infinite;animation-fill-mode:both}
.unfold{transform-box:fill-box;transform-origin:50% 0;
  animation:unfold .5s cubic-bezier(.22,.61,.36,1) both}
.float{transform-box:fill-box;transform-origin:50% 50%;
  animation:float 8s ease-in-out 5s infinite}

@keyframes unfold{from{opacity:0;transform:scaleY(.9)}to{opacity:1;transform:scaleY(1)}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes ink{from{opacity:0;filter:blur(2.2px)}to{opacity:1;filter:blur(0)}}
@keyframes draw{from{stroke-dashoffset:var(--len)}to{stroke-dashoffset:0}}
@keyframes wipe{from{transform:translateX(0)}to{transform:translateX(var(--w))}}
@keyframes stamp{0%{opacity:0;transform:scale(.8)}60%{opacity:1;transform:scale(1.06)}
  100%{opacity:1;transform:scale(1)}}
@keyframes slide{from{opacity:0;transform:translateX(12px)}to{opacity:1;transform:translateX(0)}}
@keyframes drop{0%{opacity:0;transform:translateY(-14px)}70%{opacity:1;transform:translateY(2px)}
  100%{opacity:1;transform:translateY(0)}}
@keyframes tick{0%{opacity:0}10%{opacity:1}90%{opacity:1}100%{opacity:0}}
@keyframes marquee{from{transform:translateX(0)}to{transform:translateX(var(--span))}}
@keyframes pulse{0%,100%{opacity:.2}50%{opacity:1}}
@keyframes breathe{0%,100%{opacity:.04}50%{opacity:.065}}
@keyframes float{0%,100%{transform:translateY(0) rotate(0)}
  50%{transform:translateY(-3px) rotate(.16deg)}}
@media (prefers-reduced-motion:reduce){
  *{animation-duration:.01ms !important;animation-iteration-count:1 !important}
  .wipe{opacity:0}
}
"""


if __name__ == "__main__":
    with open(FEED, encoding="utf-8") as f:
        feed = json.load(f)
    svg = build(feed)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote", OUT, len(svg), "bytes")
