"""Offline text wrapping and justification maths for the newspaper panel.

No network, no rendering — pure functions over strings, tested against
data/feed.json. SVG has no text-wrap, so wrapping happens here in Python;
justification happens in the browser via textLength, which this module
only computes the parameters for.
"""
import html

GEORGIA_AVG_CHAR_WIDTH = 6.2  # px, at 12px body size (spec measurement)
MAX_STRETCH = 0.15            # cap on textLength stretch before rivers appear

LEAD_COL_WIDTH = 270
LEAD_COL_CHARS = 43
SIDEBAR_COL_WIDTH = 162
SIDEBAR_COL_CHARS = 26


def escape(text):
    return html.escape(text, quote=True)


def wrap_text(text, max_chars):
    """Greedy word-boundary wrap. Never splits a word, never hyphenates."""
    words = text.split()
    lines = []
    current = []
    current_len = 0
    for word in words:
        add_len = len(word) + (1 if current else 0)
        if current and current_len + add_len > max_chars:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += add_len
    if current:
        lines.append(" ".join(current))
    return lines


def truncate(text, max_chars, ellipsis="…"):
    """Truncate at a word boundary with a real ellipsis character."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + ellipsis


def justify_width(line, target_width_px, avg_char_width=GEORGIA_AVG_CHAR_WIDTH,
                   max_stretch=MAX_STRETCH):
    """textLength to set for a line, or None if it shouldn't be justified.

    Returns None when the line is empty or would need more than
    max_stretch of extra spacing to fill the column (that's how rivers
    happen) — the caller should render that line at its natural width.
    """
    natural_width = len(line) * avg_char_width
    if natural_width == 0:
        return None
    stretch = (target_width_px / natural_width) - 1
    if stretch > max_stretch:
        return None
    return target_width_px


def layout_paragraph(text, max_chars, target_width_px,
                      avg_char_width=GEORGIA_AVG_CHAR_WIDTH,
                      max_stretch=MAX_STRETCH):
    """Wrap a paragraph and compute per-line justification.

    Returns a list of {"text": line, "text_length": px|None}. The last
    line of the paragraph is never justified — that's what makes it read
    as a real paragraph end instead of a stretched-out final line.
    """
    lines = wrap_text(text, max_chars)
    result = []
    for i, line in enumerate(lines):
        is_last = i == len(lines) - 1
        text_length = None if is_last else justify_width(
            line, target_width_px, avg_char_width, max_stretch)
        result.append({"text": line, "text_length": text_length})
    return result


if __name__ == "__main__":
    import json
    from pathlib import Path

    feed = json.loads((Path(__file__).parent.parent / "data" / "feed.json").read_text())
    lines = layout_paragraph(feed["lead"]["body"], LEAD_COL_CHARS, LEAD_COL_WIDTH)
    print(f"Lead body wrapped to {len(lines)} lines at {LEAD_COL_CHARS} chars / {LEAD_COL_WIDTH}px:\n")
    for l in lines:
        natural = len(l["text"]) * GEORGIA_AVG_CHAR_WIDTH
        stretch = (l["text_length"] / natural - 1) if l["text_length"] else None
        stretch_str = f"{stretch:.1%}" if stretch is not None else "not justified (last line)"
        print(f"  [{len(l['text']):2d} chars] {l['text']!r:70s} stretch={stretch_str}")
