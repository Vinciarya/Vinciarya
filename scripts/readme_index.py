"""Write the clickable half of the newspaper panel into README.md.

An SVG shown through an <img> can't carry working links -- GitHub renders it in
a restricted context where <a> inside the SVG is inert. So the panel links out
as a whole (to the lead story), and the sidebar headlines are re-emitted here as
real markdown links between the marker comments below.
"""

import json
import os

import typeset

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "..", "data", "feed.json")
README = os.path.join(HERE, "..", "README.md")

START = "<!-- daily-commit:start -->"
END = "<!-- daily-commit:end -->"

PANEL_WIDTH = 860       # must match newspaper.py's canvas, and the other panels
TITLE_CHARS = 38

# The emoji live here rather than in the SVG: colour glyphs clash with the
# panel's monochrome serif, and GitHub renders these natively.
SECTIONS = [
    ("ai", "🧠 **AI Wire**"),
    ("trending", "📦 **GitHub Trending**"),
    ("hn", "💬 **Hacker News**"),
    ("launches", "🚀 **Launches**"),
]


def md_escape(text):
    """Neutralise the markdown that shows up in real headlines."""
    for ch in ("\\", "[", "]", "*", "_", "`"):
        text = text.replace(ch, "\\" + ch)
    return text


def build_block(feed):
    lead = feed["lead"]
    alt = md_escape(lead["headline"]).replace('"', "")
    img = (f'<img src="./newspaper.svg" width="{PANEL_WIDTH}" '
           f'alt="The Daily Commit — {alt}" />')
    if lead.get("url"):
        img = f'<a href="{lead["url"]}">{img}</a>'

    rows = []
    for key, label in SECTIONS:
        items = feed.get("sections", {}).get(key, [])
        if items:
            rows.append(f"{label} · " + " · ".join(link(i) for i in items))

    infra = feed.get("infra", [])
    if infra:
        rows.append("⚠ **Infrastructure** · " + " · ".join(
            link({"title": f"{i['name']} {i['minutes']}min", "meta": i["impact"],
                  "url": i["url"]}) for i in infra))

    lines = [START, "", img, ""]
    if rows:
        # <sub> is inline: keep its opening and closing tags on the same lines
        # as the content so GitHub still applies markdown inside it
        lines += ["<sub>" + "<br>\n".join(rows) + "</sub>", ""]
    lines.append(END)
    return "\n".join(lines)


def link(item):
    title = md_escape(typeset.truncate(item["title"], TITLE_CHARS))
    text = f'[{title}]({item["url"]})' if item.get("url") else title
    return f"{text} `{item['meta']}`"


def splice(readme_text, block):
    """Replace the marked region, or insert it where the old <img> tag was."""
    if START in readme_text and END in readme_text:
        head, rest = readme_text.split(START, 1)
        _, tail = rest.split(END, 1)
        return head + block + tail
    raise SystemExit(
        f"README.md is missing the {START} / {END} markers — add them around the "
        "newspaper panel first.")


def main():
    with open(FEED, encoding="utf-8") as f:
        feed = json.load(f)
    with open(README, encoding="utf-8") as f:
        original = f.read()

    updated = splice(original, build_block(feed))
    if updated == original:
        print("README block unchanged")
        return
    with open(README, "w", encoding="utf-8") as f:
        f.write(updated)
    print("updated", README)


if __name__ == "__main__":
    main()
