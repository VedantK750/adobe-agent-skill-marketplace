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
from classify import classify_page, classify_site  # noqa: E402

USER_AGENT = ("brand-ai-readiness-audit/1.0 (read-only site audit; "
              "respects robots.txt)")

# User agents whose exclusion is a discoverability problem in its own right.
AI_AGENTS = ["GPTBot", "ClaudeBot", "Claude-Web", "PerplexityBot", "CCBot",
             "Google-Extended", "Applebot-Extended", "Bytespider", "Amazonbot"]

DEFAULT_MAX_PAGES = 40
DEFAULT_DELAY = 0.4
DEFAULT_TIMEOUT = 12
WALL_CLOCK_BUDGET = 180  # seconds; crawling stops and we report what we have

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


def fetch(sess, url, timeout=DEFAULT_TIMEOUT):
    """GET a URL. Returns a dict; never raises."""
    started = time.time()
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
        return {
            "url": url, "final_url": url, "status": None, "redirect_chain": [],
            "content_type": "", "headers": {}, "raw_html": "", "bytes": 0,
            "elapsed_ms": int((time.time() - started) * 1000),
            "error": "%s: %s" % (type(exc).__name__, exc),
        }


# ---------------------------------------------------------------- robots

def read_robots(sess, base):
    url = up.urljoin(base, "/robots.txt")
    res = fetch(sess, url)
    info = {
        "url": url,
        "present": res["status"] == 200,
        "status": res["status"],
        "body": "",
        "ai_agents_blocked": [],
        "blanket_disallow": False,
        "sitemaps": [],
        "parse_error": None,
    }
    if res["status"] != 200:
        return info, None

    body = res["raw_html"]
    if not body:
        try:
            r = sess.get(url, timeout=DEFAULT_TIMEOUT)
            body = r.text
        except Exception:
            body = ""
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

def read_sitemaps(sess, base, robots_info, limit=500):
    candidates = list(robots_info.get("sitemaps") or [])
    if not candidates:
        candidates = [up.urljoin(base, "/sitemap.xml")]

    urls, entries, seen_maps, errors = [], {}, set(), []
    queue = list(candidates)

    while queue and len(urls) < limit and len(seen_maps) < 10:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        res = fetch(sess, sm)
        if res["status"] != 200:
            errors.append("%s -> %s" % (sm, res["status"] or res["error"]))
            continue
        body = res["raw_html"]
        if not body:
            try:
                body = sess.get(sm, timeout=DEFAULT_TIMEOUT).text
            except Exception:
                continue
        if "<sitemapindex" in body.lower():
            queue.extend(re.findall(r"(?is)<loc>\s*(.*?)\s*</loc>", body)[:10])
            continue
        for block in re.findall(r"(?is)<url>(.*?)</url>", body):
            loc = re.search(r"(?is)<loc>\s*(.*?)\s*</loc>", block)
            if not loc:
                continue
            u = loc.group(1).strip()
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

def same_site(a, b):
    ha = up.urlparse(a).netloc.lower().lstrip("www.")
    hb = up.urlparse(b).netloc.lower().lstrip("www.")
    return ha == hb


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


# ---------------------------------------------------------------- rendering

def try_render(urls, timeout_ms=8000):
    """Render pages with Playwright if it is installed. Absence is fine.

    Returning None means render-dependent checks report `inconclusive`
    rather than guessing, which is the honest outcome.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
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
        return None
    return out


# ---------------------------------------------------------------- page meta

def page_meta(html, url):
    s = A.soup(html)

    def meta(name=None, prop=None):
        if name:
            t = s.find("meta", attrs={"name": re.compile("^%s$" % name, re.I)})
        else:
            t = s.find("meta", attrs={"property": re.compile("^%s$" % prop, re.I)})
        return (t.get("content") or "").strip() if t else None

    canonical = s.find("link", attrs={"rel": re.compile("^canonical$", re.I)})
    h1s = [A.normalise_ws(h.get_text(" ")) for h in s.find_all("h1")]
    headings = []
    for h in s.find_all(["h1", "h2", "h3", "h4"]):
        headings.append({
            "level": int(h.name[1]),
            "text": A.normalise_ws(h.get_text(" "))[:300],
            "id": h.get("id"),
        })

    imgs = []
    for img in s.find_all("img"):
        imgs.append({
            "src": up.urljoin(url, img.get("src") or ""),
            "alt": (img.get("alt") if img.get("alt") is not None else None),
            "width": img.get("width"),
            "height": img.get("height"),
        })

    jsonld = []
    for tag in s.find_all("script", attrs={"type": re.compile(
            "application/ld\\+json", re.I)}):
        jsonld.append((tag.string or tag.get_text() or "")[:20000])

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
        "has_nav": bool(s.find("nav")),
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

    # Seed order: home first, then sitemap URLs, then link discovery.
    queue, seen = [], set()
    for u in [base] + [normalise(u) for u in sitemap_info["urls"]]:
        if u not in seen and same_site(u, base):
            seen.add(u)
            queue.append(u)

    pages, blocked = [], []
    while queue and len(pages) < max_pages:
        if time.time() - started > WALL_CLOCK_BUDGET:
            sys.stderr.write("[crawl] wall-clock budget reached; stopping early\n")
            break
        url = queue.pop(0)
        if not allowed(rp, url):
            blocked.append(url)
            continue

        res = fetch(sess, url)
        time.sleep(delay)

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
        if res["raw_html"]:
            page.update(page_meta(res["raw_html"], res["final_url"]))
            discovered = links_from(res["raw_html"], res["final_url"])
            internal = [u for u in discovered if same_site(u, base)]
            page["internal_links"] = len(set(internal))
            page["outbound_links"] = sorted(
                {u for u in discovered if not same_site(u, base)})[:40]
            for u in internal:
                if u not in seen and len(seen) < max_pages * 4:
                    seen.add(u)
                    queue.append(u)
        page["page_type"] = classify_page(page)
        pages.append(page)

    render_map = try_render([p["final_url"] for p in pages[:12]]) if render else None
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
