#!/usr/bin/env python3
"""Crawl a site read-only and write the shared evidence snapshot.

Guarantees this script makes to the rest of the marketplace:
  * GET only. No POST, no forms, no authenticated areas, no cookies carried
    between hosts, no state-changing requests of any kind.
  * robots.txt is fetched first and obeyed for our own user agent.
  * Every URL is fetched exactly once. Analysis skills reuse this snapshot
    rather than re-crawling, so the target site pays for one pass.
  * Deterministic: URL ordering is stable, so two runs sample the same pages.
"""

import argparse
import html as _html
import json
import os
import re
import sys
import time
import urllib.parse as up
import urllib.robotparser as robotparser
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import auditlib as A  # noqa: E402
from classify import (  # noqa: E402
    classify_page, classify_site, guess_type_from_url)

USER_AGENT = ("brand-ai-readiness-audit/1.0 (read-only site audit; "
              "respects robots.txt)")

# User agents whose exclusion is a discoverability problem in its own right.
AI_AGENTS = ["GPTBot", "ClaudeBot", "Claude-Web", "PerplexityBot", "CCBot",
             "Google-Extended", "Applebot-Extended", "Bytespider", "Amazonbot"]

DEFAULT_MAX_PAGES = 40
DEFAULT_DELAY = 0.4
DEFAULT_TIMEOUT = 12
FETCH_RETRIES = 2       # extra attempts on a transient network error
FETCH_BACKOFF = 0.6     # seconds, multiplied by attempt number
WALL_CLOCK_BUDGET = 180  # seconds; crawling stops and we report what we have
TYPE_QUOTA_SHARE = 0.4   # no single page type may exceed this share of the sample
FETCH_BUDGET_FACTOR = 2.5  # cap total fetches at this multiple of max_pages

SKIP_EXT = re.compile(
    r"\.(jpg|jpeg|png|gif|webp|svg|ico|css|js|zip|gz|mp4|mp3|avi|mov|"
    r"woff2?|ttf|eot|dmg|exe|rss|xml)$", re.I)


# ---------------------------------------------------------------- fetching

def session():
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en",
    })
    return s


def fetch(sess, url, timeout=DEFAULT_TIMEOUT, retries=FETCH_RETRIES):
    """GET a URL. Returns a dict; never raises.

    A transient network error (timeout, dropped connection) is retried a few
    times with a short backoff. This is not a determinism fix — the network is
    inherently non-deterministic — but it stops one flaky request from
    collapsing a whole crawl: a timeout on the seed page leaves nothing to
    discover links from, so the audit would otherwise see a one-page site. HTTP
    error codes (4xx/5xx) are real responses, not exceptions, and are never
    retried; they are reported as-is.
    """
    started = time.time()
    last_exc = None
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, timeout=timeout, allow_redirects=True)
            chain = [h.url for h in r.history] + [r.url]
            ctype = r.headers.get("Content-Type", "")
            is_html = "html" in ctype.lower()
            return {
                "url": url,
                "final_url": r.url,
                "status": r.status_code,
                "redirect_chain": chain if len(chain) > 1 else [],
                "content_type": ctype,
                "headers": {k.lower(): v for k, v in r.headers.items()},
                "raw_html": r.text if is_html else "",
                "bytes": len(r.content or b""),
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": None,
            }
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(FETCH_BACKOFF * (attempt + 1))
    return {
        "url": url, "final_url": url, "status": None, "redirect_chain": [],
        "content_type": "", "headers": {}, "raw_html": "", "bytes": 0,
        "elapsed_ms": int((time.time() - started) * 1000),
        "error": "%s: %s" % (type(last_exc).__name__, last_exc),
    }


# ---------------------------------------------------------------- robots

def read_robots(sess, base):
    url = up.urljoin(base, "/robots.txt")
    body, status = _get_text(sess, url)
    info = {
        "url": url,
        "present": status == 200,
        "status": status,
        "body": "",
        "ai_agents_blocked": [],
        "blanket_disallow": False,
        "sitemaps": [],
        "parse_error": None,
    }
    if status != 200 or not body:
        return info, None

    info["body"] = body[:20000]

    rp = robotparser.RobotFileParser()
    try:
        rp.parse(body.splitlines())
    except Exception as exc:
        info["parse_error"] = str(exc)
        rp = None

    info["sitemaps"] = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", body)

    # Per-agent block detection, done by hand because robotparser will not
    # answer "is this specific agent excluded" cleanly across groups.
    for agent in AI_AGENTS:
        pat = re.compile(
            r"(?is)user-agent:\s*%s\s*(.*?)(?=\nuser-agent:|\Z)"
            % re.escape(agent))
        m = pat.search(body)
        if m and re.search(r"(?im)^\s*disallow:\s*/\s*$", m.group(1)):
            info["ai_agents_blocked"].append(agent)

    m = re.search(r"(?is)user-agent:\s*\*\s*(.*?)(?=\nuser-agent:|\Z)", body)
    if m and re.search(r"(?im)^\s*disallow:\s*/\s*$", m.group(1)):
        info["blanket_disallow"] = True

    return info, rp


def allowed(rp, url):
    if rp is None:
        return True
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


# ---------------------------------------------------------------- sitemap

# We only need a few hundred URLs to seed a diversified, capped crawl. Reading
# a large site's entire sitemap tree can take longer than the crawl itself
# (gov-scale sitemaps run to many multi-MB partitions), so sitemap reading is
# bounded three ways: total URLs gathered, sitemap files fetched, and a
# wall-clock sub-budget. We stop at whichever comes first and crawl with what
# we have — the diversifier then spreads the sample across sections.
SITEMAP_URL_LIMIT = 400
SITEMAP_FILE_LIMIT = 6
SITEMAP_TIME_BUDGET = 30  # seconds


def _get_text(sess, url, retries=FETCH_RETRIES):
    """Fetch a text/XML resource (robots, sitemap). Returns ("", reason) on
    failure. Transient errors are retried so a flaky robots/sitemap fetch does
    not needlessly strip the crawl of its seed URLs.

    Gzipped sitemaps (`sitemap.xml.gz`) are part of the sitemap protocol and are
    common on large sites — Airbnb publishes only
    `sitemap-master-index.xml.gz`. Without decompressing, the body is binary,
    zero <loc> entries parse, and the site looks as though its sitemap is
    unreadable. Decompress when the URL or the payload says gzip.
    """
    last = "error"
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                return "", r.status_code
            body = r.content or b""
            is_gz = (url.lower().endswith(".gz")
                     or body[:2] == b"\x1f\x8b"
                     or "gzip" in r.headers.get("Content-Type", "").lower())
            if is_gz and body[:2] == b"\x1f\x8b":
                import gzip
                try:
                    return gzip.decompress(body).decode("utf-8", "replace"), 200
                except Exception:
                    return r.text, 200
            return r.text, 200
        except Exception as exc:
            last = "%s" % type(exc).__name__
            if attempt < retries:
                time.sleep(FETCH_BACKOFF * (attempt + 1))
    return "", last


def read_sitemaps(sess, base, robots_info, limit=SITEMAP_URL_LIMIT):
    candidates = list(robots_info.get("sitemaps") or [])
    if not candidates:
        candidates = [up.urljoin(base, "/sitemap.xml")]

    started = time.time()
    urls, entries, seen_maps, errors = [], {}, set(), []
    queue = list(candidates)
    fetched_ok = 0          # only SUCCESSFUL fetches consume the file budget

    while queue and len(urls) < limit and fetched_ok < SITEMAP_FILE_LIMIT:
        if time.time() - started > SITEMAP_TIME_BUDGET:
            errors.append("sitemap time budget reached; using %d URLs so far"
                          % len(urls))
            break
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        body, status = _get_text(sess, sm)
        if not body:
            # A 404 candidate (robots often lists stale sitemap paths) must not
            # burn the budget: blog.mozilla.org declares 19 sitemaps of which
            # most 404, and counting those exhausted the limit before any real
            # index was expanded, so the site read as having no sitemap at all.
            errors.append("%s -> %s" % (sm, status))
            continue
        fetched_ok += 1
        if "<sitemapindex" in body.lower():
            # Only take as many child partitions as remain in the file budget.
            # <loc> values are XML-entity-encoded: a child sitemap URL with a
            # query string appears as ...?a=1&amp;b=2. It must be unescaped
            # before it is fetched, or the request carries a literal "&amp;",
            # 404s, and the whole sitemap reads as empty — which fired a false
            # ACC-NO-SITEMAP on sites (ProPublica) whose sitemap index is
            # perfectly valid. `html.unescape` turns &amp; back into &.
            # Expand children FIRST (prepend), so a valid index is followed
            # into real <url> entries instead of queueing behind a long list of
            # sibling candidates that may all 404.
            room = max(0, SITEMAP_FILE_LIMIT - fetched_ok)
            children = [_html.unescape(x.strip())
                        for x in re.findall(r"(?is)<loc>\s*(.*?)\s*</loc>", body)]
            queue[:0] = children[:room]
            continue
        for block in re.findall(r"(?is)<url>(.*?)</url>", body):
            loc = re.search(r"(?is)<loc>\s*(.*?)\s*</loc>", block)
            if not loc:
                continue
            u = _html.unescape(loc.group(1).strip())
            lastmod = re.search(r"(?is)<lastmod>\s*(.*?)\s*</lastmod>", block)
            urls.append(u)
            entries[u] = lastmod.group(1).strip() if lastmod else None
            if len(urls) >= limit:
                break

    return {
        "found": bool(urls) or bool(seen_maps and not errors),
        "checked": sorted(seen_maps),
        "errors": errors,
        "url_count": len(urls),
        "urls": urls,
        "lastmod": entries,
    }


# ---------------------------------------------------------------- discovery

def _registrable(host):
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def same_site(a, b):
    return _registrable(up.urlparse(a).netloc) == _registrable(up.urlparse(b).netloc)


def normalise(url):
    p = up.urlparse(url)
    p = p._replace(fragment="")
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    q = up.parse_qsl(p.query)
    q = [(k, v) for k, v in q
         if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return up.urlunparse(p._replace(path=path or "/", query=up.urlencode(q)))


def links_from(html, base_url):
    out = []
    for m in re.finditer(r'(?is)<a\b[^>]*href\s*=\s*["\']([^"\']+)["\']', html or ""):
        href = m.group(1).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = up.urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        if SKIP_EXT.search(up.urlparse(absolute).path):
            continue
        out.append(normalise(absolute))
    return out


def _section_key(url):
    """First path segment, used as a coarse section label for diversification."""
    parts = [p for p in up.urlparse(url).path.split("/") if p]
    # A leading two-letter locale segment (/in, /en-gb) is not a section; look
    # past it so locale-prefixed sites still diversify by real section.
    if parts and re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", parts[0]):
        parts = parts[1:]
    return parts[0].lower() if parts else "(root)"


def diversify(urls):
    """Reorder URLs so sections are interleaved rather than clustered.

    A sitemap is often grouped by section, so the first N entries can all be
    from one area (a partition that is entirely /legal/, say). Round-robining
    across first-path-segment buckets, shortest paths first within each, keeps
    an early, capped crawl representative of the whole site instead of one
    corner of it. Order is deterministic: buckets are visited in first-seen
    order and entries keep their relative order within a bucket.
    """
    buckets = {}
    for u in urls:
        buckets.setdefault(_section_key(u), []).append(u)
    for key in buckets:
        buckets[key].sort(key=lambda u: (len(up.urlparse(u).path), u))
    order = list(buckets.keys())
    out = []
    i = 0
    while any(buckets[k] for k in order):
        k = order[i % len(order)]
        if buckets[k]:
            out.append(buckets[k].pop(0))
        i += 1
    return out


# ---------------------------------------------------------------- rendering

def try_render(urls, timeout_ms=8000):
    """Render pages with Playwright if it is installed. Absence is fine.

    Returns (render_map, status) where status is one of:
      "rendered"       - a browser ran and produced DOM for at least some pages
      "browser-absent" - Playwright is not installed on this machine
      "launch-failed"  - Playwright is installed but the browser would not start

    The distinction matters downstream: a render-dependent check must be able to
    tell an evaluator *why* it could not compare raw against rendered HTML, and
    "no browser installed" is a different, honest story from "the auditor chose
    not to render". A None render_map means render-dependent checks report
    `inconclusive` rather than guessing.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None, "browser-absent"
    out = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(user_agent=USER_AGENT)
            for u in urls:
                try:
                    page.goto(u, timeout=timeout_ms, wait_until="networkidle")
                    out[u] = page.content()
                except Exception:
                    continue
            browser.close()
    except Exception:
        return None, "launch-failed"
    return out, "rendered"


# ---------------------------------------------------------------- page meta

# Trailing permalink glyphs that section generators (Sphinx, MkDocs, many CMSs)
# append inside the heading. They are not part of the heading text.
_PERMALINK_CHARS = "¶§#"


def heading_text(h):
    """Heading text with the trailing permalink glyph stripped."""
    txt = A.normalise_ws(h.get_text(" "))
    return txt.rstrip(" " + _PERMALINK_CHARS).strip()


def heading_anchor(h):
    """The stable anchor a citation could deep-link to, or None.

    A heading is deep-linkable when any of these is true, and real sites use
    all three: the heading carries its own id; it contains a permalink anchor
    (`<a class="headerlink" href="#...">`), the near-universal Sphinx/MkDocs
    pattern; or it sits inside a section/div/article that carries the id. Only
    checking the heading's own id reports false 'no anchor' findings on the
    entire documentation ecosystem, which is exactly where anchors matter most.
    """
    if h.get("id"):
        return h.get("id")
    for a in h.find_all("a", href=True):
        href = a.get("href") or ""
        if href.startswith("#") and len(href) > 1:
            return href[1:]
        if a.get("id"):
            return a.get("id")
    parent = h.parent
    depth = 0
    while parent is not None and depth < 3:
        name = getattr(parent, "name", None)
        if name in ("section", "article", "div") and parent.get("id"):
            return parent.get("id")
        parent = parent.parent
        depth += 1
    return None


# A soft-404 is a page that returns HTTP 200 but is really an error page. Its
# markup carries no content worth auditing, and crucially it often carries
# noindex/nofollow (correctly) — so counting it as a content page produced a
# false ACC-SNIPPET-SUPPRESSED finding on sites (MDN among them) whose 404
# route answers 200. Detected from the URL shape and the page's own title/h1,
# both site-neutral signals.
_SOFT404_URL = re.compile(r"/(404|not[-_]?found|error)(/|\.|$)", re.I)
_SOFT404_TITLE = re.compile(
    r"\b(404|page not found|not found|page does(?:n['’]?t| not) exist|"
    r"no longer exists)\b", re.I)


def is_soft_404(page):
    """True if a 200 response is really an error page."""
    if _SOFT404_URL.search(up.urlparse(page.get("final_url") or "").path):
        return True
    title = (page.get("title") or "")
    h1s = " ".join(page.get("h1") or [])
    # Require the signal in the title or H1 (structural), not merely in body
    # copy, so an article legitimately discussing "404 errors" is not caught.
    return bool(_SOFT404_TITLE.search(title) or _SOFT404_TITLE.search(h1s))


def page_meta(html, url):
    s = A.soup(html)

    def meta(name=None, prop=None):
        if name:
            t = s.find("meta", attrs={"name": re.compile("^%s$" % name, re.I)})
        else:
            t = s.find("meta", attrs={"property": re.compile("^%s$" % prop, re.I)})
        return (t.get("content") or "").strip() if t else None

    canonical = s.find("link", attrs={"rel": re.compile("^canonical$", re.I)})
    h1s = [heading_text(h) for h in s.find_all("h1")]
    headings = []
    for h in s.find_all(["h1", "h2", "h3", "h4"]):
        headings.append({
            "level": int(h.name[1]),
            "text": heading_text(h)[:300],
            "id": heading_anchor(h),
        })

    imgs = []
    for img in s.find_all("img"):
        imgs.append({
            "src": up.urljoin(url, img.get("src") or ""),
            "alt": (img.get("alt") if img.get("alt") is not None else None),
            "width": img.get("width"),
            "height": img.get("height"),
        })

    # Capture JSON-LD whole. Content sites legitimately ship large FAQPage,
    # Article or ItemList blocks well over 20 KB; truncating one mid-string
    # turns valid markup into a parse error and produces a false
    # SD-INVALID-JSON finding. The 400 KB raw-HTML cap already bounds this.
    jsonld = []
    for tag in s.find_all("script", attrs={"type": re.compile(
            "application/ld\\+json", re.I)}):
        block = (tag.string or tag.get_text() or "")
        jsonld.append(block[:200000])

    return {
        "title": A.normalise_ws(s.title.get_text()) if s.title else None,
        "meta_description": meta(name="description"),
        "meta_robots": meta(name="robots"),
        "viewport": meta(name="viewport"),
        "og_title": meta(prop="og:title"),
        "canonical": up.urljoin(url, canonical.get("href")) if canonical and canonical.get("href") else None,
        "h1": h1s,
        "headings": headings,
        "images": imgs[:120],
        "jsonld_raw": jsonld,
        "has_microdata": bool(s.find(attrs={"itemscope": True})),
        "iframes": [up.urljoin(url, f.get("src") or "") for f in s.find_all("iframe")][:20],
        "scripts": len(s.find_all("script")),
        "stylesheets": len(s.find_all("link", attrs={"rel": re.compile("stylesheet", re.I)})),
        "forms": len(s.find_all("form")),
        "has_main": bool(s.find("main") or s.find(attrs={"role": "main"})),
        "has_nav": bool(s.find("nav") or s.find(attrs={"role": "navigation"})),
        # Computed here, on the FULL document, because `raw_html` is truncated
        # before it reaches the snapshot. Large commerce pages routinely carry
        # megabytes of inlined JSON state ahead of the header markup, so a
        # search box can sit well past the truncation point; scanning the
        # stored HTML downstream would then report "no on-site search" on a
        # site that plainly has one.
        "has_search": bool(
            s.find("input", attrs={"type": re.compile(r"^search$", re.I)})
            or s.find(attrs={"role": re.compile(r"^search$", re.I)})
            or s.find("input", attrs={"name": re.compile(r"^q$", re.I)})
            or s.find(attrs={"placeholder": re.compile("search", re.I)})),
        # Same reason as has_search: decided on the full document, not the
        # truncated copy stored in the snapshot.
        "has_autoplay": bool(
            s.find(["video", "audio"], attrs={"autoplay": True})),
        "has_breadcrumb": bool(
            s.find(attrs={"class": re.compile("breadcrumb", re.I)})
            or s.find(attrs={"aria-label": re.compile("breadcrumb", re.I)})
            or s.find(attrs={"itemtype": re.compile("BreadcrumbList", re.I)})
            or any("breadcrumblist" in (raw or "").lower() for raw in jsonld)),
        "internal_links": 0,   # filled after crawl
        "outbound_links": [],  # filled below
        "text": A.visible_text(html),
        "body_text": A.main_text(html),
    }


# ---------------------------------------------------------------- main

def crawl(start_url, workdir, max_pages, delay, render):
    started = time.time()
    if not start_url.startswith(("http://", "https://")):
        start_url = "https://" + start_url
    base = normalise(start_url)
    sess = session()

    robots_info, rp = read_robots(sess, base)
    sitemap_info = read_sitemaps(sess, base, robots_info)

    # Seed order: home first, then a *diversified* pass over sitemap URLs.
    # Sitemaps are frequently clustered by section (e.g. a partition that is
    # entirely /legal/), and a strict FIFO drains the whole crawl budget into
    # that one section. Interleaving by first path segment keeps the sample
    # spread across the site so no single template dominates it.
    sitemap_seed = diversify([normalise(u) for u in sitemap_info["urls"]
                              if same_site(u, base)])
    queue, seen, seen_finals = [], set(), set()
    for u in [base] + sitemap_seed:
        if u not in seen and same_site(u, base):
            seen.add(u)
            queue.append(u)

    # Per-type quota so one template cannot dominate the sample. Home is never
    # capped; everything else is held to a share of the budget. Discovery
    # continues past the cap, but capped-type pages are no longer *kept*.
    default_cap = max(6, int(max_pages * TYPE_QUOTA_SHARE))
    # Low-value page types earn a much smaller slice of the sample. Legal
    # boilerplate and unclassifiable pages are rarely what an audit is about,
    # and on some sites (a partitioned legal sitemap, say) they would otherwise
    # crowd out the product, article and documentation pages that carry the
    # findings that matter. Capping them low keeps the sample useful.
    LOW_VALUE_CAP = max(4, int(max_pages * 0.2))
    # Only legal boilerplate is reliably low value. `other` is not — it is
    # merely "not confidently typed", and on many sites (a blog with bare-slug
    # permalinks, say) it is the actual content. Capping `other` low starved
    # those sites of a representative sample, so it keeps the normal cap.
    LOW_VALUE_TYPES = {"legal"}

    def cap_for(ptype):
        return LOW_VALUE_CAP if ptype in LOW_VALUE_TYPES else default_cap

    type_kept = {}

    # Fetches are bounded independently of kept pages. Because the quota drops
    # over-represented pages without keeping them, a section-heavy site could
    # otherwise fetch far past max_pages chasing a rarer type. This cap keeps
    # total network cost and runtime predictable regardless of site shape.
    fetch_budget = int(max_pages * FETCH_BUDGET_FACTOR)

    pages, blocked, skipped_quota, fetches = [], [], 0, 0
    while queue and len(pages) < max_pages and fetches < fetch_budget:
        if time.time() - started > WALL_CLOCK_BUDGET:
            sys.stderr.write("[crawl] wall-clock budget reached; stopping early\n")
            break
        url = queue.pop(0)
        if not allowed(rp, url):
            blocked.append(url)
            continue

        # Steer the frontier away from saturated sections *before* fetching.
        # If the URL alone identifies a type (e.g. /legal/) that has already
        # hit its quota, skip it now rather than spending a request only to
        # drop the result. This is what keeps a legal-heavy sitemap from
        # burning the whole time budget. Unknown-from-URL pages always pass.
        guessed = guess_type_from_url(url, base)
        if guessed and guessed != "home" \
                and type_kept.get(guessed, 0) >= cap_for(guessed):
            skipped_quota += 1
            continue

        res = fetch(sess, url)
        fetches += 1
        time.sleep(delay)

        # Dedupe on the *final* URL: many request URLs redirect to one target
        # (locale variants, slug aliases). Fetching each is polite waste and,
        # worse, counts the same page several times, corrupting every
        # prevalence ratio downstream.
        final = normalise(res["final_url"]) if res["final_url"] else url
        if res["status"] == 200 and final in seen_finals:
            continue
        seen_finals.add(final)

        page = {
            "url": url,
            "final_url": res["final_url"],
            "status": res["status"],
            "error": res["error"],
            "redirect_chain": res["redirect_chain"],
            "content_type": res["content_type"],
            "bytes": res["bytes"],
            "elapsed_ms": res["elapsed_ms"],
            "headers": {k: v for k, v in res["headers"].items()
                        if k in ("x-robots-tag", "content-type", "cache-control",
                                 "last-modified", "content-encoding", "server")},
            "raw_html": res["raw_html"][:400000],
        }
        discovered_internal = []
        if res["raw_html"]:
            page.update(page_meta(res["raw_html"], res["final_url"]))
            discovered = links_from(res["raw_html"], res["final_url"])
            discovered_internal = [u for u in discovered if same_site(u, base)]
            page["internal_links"] = len(set(discovered_internal))
            page["outbound_links"] = sorted(
                {u for u in discovered if not same_site(u, base)})[:40]
        page["soft_404"] = bool(res["raw_html"]) and is_soft_404(page)
        page["page_type"] = classify_page(page, base)

        # A 200 response that is not HTML (a plain-text CHANGES file, a PDF, an
        # XML feed) is neither a document to audit nor an error to report. Do
        # not keep it as a "page": counting it inflated pages_crawled and made
        # the header count disagree with the per-check sample (a site with six
        # CHANGES text files read as nine pages while only three were HTML). It
        # has already contributed any links it carried. Non-200s ARE kept —
        # the accessibility checks need their status codes and redirect chains.
        if res["status"] == 200 and not res["raw_html"]:
            continue

        # Apply the quota. A page over its type cap is dropped from the sample
        # but still contributes its links, so discovery is not starved. The
        # post-fetch check catches pages whose type the URL did not reveal.
        ptype = page["page_type"]
        if ptype != "home" and type_kept.get(ptype, 0) >= cap_for(ptype):
            skipped_quota += 1
        else:
            type_kept[ptype] = type_kept.get(ptype, 0) + 1
            pages.append(page)

        for u in discovered_internal:
            if u not in seen and len(seen) < max_pages * 8:
                seen.add(u)
                queue.append(u)

    if skipped_quota:
        sys.stderr.write(
            "[crawl] %d pages skipped by per-type quota (caps: default %d, "
            "low-value %d)\n" % (skipped_quota, default_cap, LOW_VALUE_CAP))

    if render:
        render_map, render_status = try_render([p["final_url"] for p in pages[:12]])
    else:
        # The auditor opted out with --no-render. This is not the same as a
        # machine that has no browser: say so explicitly so downstream checks
        # do not claim a capability was missing when it was merely declined.
        render_map, render_status = None, "disabled-by-flag"
    if render_map is not None:
        for p in pages:
            if p["final_url"] in render_map:
                html = render_map[p["final_url"]]
                p["rendered_html"] = html[:400000]
                p["rendered_text"] = A.visible_text(html)

    site_type = classify_site(pages)

    snapshot = {
        "site": up.urlparse(base).netloc,
        "base_url": base,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "site_type": site_type,
        "render_mode": "headless" if render_map is not None else "static-only",
        "render_status": render_status,
        "robots": robots_info,
        "robots_respected": True,
        "blocked_by_robots": blocked,
        "sitemap": {k: v for k, v in sitemap_info.items() if k != "urls"},
        "sitemap_urls": sitemap_info["urls"][:200],
        "pages": pages,
        "crawl": {
            "max_pages": max_pages,
            "delay_seconds": delay,
            "pages_crawled": len(pages),
            "pages_fetched": fetches,
            "pages_skipped_quota": skipped_quota,
            "type_cap": default_cap,
            "low_value_cap": LOW_VALUE_CAP,
            "runtime_seconds": round(time.time() - started, 1),
            "user_agent": USER_AGENT,
        },
    }
    A.save_snapshot(workdir, snapshot)
    sys.stderr.write(
        "[crawl] %s | %d pages | site_type=%s | render=%s | %.1fs\n"
        % (snapshot["site"], len(pages), site_type,
           snapshot["render_mode"], snapshot["crawl"]["runtime_seconds"]))
    return snapshot


def main():
    ap = argparse.ArgumentParser(description="Read-only site crawler.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    ap.add_argument("--no-render", action="store_true",
                    help="Skip headless rendering even if Playwright exists.")
    args = ap.parse_args()
    crawl(args.url, args.workdir, args.max_pages, args.delay,
          render=not args.no_render)


if __name__ == "__main__":
    main()
