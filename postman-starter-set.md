# Starter set — Postman testing guide

Five sources, one token, ~25 requests/day. Test every one of these in Postman and
confirm the assertions pass **before** writing a line of `fetch.py`.

| # | Source | Fills | Auth |
|---|---|---|---|
| 1 | GitHub Releases | lead story + ticker | token |
| 2 | HN Algolia | sidebar briefs | none |
| 3 | GitHub Search | rising repos | token |
| 4 | endoflife.date | ticker / briefs | none |
| 5 | Statuspage summaries | outages box | none |

**Verification status.** HN Algolia and `releases.atom` were confirmed live. GitHub REST
could not be verified from my sandbox — the shared IP had exhausted the unauthenticated
60/hr quota, which is exactly why request #0 below exists. endoflife.date and Statuspage
are documented, not hit. Run all of them yourself.

---

## 0. Postman setup

### Environment: `daily-feed`

| Variable | Initial value | Type |
|---|---|---|
| `gh_token` | `ghp_...` | **secret** |
| `gh_api` | `https://api.github.com` | default |
| `hn_api` | `https://hn.algolia.com/api/v1` | default |
| `eol_api` | `https://endoflife.date/api` | default |
| `since_iso` | *(set by script)* | default |
| `since_unix` | *(set by script)* | default |

### Getting a token

Settings → Developer settings → Personal access tokens → **Fine-grained**, repository
access "Public repositories (read-only)". No extra permissions needed — everything here is
public data. A token with zero scopes still lifts you from 60/hr to 5,000/hr, which is the
entire point.

In Postman: Collection → Authorization → **Bearer Token** → `{{gh_token}}`. Set it at the
collection level so all GitHub requests inherit it.

### Collection pre-request script

Paste into Collection → Scripts → Pre-request. Computes the date windows every request needs:

```javascript
const now = Date.now();
pm.environment.set("since_unix", Math.floor((now - 86400000) / 1000));      // 24h ago
pm.environment.set("since_iso",  new Date(now - 7*86400000)
                                   .toISOString().slice(0,10));             // 7d ago
```

---

## Request 0 — Rate limit check (do this first)

Confirms your token works before anything else fails confusingly.

```
GET {{gh_api}}/rate_limit
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
```

**Tests tab:**

```javascript
pm.test("200", () => pm.response.to.have.status(200));
const core = pm.response.json().resources.core;
pm.test("token is authenticating", () => pm.expect(core.limit).to.eql(5000));
console.log(`core: ${core.remaining}/${core.limit}`);
```

If `limit` comes back as **60**, your token isn't being sent. Fix that before continuing —
every other GitHub request will fail intermittently and look like a different bug.

---

## Request 1 — Latest release (lead story)

```
GET {{gh_api}}/repos/oven-sh/bun/releases/latest
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
```

**Fields you want:** `tag_name`, `name`, `published_at`, `html_url`, `body`,
`author.login`, `author.avatar_url`, `prerelease`, `draft`.

**Tests:**

```javascript
pm.test("200", () => pm.response.to.have.status(200));
const r = pm.response.json();
pm.test("has tag", () => pm.expect(r.tag_name).to.be.a("string"));
pm.test("not a prerelease", () => pm.expect(r.prerelease).to.be.false);
pm.test("has body for the lead", () => pm.expect((r.body||"").length).to.be.above(40));
console.log(r.tag_name, "|", r.published_at, "| body:", (r.body||"").length, "chars");
```

**Gotchas**

- `/releases/latest` **excludes prereleases and drafts**. That's usually what you want, but
  fast-moving repos may show a stale "latest" if they're mid-beta.
- Some repos have zero releases → **404**. Handle it; don't let one repo kill the run.
- `body` is Markdown and often huge — thousands of characters of changelog. You need the
  first paragraph, so split on `\n\n`, strip Markdown, and truncate.
- `body` can be empty or null even on a real release.

**Keyless fallback** — `https://github.com/oven-sh/bun/releases.atom` returns 200 with no
auth and no API quota. But it lists **tags, not just releases** — the live feed contained
entries like `consolidation-step-7-green`, which is an internal tag, not a shipped version.
Filter to entries whose title matches a version pattern (`^v?\d+\.\d+`).

**Curl:**

```bash
curl -s -H "Authorization: Bearer $GH_TOKEN" \
     -H "X-GitHub-Api-Version: 2022-11-28" \
     "https://api.github.com/repos/oven-sh/bun/releases/latest" | jq '{tag_name, published_at}'
```

---

## Request 2 — Hacker News (briefs)

**Do not use `tags=front_page` for "today."** It isn't date-scoped — it returns stories
that have *ever* been on the front page, ranked by relevance. Filter by timestamp instead:

```
GET {{hn_api}}/search
```

**Params:**

| Key | Value |
|---|---|
| `tags` | `story` |
| `numericFilters` | `created_at_i>{{since_unix}},points>150` |
| `hitsPerPage` | `20` |
| `attributesToRetrieve` | `title,url,points,num_comments,author,created_at,objectID` |

**Tests:**

```javascript
pm.test("200", () => pm.response.to.have.status(200));
const d = pm.response.json();
pm.test("has hits", () => pm.expect(d.hits.length).to.be.above(0));
pm.test("all above threshold", () =>
  d.hits.forEach(h => pm.expect(h.points).to.be.above(150)));
pm.test("all within 24h", () => {
  const cut = Number(pm.environment.get("since_unix"));
  d.hits.forEach(h => pm.expect(h.created_at_i).to.be.above(cut));
});
console.log(d.hits.map(h => `${h.points}  ${h.title}`).join("\n"));
```

**Gotchas**

- `attributesToRetrieve` is not optional in practice. Without it every hit carries
  `_highlightResult` plus a `children` array of **every comment ID** — I saw single stories
  with 250+ IDs. The payload balloons for data you'll never read.
- Rate limit is 10,000/hr, no key. You will never come close.
- `url` is **null** for Ask HN / Tell HN self-posts. Fall back to
  `https://news.ycombinator.com/item?id={objectID}`.
- `story_text` is HTML-escaped and contains `<p>` tags and `&quot;` entities. Unescape and
  strip before typesetting.
- **A quiet day returns fewer than 3 hits at points>150.** Test this: temporarily set the
  threshold to 800 and confirm your layout degrades gracefully instead of breaking.
- Roughly a third of HN is not developer content. Add a domain allowlist on top of the
  points threshold, or a politics headline lands on your profile.

---

## Request 3 — Rising repos

```
GET {{gh_api}}/search/repositories
```

**Params:**

| Key | Value |
|---|---|
| `q` | `created:>{{since_iso}} stars:>100` |
| `sort` | `stars` |
| `order` | `desc` |
| `per_page` | `5` |

**Tests:**

```javascript
pm.test("200", () => pm.response.to.have.status(200));
const d = pm.response.json();
pm.test("got repos", () => pm.expect(d.items.length).to.be.above(0));
pm.test("descriptions present", () =>
  d.items.forEach(i => pm.expect(i.description).to.not.be.null));
console.log(d.items.map(i => `${i.stargazers_count}★  ${i.full_name}`).join("\n"));
```

**Gotchas**

- **Search has its own rate limit: 30 requests/minute**, separate from the 5,000/hr core
  pool. Fine for daily, painful while iterating — don't hammer it during development.
- `q` needs the space between qualifiers URL-encoded. Postman handles this; `curl` does not.
- `description` is genuinely `null` sometimes. Guard it.
- `created:>` finds *newly created* repos, not "trending" ones. An established project
  gaining 5k stars this week won't appear. That's a real semantic difference from
  github.com/trending — accept it or track star deltas yourself across runs.

---

## Request 4 — endoflife.date

Two API versions exist and the schemas differ. Check which one you're hitting.

```
GET https://endoflife.date/api/nodejs.json          ← legacy
GET https://endoflife.date/api/v1/products/nodejs   ← v1
```

| Legacy field | v1 field |
|---|---|
| `cycle` | `name` |
| `releaseDate` | `date` |
| `latest` (string) | `latest.name` (object with `name`, `date`, `link`) |
| `releases` | `cycles` |

**Tests (legacy):**

```javascript
pm.test("200", () => pm.response.to.have.status(200));
const cycles = pm.response.json();
pm.test("is an array", () => pm.expect(cycles).to.be.an("array"));
const soon = cycles.filter(c => typeof c.eol === "string"
  && new Date(c.eol) > new Date()
  && new Date(c.eol) < new Date(Date.now() + 90*86400000));
console.log("EOL within 90 days:", soon.map(c => `${c.cycle} → ${c.eol}`));
```

**Gotchas**

- **`eol` is a union type** — either a date string (`"2026-04-30"`) or a boolean. `false`
  means ongoing support; `true` means EOL with no known date. Same for `lts`, `support`,
  and `extendedSupport`. A naive `new Date(c.eol)` on a boolean gives you garbage.
- No auth, free, ~462 products tracked.
- **Data is CC-BY-SA.** You're publishing it, so attribute it — a small "lifecycle data:
  endoflife.date" line in the footer covers you.
- The interesting item is *change*: "Node 20 reaches EOL in 40 days" is a brief; "Node 20
  reaches EOL in 400 days" is noise. Filter to a 90-day window.

---

## Request 5 — Statuspage (outages box)

Statuspage exposes an identical schema across vendors, so one parser handles all of them.

```
GET https://www.githubstatus.com/api/v2/summary.json
```

Also: `status.npmjs.org`, `www.cloudflarestatus.com`, `status.openai.com`,
`status.anthropic.com`, `www.vercelstatus.com`.

**Tests:**

```javascript
pm.test("200", () => pm.response.to.have.status(200));
const d = pm.response.json();
pm.test("has status.indicator", () =>
  pm.expect(d.status.indicator).to.be.oneOf(["none","minor","major","critical"]));
console.log(d.page.name, "→", d.status.description,
            "| incidents:", d.incidents.length);
```

**Gotchas**

- Hostnames are inconsistent — some take `www.`, some don't, some are `status.*`. Verify
  each one individually; a wrong host gives you an HTML 404, not JSON.
- `incidents` is `[]` on a healthy day, and `status.description` reads "All Systems
  Operational." That's your graceful-degradation text, free.
- `components` is a long array you don't need. Read `status` and `incidents` only.
- Rate limits are undocumented. Five vendors once a day is fine; don't poll.

---

## Field mapping → feed.json

| feed.json | Source | Path |
|---|---|---|
| `lead.headline` | Releases | `{repo} + " " + tag_name`, uppercased |
| `lead.deck` | Releases | first sentence of `body`, Markdown stripped |
| `lead.body` | Releases | first paragraph of `body`, truncated |
| `lead.source` | Releases | `full_name` |
| `lead.cut` | Releases | `author.avatar_url` → halftone |
| `briefs[]` | HN | `title` + `points + " pts"` |
| `briefs[]` | Search | `full_name` + `stargazers_count + "★"` |
| `ticker[]` | endoflife | `product + " EOL " + eol` |
| `outages[]` | Statuspage | `page.name` + `status.description` |

---

## Pre-flight checklist

- [ ] Request 0 reports `limit: 5000` — token is being sent
- [ ] Every request returns 200 and its tests pass
- [ ] Request 1 tried against a repo with **no releases** → 404 handled
- [ ] Request 2 tried with `points>800` → thin-day path exercised
- [ ] Request 2 tried against an Ask HN post → `url: null` handled
- [ ] Request 4 checked against a product with `eol: false` → boolean handled
- [ ] Request 5 checked against a healthy page → empty `incidents` handled
- [ ] Search request not fired more than 30×/minute
- [ ] Attribution line drafted for endoflife.date (CC-BY-SA)
- [ ] Longest real title captured and pasted into your test `feed.json`

---

## Then, and only then

Export the collection, save one real response per source as a fixture, and hand-write
`data/feed.json` from those fixtures — including the longest HN title you saw. The
typesetting work in the main spec runs entirely against that file with no network.

The fixtures are the point. When a source changes shape in four months, you'll diff against
them instead of guessing.
