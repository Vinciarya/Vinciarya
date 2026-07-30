
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "..", "data", "feed.json")
STARS_PATH = os.path.join(HERE, "..", "data", "stars.json")
REPO = "Vinciarya/Vinciarya"  # used only to compute the edition number

GH_API = "https://api.github.com"
HN_API = "https://hn.algolia.com/api/v1"
EOL_API = "https://endoflife.date/api"

STATUSPAGES = {
    "GitHub": "https://www.githubstatus.com/api/v2/summary.json",
    "npm": "https://status.npmjs.org/api/v2/summary.json",
    "Cloudflare": "https://www.cloudflarestatus.com/api/v2/summary.json",
    "OpenAI": "https://status.openai.com/api/v2/summary.json",
    "Anthropic": "https://status.anthropic.com/api/v2/summary.json",
    "Vercel": "https://www.vercelstatus.com/api/v2/summary.json",
}

# ---- config: edit these to match your actual stack -------------------------
# Spec calls for 10-15 repos matching the runtimes/tooling you actually use
# (newspaper-panel-spec.md #4). Starts with just Bun since that's what every
# fixture so far has been tested against -- add your own.
RELEASE_REPOS = ["oven-sh/bun"]

EOL_PRODUCTS = ["nodejs"]

# Per-section caps. The panel is a fixed grid: an uncapped list on a busy news
# day would run past the bottom of the page.
MAX_AI = 3
MAX_LAUNCHES = 4
MAX_TRENDING = 4
MAX_HN = 4
MAX_MARKET = 8      # ticker rail
MAX_INFRA = 2

HN_MIN_POINTS = 150
# No domain allowlist: the old one cut a typical day from 19 stories to 2,
# which cannot fill the AI Wire, Hacker News and Launches sections at once.
# The points threshold is the quality gate now.

AI_PATTERN = re.compile(
    r"\b(ai|llm|llms|gpt|claude|gemini|openai|anthropic|mistral|llama|"
    r"model|models|agent|agents|transformer|inference|embedding|diffusion|"
    r"rag|prompt|fine-?tun\w*|neural|machine learning)\b", re.I)
# ------------------------------------------------------------------------

GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "llama-3.1-8b-instant"

GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GH_TOKEN:
    GH_HEADERS["Authorization"] = f"Bearer {GH_TOKEN}"


# ==== GitHub Releases (lead story) ==========================================

def fetch_release(repo):
    """Raw release JSON, or None if the repo has no releases (404)."""
    r = requests.get(f"{GH_API}/repos/{repo}/releases/latest", headers=GH_HEADERS, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def first_paragraph(body):
    """Best-effort first prose paragraph from a release body.

    Real release bodies are often install instructions + a contributor list
    + a link to a blog post, not changelog prose (confirmed against the Bun
    fixture, which is entirely this shape). Skip anything that isn't a
    normal paragraph of sentences: code fences (anywhere in the block, not
    just at the start -- a "Windows:" label followed by a fenced snippet
    isn't prose either), headings, install/upgrade boilerplate, and
    markdown lists (a contributor list survives length-only filtering
    once its `[@x](url)` links are stripped down to bare names).
    """
    if not body:
        return None
    for para in body.replace("\r\n", "\n").split("\n\n"):
        para = para.strip()
        if not para or "```" in para or para.startswith("#"):
            continue
        if para.lower().startswith("to install") or para.lower().startswith("to upgrade"):
            continue
        lines = para.split("\n")
        list_lines = sum(1 for l in lines if l.strip().startswith(("-", "*", "•")))
        if list_lines / len(lines) > 0.5:
            continue
        text = re.sub(r"[*_`]", "", para)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = " ".join(text.split())
        if len(text) > 40:
            return text
    return None


def groq_prose(repo, tag, raw_body):
    """Ask Groq for a (deck, body) pair. None if unset/unavailable/malformed."""
    if not GROQ_API_KEY:
        return None
    prompt = (
        f"Write a two-line newspaper blurb about the GitHub release {repo} {tag}.\n"
        f"Release notes:\n{(raw_body or '(no notes provided)')[:2000]}\n\n"
        "Reply with exactly two lines, no labels, no quotes:\n"
        "Write flowing prose only -- no code, no shell commands, no URLs, no "
        "install or upgrade instructions. Report what changed and why it matters.\n"
        "1. a one-sentence deck, under 90 characters\n"
        # the lead body fills two 40-char columns on the panel; ~100 words is
        # what it takes to set them both without leaving the page half empty
        "2. a 95-115 word body paragraph in neutral news style"
    )
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 400,
            },
            timeout=15,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        lines = [l.strip(" -12.") for l in content.split("\n") if l.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    except (requests.RequestException, KeyError, IndexError):
        pass
    return None


def assemble_lead(repo, tag, prose, groq_result, url=""):
    """Pure: turn a prose paragraph and/or a Groq result into a lead dict."""
    if groq_result:
        deck, body = groq_result
    elif prose:
        deck = prose.split(". ")[0][:90]
        body = prose[:700]
    else:
        deck = f"See release notes on {repo}"
        body = (f"{repo} shipped {tag}. The release notes on GitHub didn't include "
                f"enough changelog prose to summarize automatically -- see the "
                f"repo's releases page for details.")
    return {
        "headline": f"{repo.split('/')[-1].upper()} SHIPS {tag.upper()}",
        "deck": deck,
        "body": body,
        "source": repo,
        "url": url or f"https://github.com/{repo}/releases/tag/{tag}",
    }


def build_lead(repo):
    raw = fetch_release(repo)
    if raw is None or raw.get("draft") or raw.get("prerelease"):
        return None
    tag = raw["tag_name"]
    prose = first_paragraph(raw.get("body"))
    groq_result = groq_prose(repo, tag, raw.get("body"))
    return assemble_lead(repo, tag, prose, groq_result, raw.get("html_url", ""))


# ==== Hacker News (briefs) ===================================================

def fetch_hn_hits(min_points=HN_MIN_POINTS):
    since_unix = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    params = {
        "tags": "story",
        "numericFilters": f"created_at_i>{since_unix},points>{min_points}",
        "hitsPerPage": 20,
        "attributesToRetrieve": "title,url,points,num_comments,author,created_at,objectID",
    }
    r = requests.get(f"{HN_API}/search", params=params, timeout=10)
    r.raise_for_status()
    return r.json()["hits"]


def parse_hn_hit(hit):
    """Pure: one HN hit -> a brief dict."""
    url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
    return {"kind": "hn", "title": hit["title"], "meta": f"{hit['points']} pts", "url": url}


def is_ai_story(title):
    return bool(AI_PATTERN.search(title))


def is_launch(title):
    return title.strip().lower().startswith("show hn")


def fetch_hn_briefs():
    return [parse_hn_hit(h) for h in fetch_hn_hits()]


# ==== GitHub Search (rising repos) ==========================================

def fetch_rising_items(days=7, min_stars=100, per_page=5):
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    params = {
        "q": f"created:>{since_iso} stars:>{min_stars}",
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    r = requests.get(f"{GH_API}/search/repositories", params=params, headers=GH_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()["items"]


def parse_rising_item(item):
    """Pure: one search-result repo -> a brief dict."""
    stars = item["stargazers_count"]
    meta = f"{stars/1000:.1f}k★" if stars >= 1000 else f"{stars}★"
    return {"kind": "rising", "title": item["full_name"], "meta": meta,
            "url": item["html_url"]}


# ==== endoflife.date (ticker) ================================================

def fetch_eol_cycles(product):
    r = requests.get(f"{EOL_API}/{product}.json", timeout=10)
    if r.status_code != 200:
        return []
    return r.json()


def parse_eol_cycles(cycles, product, today=None, window_days=90):
    """Pure: legacy-schema cycles -> ticker strings for EOLs in the next N days.

    eol is a union type -- a date string, or a bool meaning "ongoing" (False)
    or "EOL with no known date" (True). Only the date-string case is
    reportable here.
    """
    today = today or date.today()
    window_end = today + timedelta(days=window_days)
    out = []
    for cycle in cycles:
        eol = cycle.get("eol")
        if not isinstance(eol, str):
            continue
        eol_date = date.fromisoformat(eol)
        if today < eol_date <= window_end:
            out.append(f"{product} {cycle['cycle']} EOL {eol}")
    return out


def fetch_eol_ticker():
    ticker = []
    for product in EOL_PRODUCTS:
        ticker += parse_eol_cycles(fetch_eol_cycles(product), product)
    return ticker


# ==== Statuspage (infrastructure) ============================================
# Reports incidents from the last 24h rather than live status. A newspaper
# publishes once a day: "Cloudflare is degraded right now" is false within the
# hour, but "Cloudflare Workers was down 28 minutes" stays true all day.

def fetch_incidents(url):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def parse_incidents(data, name, now=None, window_hours=24,
                    impacts=("major", "critical")):
    """Pure: recent incidents worth a front-page banner, newest first.

    Only major/critical get reported -- the spec is "only if something major
    broke", and minor Statuspage entries are near-permanent background noise.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    out = []
    for inc in data.get("incidents", []):
        if inc.get("impact") not in impacts:
            continue
        started = datetime.fromisoformat(inc["created_at"].replace("Z", "+00:00"))
        if started < cutoff:
            continue
        resolved_at = inc.get("resolved_at")
        ended = (datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
                 if resolved_at else now)
        out.append({
            "name": name,
            "title": inc["name"],
            "impact": inc["impact"],
            "minutes": max(int((ended - started).total_seconds() // 60), 1),
            "ongoing": resolved_at is None,
            "url": inc.get("shortlink", ""),
        })
    return out


def fetch_infra():
    infra = []
    for name, url in STATUSPAGES.items():
        try:
            data = fetch_incidents(url.replace("summary.json", "incidents.json"))
        except requests.RequestException:
            continue
        infra += parse_incidents(data, name)
    infra.sort(key=lambda i: (not i["ongoing"], -i["minutes"]))
    return infra[:MAX_INFRA]


# ==== star history (trending + market) =======================================
# GitHub has no trending API, so "trending" is computed here as the change in
# star count since yesterday's snapshot. Day one has no baseline and yields
# nothing, by design -- the sections simply don't render.

def fetch_star_pool(days=7, min_stars=5000, per_page=100):
    """One search call covering the large, actively-pushed repos."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    r = requests.get(f"{GH_API}/search/repositories",
                     params={"q": f"pushed:>{since} stars:>{min_stars}",
                             "sort": "stars", "order": "desc", "per_page": per_page},
                     headers=GH_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()["items"]


def build_star_snapshot(rising_items):
    """{full_name: stars} for today. The freshly-launched repos are merged in
    explicitly -- they are the fastest movers but too small for the pool query.
    """
    snapshot = {i["full_name"]: i["stargazers_count"] for i in fetch_star_pool()}
    snapshot.update({i["full_name"]: i["stargazers_count"] for i in rising_items})
    return snapshot


def star_deltas(snapshot, previous):
    """Pure: [(repo, gained, total)] sorted by stars gained since the last run."""
    if not previous:
        return []
    gains = [(repo, stars - previous[repo], stars)
             for repo, stars in snapshot.items()
             if repo in previous and stars > previous[repo]]
    return sorted(gains, key=lambda g: -g[1])


# ==== edition number ==========================================================

def edition_number():
    """Days since the repo was created. Uses the GitHub API rather than local
    git history because actions/checkout@v4 defaults to a shallow clone,
    which wouldn't have the real first commit to measure from.
    """
    r = requests.get(f"{GH_API}/repos/{REPO}", headers=GH_HEADERS, timeout=10)
    r.raise_for_status()
    created = datetime.fromisoformat(r.json()["created_at"].replace("Z", "+00:00")).date()
    return (date.today() - created).days


# ==== assembly + hash gate ====================================================

def feed_hash(feed):
    material = {k: v for k, v in feed.items() if k not in ("generated", "edition")}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def build_feed(previous=None, prev_stars=None):
    lead = None
    for repo in RELEASE_REPOS:
        lead = build_lead(repo)
        if lead:
            break
    if lead is None and previous:
        lead = previous.get("lead")
    if lead is None:
        lead = {
            "headline": "QUIET DAY ON THE RELEASE RADAR",
            "deck": "No qualifying releases today",
            "body": "None of today's tracked repos shipped a release. Back tomorrow.",
            "source": "",
            "url": "",
        }

    # Sections claim stories in priority order and remove what they take, so a
    # story that qualifies for several (an AI repo that is also a Show HN and
    # also trending) is printed exactly once, in its most specific section.
    hn_pool = fetch_hn_briefs()
    claimed = set()

    def take(candidates, limit):
        picked = []
        for item in candidates:
            # keyed on url, falling back to title: two items with no url would
            # otherwise collide on "" and the second would vanish silently
            key = item["url"] or item["title"]
            if key in claimed or len(picked) >= limit:
                continue
            claimed.add(key)
            picked.append(item)
        return picked

    ai = take([b for b in hn_pool if is_ai_story(b["title"])], MAX_AI)

    rising_items = fetch_rising_items()
    launches = take([b for b in hn_pool if is_launch(b["title"])]
                    + [parse_rising_item(i) for i in rising_items], MAX_LAUNCHES)

    snapshot = build_star_snapshot(rising_items)
    deltas = star_deltas(snapshot, prev_stars)
    trending = take([{"kind": "trending", "title": repo,
                      "meta": f"+{gained:,}★", "url": f"https://github.com/{repo}"}
                     for repo, gained, _ in deltas], MAX_TRENDING)

    hn = take(hn_pool, MAX_HN)

    feed = {
        "generated": date.today().isoformat(),
        "edition": edition_number(),
        "lead": lead,
        "sections": {"ai": ai, "trending": trending, "hn": hn, "launches": launches},
        "market": [{"name": repo.split("/")[-1], "gained": gained}
                   for repo, gained, _ in deltas[:MAX_MARKET]],
        "ticker": fetch_eol_ticker(),
        "infra": fetch_infra(),
    }
    return feed, snapshot


def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    previous = read_json(OUT_PATH)
    prev_stars = read_json(STARS_PATH)

    feed, snapshot = build_feed(previous, prev_stars)

    # The snapshot is written every run even when the feed is unchanged --
    # skipping it would break the delta chain that trending and market need.
    with open(STARS_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True)

    if previous and feed_hash(previous) == feed_hash(feed):
        print("feed unchanged, skipping write")
        return

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2)
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    main()
