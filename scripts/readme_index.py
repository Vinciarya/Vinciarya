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

PANEL_WIDTH = 1000      # must match newspaper.py's canvas, and the other panels
TITLE_CHARS = 38

# Section labels are shields.io badges matching the GitHub/LinkedIn pair lower
# down the README. Only the labels are badges -- one per section, five images.
# Rendering every story as a badge would mean ~15 camo-proxied requests per
# page load, and headlines are far too long for a badge to hold.
# Each badge links to the source that section is drawn from.
# shields.io path encoding: space -> _, literal dash -> --, literal _ -> __
BADGE_STYLE = "for-the-badge"
SECTIONS = [
    # not "openai": shields.io still returns 200 for an unknown slug, it just
    # renders the badge with no icon -- verify any logo change actually draws
    ("ai", {"label": "AI_Wire", "color": "1a1a1a", "logo": "anthropic",
            "hub": "https://news.ycombinator.com/"}),
    ("trending", {"label": "GitHub_Trending", "color": "2EA043", "logo": "github",
                  "hub": "https://github.com/trending"}),
    ("hn", {"label": "Hacker_News", "color": "FF6600", "logo": "ycombinator",
            "hub": "https://news.ycombinator.com/"}),
    ("launches", {"label": "Launches", "color": "8B2500", "logo": "producthunt",
                  "hub": "https://news.ycombinator.com/show"}),
]
INFRA_BADGE = {"label": "Infrastructure", "color": "B00020", "logo": "statuspage",
               "hub": "https://www.githubstatus.com/"}


def badge(spec):
    src = (f"https://img.shields.io/badge/{spec['label']}-{spec['color']}"
           f"?style={BADGE_STYLE}&logo={spec['logo']}&logoColor=white")
    alt = spec["label"].replace("_", " ")
    return f'<a href="{spec["hub"]}"><img src="{src}" alt="{alt}" /></a>'


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
    for key, spec in SECTIONS:
        items = feed.get("sections", {}).get(key, [])
        if items:
            rows.append(f"{badge(spec)} <sub>"
                        + " · ".join(link(i) for i in items) + "</sub>")

    infra = feed.get("infra", [])
    if infra:
        rows.append(f"{badge(INFRA_BADGE)} <sub>" + " · ".join(
            link({"title": f"{i['name']} {i['minutes']}min", "meta": i["impact"],
                  "url": i["url"]}) for i in infra) + "</sub>")

    lines = [START, "", img, ""]
    if rows:
        # <sub> wraps only the links -- a badge inside it would be shrunk and
        # dropped to the subscript baseline
        lines += ["<br>\n".join(rows), ""]
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
