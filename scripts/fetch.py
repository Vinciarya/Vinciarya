
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

MAX_BRIEFS = 5  # sidebar is ~162px wide; an uncapped list can run away on a busy news day

HN_MIN_POINTS = 150
HN_DOMAIN_ALLOWLIST = {
    "github.com", "arxiv.org", "news.ycombinator.com",
    "npmjs.com", "npmjs.org", "python.org", "rust-lang.org",
    "developer.mozilla.org", "web.dev", "chromium.org",
    "kernel.org", "llvm.org", "postgresql.org", "sqlite.org",
}
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
        "1. a one-sentence deck, under 90 characters\n"
        "2. a ~45-word body paragraph in neutral news style"
    )
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 220,
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


def assemble_lead(repo, tag, prose, groq_result):
    """Pure: turn a prose paragraph and/or a Groq result into a lead dict."""
    if groq_result:
        deck, body = groq_result
    elif prose:
        deck = prose.split(". ")[0][:90]
        body = prose[:400]
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
    }


def build_lead(repo):
    raw = fetch_release(repo)
    if raw is None or raw.get("draft") or raw.get("prerelease"):
        return None
    tag = raw["tag_name"]
    prose = first_paragraph(raw.get("body"))
    groq_result = groq_prose(repo, tag, raw.get("body"))
    return assemble_lead(repo, tag, prose, groq_result)


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


def parse_hn_hit(hit, allowlist=HN_DOMAIN_ALLOWLIST):
    """Pure: one HN hit -> a brief dict, or None if it's filtered out."""
    url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
    domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    if allowlist and domain not in allowlist:
        return None
    return {"kind": "hn", "title": hit["title"], "meta": f"{hit['points']} pts"}


def fetch_hn_briefs():
    briefs = [parse_hn_hit(h) for h in fetch_hn_hits()]
    return [b for b in briefs if b]


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
    return {"kind": "rising", "title": item["full_name"], "meta": meta}


def fetch_rising_briefs():
    return [parse_rising_item(i) for i in fetch_rising_items()]


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


# ==== Statuspage (outages) ===================================================

def fetch_statuspage(url):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def parse_statuspage(data, name):
    """Pure: only surfaces a vendor if it actually has an active incident --
    a healthy page returns None, so the outages box stays empty on a normal
    day instead of listing six "All Systems Operational" lines every time.
    """
    if not data.get("incidents"):
        return None
    return {
        "name": name,
        "status": data["status"]["description"],
        "indicator": data["status"]["indicator"],
    }


def fetch_outages():
    outages = []
    for name, url in STATUSPAGES.items():
        try:
            data = fetch_statuspage(url)
        except requests.RequestException:
            continue
        outage = parse_statuspage(data, name)
        if outage:
            outages.append(outage)
    return outages


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


def build_feed(previous=None):
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
        }

    return {
        "generated": date.today().isoformat(),
        "edition": edition_number(),
        "lead": lead,
        "briefs": (fetch_hn_briefs() + fetch_rising_briefs())[:MAX_BRIEFS],
        "ticker": fetch_eol_ticker(),
        "outages": fetch_outages(),
    }


def main():
    previous = None
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            previous = json.load(f)

    feed = build_feed(previous)

    if previous and feed_hash(previous) == feed_hash(feed):
        print("feed unchanged, skipping write")
        return

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2)
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    main()
