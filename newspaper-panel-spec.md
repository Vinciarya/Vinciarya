# The Daily Commit — build spec

A self-updating newspaper front page for a GitHub profile README. Pulls the day's
developer news, typesets it as a broadsheet, commits the SVG back to the repo.

---

## 1. Overview

**What it is.** One SVG panel, ~486px wide (matching the existing wordmark panel),
laid out as a newspaper front page: masthead, dateline, lead story, sidebar briefs,
footer ticker. Rebuilt daily by a GitHub Action.

**Why this shape.** Every other panel in the profile is a terminal. This one is print —
serif typography, justified columns, a real grid. Maximum contrast against work already
shipped, and a register almost nobody attempts in a README.

**What makes it work.** The content is about the wider developer world, not self-reported
stats. It changes on its own. And the animation is deliberately restrained, because print
that wiggles stops reading as print.

---

## 2. Architecture

Three separate stages with a JSON file as the seam. Never collapse fetch and render into
one command — you will want to re-render fifty times while tuning the grid, without
hitting anyone's API.

```
  cron (daily)
       │
       ▼
  fetch.py ──────► data/feed.json  ──────► newspaper.py ──────► newspaper.svg
  (network)         (committed,              (pure, offline)      (committed)
                     readable diffs)
```

### Repo layout

```
.
├── .github/workflows/daily-feed.yml
├── scripts/
│   ├── fetch.py          # sources → feed.json
│   ├── newspaper.py      # feed.json → newspaper.svg
│   ├── typeset.py        # wrapping, justification, column maths
│   └── masthead.py       # font outlines → <path> data (run once)
├── assets/
│   ├── masthead.svgpath  # baked once, committed
│   └── fonts/            # OFL font used for the masthead
├── data/
│   └── feed.json
└── newspaper.svg
```

---

## 3. What you need

### Runtime

| Thing | Version | Why |
|---|---|---|
| Python | 3.11+ | `datetime.UTC`, better `zoneinfo` |
| `requests` | any | fetching |
| `fonttools` | 4.x | extracting glyph outlines for the masthead |

That's it. No PIL for this panel — nothing is rasterized. `pip install requests fonttools`.

### GitHub

- Actions enabled on the profile repo (`Vinciarya/Vinciarya`)
- Workflow permission `contents: write` so the Action can commit
- Settings → Actions → General → Workflow permissions set to read *and* write

### Secrets

| Secret | Required? | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | automatic | GitHub API calls, committing |
| `ANTHROPIC_API_KEY` | optional | writing the lead paragraph |

### A font you're allowed to redistribute

This one matters. Baking glyph outlines into a committed SVG is redistribution of the
font's design data. System fonts — Georgia, Futura, Times — are licensed for use on your
machine, not for shipping in a repo. Use an SIL OFL font instead, which explicitly
permits embedding and redistribution:

- **UnifrakturMaguntia** — blackletter, the classic newspaper masthead
- **Playfair Display** — high-contrast didone, more modern broadsheet
- **Libre Baskerville** — safe, readable, less dramatic

Commit the font file with its `OFL.txt` and you're clean. (I'm not a lawyer — but OFL is
unambiguous about this, and system fonts are unambiguously not.)

Body text needs no font file at all. It rides on `Georgia, 'Times New Roman', Times,
serif`, which resolves to a metric-compatible face on every platform.

---

## 4. Data sources

All keyless except GitHub, which uses the token the Action already has.

| Source | Endpoint | Gives you |
|---|---|---|
| Hacker News | `https://hacker-news.firebaseio.com/v0/topstories.json` then `/v0/item/{id}.json` | front-page stories, points, url, text |
| GitHub Releases | `GET /repos/{owner}/{repo}/releases/latest` | version, published date, release notes |
| GitHub Search | `GET /search/repositories?q=created:>{date}&sort=stars&order=desc&per_page=5` | repos gaining traction this week |
| Lobste.rs | `https://lobste.rs/hottest.json` | higher signal-to-noise than HN |
| dev.to | `https://dev.to/api/articles?top=1&per_page=5` | written pieces, has real descriptions |

**Rate limits.** GitHub authenticated: 5000/hr core, 30/min search. HN Firebase: no
practical limit. Lobsters and dev.to: be polite, one call each. A daily run uses maybe
25 requests total.

**Pin your release-radar list.** Ten to fifteen repos matching the stack actually in use —
runtimes, the AI/LLM tooling, the web framework. This is the highest-signal section
because it's "what shipped in the tools I use," not generic news.

**Filter HN hard.** Roughly a third of the front page isn't developer content. Require
150+ points *and* an allowlist on domain, or a politics headline lands on the profile.

---

## 5. feed.json schema

```json
{
  "generated": "2026-07-29",
  "edition": 214,
  "lead": {
    "headline": "BUN SHIPS 1.3.0",
    "deck": "Runtime claims 40% faster cold starts",
    "body": "Forty-five words of prose about the day's biggest story...",
    "source": "oven-sh/bun"
  },
  "briefs": [
    {"kind": "release",  "title": "Deno 2.4 lands",              "meta": "denoland/deno"},
    {"kind": "hn",       "title": "Writing a SQLite clone in Zig","meta": "412 pts"},
    {"kind": "rising",   "title": "nanoagent",                    "meta": "+1.2k stars/wk"}
  ],
  "ticker": ["Rust 1.92 stable", "Postgres 18 beta 2", "htmx 2.1"]
}
```

**Hash gate.** Serialize with `sort_keys=True`, drop `generated` and `edition`, hash it,
compare against the previous commit's. Identical → exit without committing. Without this
you commit every single day regardless of whether anything changed, and those commits
land in the contribution graph the neighbouring panel renders.

**Edition number.** Days since the repo was created. Increments on its own, costs nothing,
and does more for the newspaper illusion than any animation on the list.

---

## 6. The rendering constraints

Three limits shape every decision. SVG loaded through `<img>` is in restricted mode:

1. **No JavaScript.** Declarative animation only — SMIL and CSS `@keyframes` both work.
2. **No external resources.** No `@font-face`, no remote images. Everything self-contained.
3. **No text wrapping.** SVG has no `text-wrap`. `foreignObject` does not render in `<img>`
   context, so the usual escape hatch is closed.

### Consequences

**Masthead → vector paths.** Run `masthead.py` once locally: load the OFL font with
fontTools, walk each glyph with `SVGPathPen`, emit `<path d="...">`. Commit the result.
~3KB, renders identically forever, zero dependencies at view time.

**Body text → wrapped in Python.** One `<text>` element per line. Same approach as the
existing ASCII renderer, different content.

**Justification → `textLength` + `lengthAdjust="spacing"`.** Set `textLength` to the exact
column width on every line except the last of a paragraph. The browser distributes the
slack into word spaces and you get genuinely justified columns. Two rules: cap the stretch
at ~15% or you get rivers of white running down the column, and never hyphenate at these
widths.

---

## 7. Layout grid

Panel width 486px to match the existing wordmark panel. Height lands around 520px.

```
  ┌────────────────────────────────────────────────┐  ← 486 wide
  │              T H E   D A I L Y                 │
  │                C O M M I T                     │  masthead, ~64px, baked paths
  ├════════════════════════════════════════════════┤  double rule
  │  VOL. II · No. 214        WED 29 JULY 2026     │  dateline, 10px caps, tracked
  ├──────────────────────────┬─────────────────────┤
  │  BUN SHIPS 1.3.0         │  ALSO INSIDE        │
  │  ──────────────────      │  ─────────────      │
  │  Runtime claims 40%      │  · Deno 2.4 lands   │
  │  faster cold starts      │  · Zig SQLite clone │
  │                          │    tops HN at 412   │
  │  Body copy, justified,   │  · nanoagent gains  │
  │  ~43 chars per line at   │    1.2k stars       │
  │  12px Georgia...         │                     │
  ├──────────────────────────┴─────────────────────┤
  │  ALSO: Rust 1.92 · Postgres 18b2 · htmx 2.1    │  footer ticker
  └────────────────────────────────────────────────┘
```

**Measurements.** 18px page margin → 450px usable. Split 270 / 162 with an 18px gutter.
Georgia at 12px averages ~6.2px per character, so the lead column takes ~43 characters
and the sidebar ~26. Body leading 16px.

**Type scale.** Masthead 42px (paths). Dateline 9px caps, 1.5px letter-spacing. Headline
17px bold caps. Deck 11px italic. Body 12px. Ticker 9px.

---

## 8. Animation

Five effects, all restrained. Anything more and the print illusion collapses.

| Effect | How | Timing |
|---|---|---|
| Ink bleed on masthead | `feTurbulence` + `feDisplacementMap`, tiny `scale` | 8s loop, barely visible |
| Blocks settle | fade in + 4px `translateY`, staggered | 150ms apart, once |
| Date stamp | scale-in, slight rotation, holds | thumps at 1.2s |
| Halftone texture | one `<pattern>` of 1px dots, low opacity | static |
| Rule draw-in | `stroke-dashoffset` on the double rule | 0.6s, once |

### Theme

`prefers-color-scheme` inside the SVG's `<style>` works in `<img>` context, so the paper
can flip with the viewer's GitHub theme:

- **Light** — paper `#f4f1ea`, ink `#1a1a1a`, rules `#1a1a1a`
- **Dark** — paper `#12100e`, ink `#e8e2d5`, rules `#3a352e`

Roughly eight lines of CSS for both.

---

## 9. Workflow

```yaml
name: daily-feed
on:
  schedule:
    - cron: '0 2 * * *'      # 02:00 UTC = 07:30 IST
  workflow_dispatch:          # manual trigger, also keeps the schedule alive

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install requests fonttools
      - run: python scripts/fetch.py
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - run: python scripts/newspaper.py
      - name: commit if changed
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/feed.json newspaper.svg
          git diff --staged --quiet || git commit -m "feed: $(date -u +%F)"
          git push
```

**Keep the bot identity.** Don't set `user.email` to your own address. Bot commits aren't
attributed to your account, which keeps them out of the contribution graph the adjacent
panel renders.

---

## 10. Build order

Each phase produces something you can look at. Don't skip ahead — the typography is the
risky part and it needs no network at all.

1. **Hand-write `data/feed.json`.** Realistic content, including a pathologically long HN
   title. Ten minutes.
2. **`typeset.py` — wrapping and justification.** Get one justified column rendering
   correctly at 270px. This is the make-or-break piece. Verify no line stretches past 15%.
3. **`newspaper.py` — full static layout.** Masthead as plain text for now. Grid, rules,
   both columns, ticker. Open it in a browser until it looks like a newspaper.
4. **`masthead.py` — bake the outlines.** Swap the placeholder for real paths.
5. **Animation and theme.** All five effects, then `prefers-color-scheme`.
6. **`fetch.py` — one source only.** GitHub Releases, since it's the highest signal and
   the token is already there. Confirm the schema survives real data.
7. **Remaining sources plus filtering.** HN with the points threshold and domain allowlist.
8. **The LLM lead.** Optional, but it's what makes the page read as prose.
9. **The workflow.** `workflow_dispatch` first, run it by hand until it's clean, then
   enable the cron.

---

## 11. Gotchas checklist

- [ ] **Never render relative time.** "2h ago" is baked at build time; camo caching plus
      cron drift makes it wrong within the hour. Print the date.
- [ ] **Camo caching** — a fresh commit takes minutes to surface in the README. Not broken.
- [ ] **Scheduled workflows auto-disable** after 60 days of repo inactivity, and bot
      commits don't reliably reset the timer. Keep `workflow_dispatch` as the fallback.
- [ ] **GitHub cron drift** — a job scheduled for 02:00 may run at 02:20. Irrelevant daily.
- [ ] **Escape everything.** Headlines contain `&`, `<`, quotes. `html.escape()` on all of it.
- [ ] **Empty-day degradation.** If a source returns nothing, the layout must still hold.
      A quiet day is a thin paper, not a broken one.
- [ ] **Font licence** — ship `OFL.txt` alongside the font.
- [ ] **Truncate at word boundaries**, with a real ellipsis character, not three dots.

---

## 12. Done when

- Renders correctly from a hand-written `feed.json` with no network access
- Columns are justified with no visible rivers
- Masthead has no external font dependency
- Runs on cron, commits nothing when the feed is unchanged
- Bot commits don't appear in the contribution graph
- Reads as a newspaper in both light and dark themes
- Sits at 486px wide beside the existing wordmark panel
