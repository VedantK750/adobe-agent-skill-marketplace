#!/usr/bin/env python3
"""Fixture tests for the brand-ai-readiness-audit marketplace.

Two synthetic sites are served locally and audited end to end:

  badsite   - deliberately breaks a specific check in each way the marketplace
              is meant to catch (AI crawler blocked, JS shell, duplicate H1s,
              dangling chunks, image-locked facts, stale copyright, ...).
  goodsite  - a clean local business that should trip almost nothing.

For each check we assert BOTH directions: it fires on the broken site and it
stays silent (records not_applicable / passes) on the clean one. As the plan
says, the negative assertions matter more than the positive ones — a check
that fires on everything is worse than useless. The audit is run over a real
HTTP server rather than the file system so robots.txt, redirects, status codes
and the crawler's own logic are all exercised exactly as in production.

Run:  python3 tests/run_tests.py
Exit code is non-zero if any assertion fails.
"""

import functools
import http.server
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The shared library the skills use, so unit assertions can test its helpers
# directly rather than only through a full pipeline run.
sys.path.insert(0, os.path.join(ROOT, "lib"))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
RUN_AUDIT = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts",
                         "run_audit.py")
WORK = os.path.join(ROOT, "tests", ".work")

BAD_PORT = 8899
GOOD_PORT = 8898  # goodsite fixtures reference 127.0.0.1:8898 in canonicals
CONFLICT_PORT = 8897  # conflictsite fixtures reference 127.0.0.1:8897


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # keep test output clean
        pass


def serve(directory, port):
    handler = functools.partial(QuietHandler, directory=directory)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def audit(url, workdir):
    if os.path.exists(workdir):
        import shutil
        shutil.rmtree(workdir)
    os.makedirs(workdir, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, RUN_AUDIT, "--url", url, "--workdir", workdir,
         "--max-pages", "20", "--no-render"],
        capture_output=True, text=True)
    report_path = os.path.join(workdir, "audit-report.json")
    if not os.path.exists(report_path):
        raise SystemExit("audit did not produce a report for %s\n%s"
                         % (url, proc.stderr[-2000:]))
    with open(report_path) as fh:
        return json.load(fh)


def check_ids(report, bucket):
    if bucket == "findings":
        return {f["check_id"] for f in report["findings"]}
    return {x["check_id"] for x in report.get(bucket, [])}


def finding(report, check_id):
    """Return the first finding with this check_id, or None."""
    for f in report["findings"]:
        if f["check_id"] == check_id:
            return f
    return None


def reason_for(report, bucket, check_id):
    """Return the reason recorded for a check_id in not_applicable/inconclusive."""
    for x in report.get(bucket, []):
        if x["check_id"] == check_id:
            return x.get("reason", "")
    return None


# ---------------------------------------------------------------- assertions

RESULTS = []


def expect(cond, label):
    RESULTS.append((bool(cond), label))
    mark = "PASS" if cond else "FAIL"
    print("  [%s] %s" % (mark, label))


def run():
    print("Serving fixtures...")
    good = serve(os.path.join(FIXTURES, "goodsite"), GOOD_PORT)
    bad = serve(os.path.join(FIXTURES, "badsite"), BAD_PORT)
    conflict = serve(os.path.join(FIXTURES, "conflictsite"), CONFLICT_PORT)
    time.sleep(0.3)

    try:
        print("Auditing badsite...")
        bad_report = audit("http://127.0.0.1:%d/" % BAD_PORT,
                           os.path.join(WORK, "badsite"))
        print("Auditing goodsite...")
        good_report = audit("http://127.0.0.1:%d/" % GOOD_PORT,
                            os.path.join(WORK, "goodsite"))
        print("Auditing conflictsite...")
        conflict_report = audit("http://127.0.0.1:%d/" % CONFLICT_PORT,
                                os.path.join(WORK, "conflictsite"))
        print("Auditing badsite again (determinism)...")
        bad_report2 = audit("http://127.0.0.1:%d/" % BAD_PORT,
                            os.path.join(WORK, "badsite2"))
    finally:
        good.shutdown()
        bad.shutdown()
        conflict.shutdown()

    bad_fire = check_ids(bad_report, "findings")
    good_fire = check_ids(good_report, "findings")

    # -- Positive: each of these MUST fire on the broken site ---------------
    print("\nbadsite - checks that must fire:")
    must_fire = [
        ("ACC-AI-CRAWLER-BLOCKED", "robots.txt blocks GPTBot"),
        ("MR-EMPTY-SHELL", "JS application shell, no server-rendered text"),
        ("MR-MULTI-H1", "duplicate H1 headings"),
        ("SD-ABSENT", "no structured data anywhere"),
        ("FP-STALE-COPYRIGHT", "copyright year 2019"),
    ]
    for cid, why in must_fire:
        expect(cid in bad_fire, "%s fires (%s)" % (cid, why))

    # The badsite critical must be present and be severity critical.
    crit = [f for f in bad_report["findings"]
            if f["check_id"] == "ACC-AI-CRAWLER-BLOCKED"]
    expect(crit and crit[0]["severity"] == "critical",
           "ACC-AI-CRAWLER-BLOCKED is severity critical")

    # -- Negative: the clean site must NOT raise these ----------------------
    print("\ngoodsite - checks that must stay silent:")
    must_not_fire = [
        "ACC-AI-CRAWLER-BLOCKED", "ACC-BLANKET-DISALLOW", "SD-ABSENT",
        "SD-NO-ORGANIZATION", "SD-NO-SAMEAS", "MR-EMPTY-SHELL",
        "MR-MULTI-H1", "MR-NO-MAIN-LANDMARK", "AE-NO-DEFINITION",
        "FP-STALE-COPYRIGHT", "EN-NO-VIEWPORT", "EN-NO-SITE-SEARCH",
        "AE-NO-HEADING-ANCHORS",
    ]
    for cid in must_not_fire:
        expect(cid not in good_fire, "%s does NOT fire on clean site" % cid)

    # The clean site should be nearly clean overall. Rather than an arbitrary
    # count that breaks whenever a check is tuned, assert the meaningful
    # properties: nothing severe fires, and every finding that does is a
    # low-severity, low-confidence heuristic (never a confident defect claim).
    expect(good_report["summary"]["critical"] == 0,
           "goodsite has zero critical findings")
    expect(good_report["summary"]["high"] == 0,
           "goodsite has zero high-severity findings")
    expect(all(f["severity"] in ("medium", "low")
               for f in good_report["findings"]),
           "goodsite raises only medium/low findings if any (got severities: %s)"
           % sorted({f["severity"] for f in good_report["findings"]}))

    # -- conflictsite: the markup-vs-text price disagreement ----------------
    print("\nconflictsite - markup contradicts visible price:")
    conflict_fire = check_ids(conflict_report, "findings")
    expect("SD-TEXT-CONFLICT" in conflict_fire,
           "SD-TEXT-CONFLICT fires when JSON-LD price != visible price")
    # It has valid Organization + sameAs, so those must stay silent.
    expect("SD-NO-ORGANIZATION" not in conflict_fire,
           "SD-NO-ORGANIZATION silent (Organization node present)")
    expect("SD-NO-SAMEAS" not in conflict_fire,
           "SD-NO-SAMEAS silent (sameAs present)")

    # Fix #4 — the price-conflict check is now currency-aware and compares the
    # full decimal. conflictsite has TWO product pages: widget (markup USD 49 vs
    # visible $129 -> a real conflict) and agree (markup USD 19.99 vs visible
    # $19.99, plus a EUR shipping figure -> must NOT conflict). So exactly one
    # product page conflicts: the check fires, but only for widget, and the EUR
    # figure must not manufacture a phantom conflict on the agree page.
    sd_conflict = finding(conflict_report, "SD-TEXT-CONFLICT")
    expect(sd_conflict is not None
           and sd_conflict["prevalence"]["affected"] == 1,
           "SD-TEXT-CONFLICT flags exactly the one genuinely conflicting page")
    expect(sd_conflict is not None
           and all("agree" not in u for u in sd_conflict.get("affected_urls", [])),
           "SD-TEXT-CONFLICT does NOT fire on the matching-price page "
           "(no full-decimal or cross-currency false positive)")

    # -- Fix #2: entity-corroboration is not a silent no-op offline ----------
    print("\nentity anchoring (works with no search):")
    # badsite has no JSON-LD, no external profiles, no sameAs: a concrete,
    # search-free identity-anchoring risk the skill must surface rather than
    # only recording everything inconclusive.
    expect("EC-WEAK-IDENTITY-ANCHORING" in bad_fire,
           "EC-WEAK-IDENTITY-ANCHORING fires on a site with no identity anchors")
    # goodsite and conflictsite both carry Organization + sameAs, so the anchor
    # is present and the check must stay silent.
    expect("EC-WEAK-IDENTITY-ANCHORING" not in good_fire,
           "EC-WEAK-IDENTITY-ANCHORING silent when Organization + sameAs present "
           "(goodsite)")
    expect("EC-WEAK-IDENTITY-ANCHORING" not in conflict_fire,
           "EC-WEAK-IDENTITY-ANCHORING silent when Organization + sameAs present "
           "(conflictsite)")

    # -- Fix #3: render honesty ----------------------------------------------
    print("\nrender honesty (tests run with --no-render):")
    # The audit ran with --no-render, so MR-RENDER-GAP is inconclusive. Its
    # reason must say rendering was *disabled*, not that no browser exists —
    # the tool must not confuse a declined capability with a missing one.
    rr = reason_for(bad_report, "inconclusive", "MR-RENDER-GAP")
    expect(rr is not None and "disabled" in rr.lower(),
           "MR-RENDER-GAP reason says rendering was disabled by flag")
    expect(rr is not None and "no headless browser is installed" not in rr.lower(),
           "MR-RENDER-GAP does not claim a browser was missing when it was "
           "merely disabled")

    # -- Fix #5: a low-confidence brand guess reads as a hypothesis ----------
    # AE-ENTITY-NOT-RESTATED, when it fires on a brand inferred only from title
    # text, must phrase the evidence as an assumption. On the fixtures the check
    # may or may not fire; when it does with a title-only guess, assert the
    # wording. This is a conditional assertion, skipped cleanly if not present.
    for name, rep in (("badsite", bad_report), ("goodsite", good_report),
                      ("conflictsite", conflict_report)):
        ae = finding(rep, "AE-ENTITY-NOT-RESTATED")
        if ae and ae.get("confidence") == "low":
            expect("assuming the brand" in ae["evidence"].lower(),
                   "%s: title-only brand guess is phrased as an assumption"
                   % name)

    # -- Structural guarantees the schema cannot express --------------------
    print("\nstructural guarantees:")
    for name, rep in (("badsite", bad_report), ("goodsite", good_report)):
        s = rep["summary"]
        expect(s["total_findings"] == len(rep["findings"]),
               "%s: total_findings matches findings length" % name)
        counted = {k: sum(1 for f in rep["findings"] if f["severity"] == k)
                   for k in ("critical", "high", "medium", "low")}
        expect(all(s[k] == counted[k] for k in counted),
               "%s: severity counts match findings" % name)
        expect(all(f["suggested_action"].get("priority") == f["severity"]
                   for f in rep["findings"]),
               "%s: every action priority equals its finding severity" % name)
        ids = [f["id"] for f in rep["findings"]]
        expect(ids == sorted(ids), "%s: finding ids are in order" % name)
        expect(len(rep.get("proactive_recommendations", [])) >= 5,
               "%s: proactive recommendations present" % name)
        expect(rep.get("not_applicable") is not None
               and len(rep["not_applicable"]) > 0,
               "%s: not_applicable records present (checks that ran silently)"
               % name)
        # Prevalence must be a coherent ratio: affected <= sampled, always.
        # A finding reporting affected > sampled (mixing a heading count against
        # a page count, say) is nonsensical evidence a reader would distrust.
        bad_prev = [f["check_id"] for f in rep["findings"]
                    if (f.get("prevalence") or {}).get("affected", 0)
                    > (f.get("prevalence") or {}).get("sampled", 0)]
        expect(not bad_prev,
               "%s: every finding has affected <= sampled (offenders: %s)"
               % (name, bad_prev))

    # -- Determinism: audit badsite twice, reports match --------------------
    print("\ndeterminism:")

    def norm(r):
        r = json.loads(json.dumps(r))
        r["audited_at"] = "X"
        r.get("audit_meta", {})["runtime_seconds"] = "X"
        return json.dumps(r, sort_keys=True)
    expect(norm(bad_report) == norm(bad_report2),
           "two badsite audits produce identical reports")

    # The strong guarantee: over a FROZEN snapshot, the analysis is a pure
    # function. Re-run every analyser + compose ten times against one saved
    # snapshot and hash the report; all ten must be identical. This isolates
    # analysis determinism from all network variance.
    snap_src = os.path.join(WORK, "badsite")
    hashes = set()
    for i in range(10):
        wd = os.path.join(WORK, "frozen-%d" % i)
        if os.path.exists(wd):
            import shutil
            shutil.rmtree(wd)
        os.makedirs(wd)
        import shutil
        shutil.copy(os.path.join(snap_src, "snapshot.json"),
                    os.path.join(wd, "snapshot.json"))
        for sk in ("site-acquisition", "machine-readability", "structured-data",
                   "answer-extractability", "entity-corroboration",
                   "freshness-provenance", "engagement-audit"):
            subprocess.run(
                [sys.executable,
                 os.path.join(ROOT, "skills", sk, "scripts", "analyze.py"),
                 "--workdir", wd], capture_output=True)
        out = os.path.join(wd, "audit-report.json")
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "skills", "audit-orchestrator",
                                          "scripts", "compose_report.py"),
             "--workdir", wd, "--out", out], capture_output=True)
        with open(out) as fh:
            import hashlib
            hashes.add(hashlib.sha256(norm(json.load(fh)).encode()).hexdigest())
        shutil.rmtree(wd, ignore_errors=True)
    expect(len(hashes) == 1,
           "analysis is a pure function of the snapshot "
           "(10 runs -> %d distinct report(s))" % len(hashes))

    # -- Focused regression units: freshness false positives ----------------
    # These build a synthetic snapshot and run one analyser directly, isolating
    # two false positives found while validating against live sites:
    #   * a blog "posts by year" archive widget (headings 2005..2026) must not
    #     read as a stale page — it is navigation, and it contains the current
    #     year; and
    #   * a copyright RANGE or a bare founding year must not read as stale when
    #     the site also shows a current year.
    print("\nfreshness regression units:")
    import shutil as _sh

    def run_freshness(snapshot):
        wd = os.path.join(WORK, "unit-fresh")
        if os.path.exists(wd):
            _sh.rmtree(wd)
        os.makedirs(wd)
        with open(os.path.join(wd, "snapshot.json"), "w") as fh:
            json.dump(snapshot, fh)
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "skills", "freshness-provenance",
                                          "scripts", "analyze.py"),
             "--workdir", wd], capture_output=True)
        with open(os.path.join(wd, "fragments",
                               "freshness-provenance.json")) as fh:
            frag = json.load(fh)
        _sh.rmtree(wd, ignore_errors=True)
        return {f["check_id"] for f in frag["findings"]}

    def page(url, headings=None, text=""):
        return {
            "url": url, "final_url": url, "status": 200,
            "raw_html": "<html>x</html>", "text": text, "body_text": text,
            "headings": headings or [], "page_type": "article",
            "images": [], "meta_robots": None, "headers": {},
        }

    # (a) archive widget: years 2005..2026 as bare headings + a current range.
    archive_headings = [{"level": 2, "text": str(y), "id": None}
                        for y in range(2005, 2027)]
    snap_archive = {
        "site": "blog.example.com", "base_url": "https://blog.example.com/",
        "audited_at": "2026-01-01T00:00:00Z", "site_type": "publisher",
        "render_mode": "static-only", "render_status": "disabled-by-flag",
        "pages": [page("https://blog.example.com/post",
                       headings=archive_headings,
                       text="© 2005-2026 Example Blog. A normal post body with "
                            "enough words to be substantive content here."),
                  page("https://blog.example.com/post2",
                       headings=[{"level": 2, "text": "Archive 2018", "id": None}],
                       text="© 2005-2026 Example Blog. Another substantive body "
                            "of text on this second page to pass thresholds.")],
        "sitemap": {"lastmod": {}}, "sitemap_urls": [],
    }
    fired = run_freshness(snap_archive)
    expect("FP-STALE-YEAR-HEADINGS" not in fired,
           "archive year-widget headings do NOT fire FP-STALE-YEAR-HEADINGS")
    expect("FP-STALE-COPYRIGHT" not in fired,
           "a current copyright range does NOT fire FP-STALE-COPYRIGHT")

    # (b) genuinely stale: a real title naming a past year, no current year.
    snap_stale = {
        "site": "old.example.com", "base_url": "https://old.example.com/",
        "audited_at": "2026-01-01T00:00:00Z", "site_type": "publisher",
        "render_mode": "static-only", "render_status": "disabled-by-flag",
        "pages": [page("https://old.example.com/guide",
                       headings=[{"level": 1,
                                  "text": "The complete SEO guide for 2019",
                                  "id": None}],
                       text="© 2019 Old Example. This guide has plenty of body "
                            "text discussing the topic at length for the year.")],
        "sitemap": {"lastmod": {}}, "sitemap_urls": [],
    }
    fired2 = run_freshness(snap_stale)
    expect("FP-STALE-YEAR-HEADINGS" in fired2,
           "a real past-year heading still fires FP-STALE-YEAR-HEADINGS")
    expect("FP-STALE-COPYRIGHT" in fired2,
           "a lone stale copyright with no current year still fires")

    # -- Organization subtype + lenient JSON-LD regressions -----------------
    # Both of these were real false positives found by auditing live D2C
    # brands, not by the fixtures. They are pinned here so they cannot return.
    print("\nstructured-data / freshness regression units:")

    import auditlib as _A

    # (a) schema.org Organization SUBTYPES must count as an Organization.
    # ruggable.com declares `OnlineStore` (the Shopify default) and was told
    # it had "no Organization node anywhere on the site" — a high-severity
    # finding an author can see is wrong, which discredits the whole report.
    expect(all(_A.is_org_type(t) for t in
               ("Organization", "LocalBusiness", "OnlineStore",
                "NewsMediaOrganization", "Dentist", "ClothingStore",
                "https://schema.org/OnlineStore")),
           "Organization subtypes are recognised as an Organization identity")
    expect(not any(_A.is_org_type(t) for t in
                   ("Product", "Article", "WebSite", "Person", "Service",
                    "BreadcrumbList", "FinancialProduct")),
           "non-Organization types are NOT mistaken for an Organization")

    def run_sd(snapshot):
        wd = os.path.join(WORK, "unit-sd")
        if os.path.exists(wd):
            _sh.rmtree(wd)
        os.makedirs(wd)
        with open(os.path.join(wd, "snapshot.json"), "w") as fh:
            json.dump(snapshot, fh)
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "skills", "structured-data",
                                          "scripts", "analyze.py"),
             "--workdir", wd], capture_output=True)
        with open(os.path.join(wd, "fragments", "structured-data.json")) as fh:
            frag = json.load(fh)
        _sh.rmtree(wd, ignore_errors=True)
        return {f["check_id"] for f in frag["findings"]}

    def sd_page(url, ptype, jsonld):
        return {
            "url": url, "final_url": url, "status": 200,
            "raw_html": "<html>x</html>", "text": "Some body text here.",
            "body_text": "Some body text here.", "headings": [],
            "page_type": ptype, "images": [], "meta_robots": None,
            "headers": {}, "jsonld_raw": jsonld,
        }

    onlinestore = ('{"@context":"https://schema.org","@type":"OnlineStore",'
                   '"name":"Rugs Co","url":"https://shop.example.com/",'
                   '"sameAs":["https://www.instagram.com/rugsco"]}')
    snap_store = {
        "site": "shop.example.com", "base_url": "https://shop.example.com/",
        "audited_at": "2026-01-01T00:00:00Z", "site_type": "ecommerce",
        "render_mode": "static-only", "render_status": "disabled-by-flag",
        "pages": [sd_page("https://shop.example.com/", "home", [onlinestore])],
    }
    fired_store = run_sd(snap_store)
    expect("SD-NO-ORGANIZATION" not in fired_store,
           "an OnlineStore node does NOT fire SD-NO-ORGANIZATION")
    expect("SD-COVERAGE-HOME" not in fired_store,
           "an OnlineStore node satisfies home-page schema coverage")
    expect("SD-NO-SAMEAS" not in fired_store,
           "sameAs on an Organization subtype is read (no SD-NO-SAMEAS)")

    snap_nostore = {
        "site": "shop.example.com", "base_url": "https://shop.example.com/",
        "audited_at": "2026-01-01T00:00:00Z", "site_type": "ecommerce",
        "render_mode": "static-only", "render_status": "disabled-by-flag",
        "pages": [sd_page("https://shop.example.com/", "home",
                          ['{"@context":"https://schema.org",'
                           '"@type":"WebPage","name":"Home"}'])],
    }
    expect("SD-NO-ORGANIZATION" in run_sd(snap_nostore),
           "a site with genuinely no Organization node still fires")

    # (b) JSON-LD with a raw newline inside a string value must still be read.
    # glossier.com embeds an `articleBody` containing literal newlines; strict
    # json.loads fails, and every correctly-declared datePublished became
    # invisible, firing FP-NO-DATES on properly dated articles.
    dirty = ('{"@context":"https://schema.org","@type":"Article",'
             '"headline":"A post","articleBody":"Line one\nline two",'
             '"datePublished":"2025-05-04T11:17:45Z"}')
    snap_dirty = {
        "site": "blog.example.com", "base_url": "https://blog.example.com/",
        "audited_at": "2026-01-01T00:00:00Z", "site_type": "publisher",
        "render_mode": "static-only", "render_status": "disabled-by-flag",
        "pages": [dict(page("https://blog.example.com/a",
                            text="A substantive body of article copy here."),
                       jsonld_raw=[dirty]),
                  dict(page("https://blog.example.com/b",
                            text="Another substantive body of article copy."),
                       jsonld_raw=[dirty])],
    }
    expect("FP-NO-DATES" not in run_freshness(snap_dirty),
           "dates survive a raw control character in JSON-LD (no FP-NO-DATES)")

    snap_undated = {
        "site": "blog.example.com", "base_url": "https://blog.example.com/",
        "audited_at": "2026-01-01T00:00:00Z", "site_type": "publisher",
        "render_mode": "static-only", "render_status": "disabled-by-flag",
        "pages": [dict(page("https://blog.example.com/a",
                            text="A substantive body of article copy here."),
                       jsonld_raw=['{"@context":"https://schema.org",'
                                   '"@type":"Article","headline":"No date"}']),
                  dict(page("https://blog.example.com/b",
                            text="Another substantive body of article copy."),
                       jsonld_raw=[])],
    }
    expect("FP-NO-DATES" in run_freshness(snap_undated),
           "genuinely undated articles still fire FP-NO-DATES")

    # -- Unreachable-origin honesty regressions -----------------------------
    # An SSLError/DNS failure/timeout means the request never reached the
    # origin, so it is not evidence the site lacks a robots.txt or sitemap —
    # and the cause is often the auditing environment (TLS interception, a
    # sandboxed resolver). Asserting "No robots.txt served" there states an
    # unobserved fact. Found by auditing caraway.com and away.com live.
    print("\nunreachable-origin honesty units:")

    def run_acq(snapshot):
        wd = os.path.join(WORK, "unit-acq")
        if os.path.exists(wd):
            _sh.rmtree(wd)
        os.makedirs(wd)
        with open(os.path.join(wd, "snapshot.json"), "w") as fh:
            json.dump(snapshot, fh)
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "skills", "site-acquisition",
                                          "scripts", "analyze.py"),
             "--workdir", wd], capture_output=True)
        with open(os.path.join(wd, "fragments", "site-acquisition.json")) as fh:
            frag = json.load(fh)
        _sh.rmtree(wd, ignore_errors=True)
        return ({f["check_id"] for f in frag["findings"]},
                {i["check_id"] for i in frag.get("inconclusive", [])})

    def acq_snap(robots_status, sitemap_error):
        return {
            "site": "shop.example.com",
            "base_url": "https://shop.example.com/",
            "audited_at": "2026-01-01T00:00:00Z", "site_type": "unknown",
            "render_mode": "static-only", "render_status": "disabled-by-flag",
            "robots": {"present": False, "status": robots_status, "body": "",
                       "ai_agents_blocked": [], "blanket_disallow": False,
                       "sitemaps": [], "parse_error": None,
                       "url": "https://shop.example.com/robots.txt"},
            "sitemap": {"found": False, "url_count": 0, "lastmod": {},
                        "checked": ["https://shop.example.com/sitemap.xml"],
                        "errors": ["https://shop.example.com/sitemap.xml -> %s"
                                   % sitemap_error]},
            "pages": [],
        }

    for transport in ("SSLError", "ConnectionError", "Timeout"):
        fired, unknown = run_acq(acq_snap(transport, transport))
        expect("ACC-NO-ROBOTS" not in fired and "ACC-NO-ROBOTS" in unknown,
               "%s on robots.txt is inconclusive, not 'No robots.txt served'"
               % transport)
        expect("ACC-NO-SITEMAP" not in fired and "ACC-NO-SITEMAP" in unknown,
               "%s on the sitemap is inconclusive, not 'no sitemap'" % transport)

    # The negative direction: a site that genuinely answers 404 for both IS
    # missing them, and must still be told so.
    fired404, unknown404 = run_acq(acq_snap(404, 404))
    expect("ACC-NO-ROBOTS" in fired404,
           "a real 404 on robots.txt still fires ACC-NO-ROBOTS")
    expect("ACC-NO-SITEMAP" in fired404,
           "a real 404 on the sitemap still fires ACC-NO-SITEMAP")

    # -- Supporting-schema precedence regressions ---------------------------
    # FAQPage/HowTo are routinely embedded as enhancements on commerce pages.
    # Treating them as the page's identity classified quince.com's and
    # drsquatch.com's product pages as "documentation", silencing every
    # product check and mislabelling both sites as documentation sites.
    print("\npage-type precedence units:")
    sys.path.insert(0, os.path.join(ROOT, "skills", "site-acquisition",
                                    "scripts"))
    import classify as _classify

    faq = ('{"@context":"https://schema.org","@type":"FAQPage",'
           '"mainEntity":[{"@type":"Question","name":"How do I wash it?",'
           '"acceptedAnswer":{"@type":"Answer","text":"Machine wash cold."}}]}')
    pdp = {
        "url": "https://shop.example.com/women/crossiant-ring",
        "final_url": "https://shop.example.com/women/crossiant-ring",
        "status": 200, "jsonld_raw": [faq], "headings": [],
        "body_text": "Crossiant Ring $68.00 ADD TO BAG Free shipping.",
        "text": "Crossiant Ring $68.00 ADD TO BAG Free shipping.",
        "internal_links": 20,
    }
    expect(_classify.classify_page(pdp, "https://shop.example.com/") == "product",
           "a product page carrying an FAQ block classifies as product")

    # The negative direction: a genuine FAQ page with no commerce signals must
    # still classify as documentation, or the fix would simply hide FAQPage.
    real_faq = {
        "url": "https://shop.example.com/help/faq",
        "final_url": "https://shop.example.com/help/faq",
        "status": 200, "jsonld_raw": [faq], "headings": [],
        "body_text": "Frequently asked questions about orders and returns.",
        "text": "Frequently asked questions about orders and returns.",
        "internal_links": 5,
    }
    expect(_classify.classify_page(real_faq, "https://shop.example.com/")
           == "documentation",
           "a genuine FAQ page with no commerce signals stays documentation")

    # A defining type still wins outright over a co-declared supporting type.
    both = dict(pdp, jsonld_raw=[faq, '{"@context":"https://schema.org",'
                                 '"@type":"Product","name":"Ring"}'])
    expect(_classify.classify_page(both, "https://shop.example.com/") == "product",
           "a declared Product outranks a co-declared FAQPage")

    # -- Truncated-evidence regressions --------------------------------------
    # Found by auditing misen.com: the snapshot stores only the first 400 000
    # characters of each page, and that store carried megabytes of inlined
    # product JSON before its header markup, so the site's search box sat at
    # offset ~2.3 M. A check scanning the STORED html therefore saw no search
    # input and reported "a large site offers no on-site search" about a site
    # that has one. The crawler now decides these on the full document and
    # stores the verdict as a flag; the analyser must trust the flag.
    def run_engagement(snapshot):
        wd = os.path.join(WORK, "unit-engagement")
        if os.path.exists(wd):
            _sh.rmtree(wd)
        os.makedirs(wd)
        with open(os.path.join(wd, "snapshot.json"), "w") as fh:
            json.dump(snapshot, fh)
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "skills", "engagement-audit",
                                          "scripts", "analyze.py"),
             "--workdir", wd], capture_output=True)
        with open(os.path.join(wd, "fragments", "engagement-audit.json")) as fh:
            frag = json.load(fh)
        _sh.rmtree(wd, ignore_errors=True)
        return {f["check_id"] for f in frag["findings"]}

    def big_page(url, has_search, has_autoplay=False):
        # raw_html deliberately carries NO search/autoplay markup, standing in
        # for a document whose real markup fell beyond the truncation point.
        p = page(url, text="Body copy with enough words to be substantive here.")
        p.update({"page_type": "listing", "raw_html": "<html><body>" + ("x" * 200)
                  + "</body></html>", "has_search": has_search,
                  "has_autoplay": has_autoplay, "internal_links": 8,
                  "bytes": 4_900_000, "elapsed_ms": 200, "has_nav": True,
                  "viewport": "width=device-width", "iframes": []})
        return p

    def big_snap(has_search, has_autoplay=False):
        return {
            "site": "shop.example.com", "base_url": "https://shop.example.com/",
            "audited_at": "2026-01-01T00:00:00Z", "site_type": "ecommerce",
            "render_mode": "static-only", "render_status": "disabled-by-flag",
            "pages": [big_page("https://shop.example.com/p/%d" % i, has_search,
                               has_autoplay) for i in range(20)],
        }

    expect("EN-NO-SITE-SEARCH" not in run_engagement(big_snap(True)),
           "search found beyond the truncation point does NOT fire "
           "EN-NO-SITE-SEARCH")
    expect("EN-NO-SITE-SEARCH" in run_engagement(big_snap(False)),
           "a site genuinely without search still fires EN-NO-SITE-SEARCH")
    expect("EN-AUTOPLAY-MEDIA" in run_engagement(
               big_snap(True, has_autoplay=True)),
           "autoplay beyond the truncation point is still detected")
    expect("EN-AUTOPLAY-MEDIA" not in run_engagement(big_snap(True)),
           "a site without autoplay does NOT fire EN-AUTOPLAY-MEDIA")

    # The crawler must set these flags from the full document, not the copy it
    # stores. This pins the mechanism itself, independently of any analyser.
    import crawl as _crawl
    huge = ("<html><head><title>T</title></head><body>"
            + "<span>%s</span>" % ("y" * 500000)
            + '<form role="search"><input type="search" name="q" '
              'placeholder="Search products"></form>'
            + '<video autoplay muted src="/v.mp4"></video>'
            + "</body></html>")
    meta_full = _crawl.page_meta(huge, "https://shop.example.com/")
    expect(meta_full.get("has_search") is True,
           "crawler detects a search box lying past 400k chars")
    expect(meta_full.get("has_autoplay") is True,
           "crawler detects autoplay lying past 400k chars")
    plain = _crawl.page_meta("<html><body><p>No search here.</p></body></html>",
                             "https://shop.example.com/")
    expect(plain.get("has_search") is False,
           "crawler reports no search when the document truly has none")
    expect(plain.get("has_autoplay") is False,
           "crawler reports no autoplay when the document truly has none")

    # -- Skill-format and safety hygiene -------------------------------------
    # Each skill folder must stand on its own: the brief requires every skill
    # to satisfy the agentskills.io spec independently and to declare its own
    # guardrails, because a skill can be lifted out of this marketplace and
    # read alone. A guarantee that lives only in the README is not portable.
    print("\nskill-format and safety hygiene:")
    import glob as _glob
    skill_files = sorted(_glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")))
    expect(len(skill_files) == 8, "all eight skill folders carry a SKILL.md")

    for sf in skill_files:
        sid = os.path.basename(os.path.dirname(sf))
        body = open(sf, encoding="utf-8").read()
        lines = body.splitlines()
        expect(lines[0].strip() == "---",
               "%s: SKILL.md opens with YAML frontmatter" % sid)
        fm_end = next((i for i, l in enumerate(lines[1:], 1)
                       if l.strip() == "---"), None)
        fm = "\n".join(lines[1:fm_end or 1])
        for key in ("name:", "description:", "license:"):
            expect(key in fm, "%s: frontmatter declares %s" % (sid, key.strip(':')))
        expect(("name: %s" % sid) in fm,
               "%s: frontmatter name matches its folder" % sid)
        expect("allowed-tools:" in fm,
               "%s: declares its tool needs" % sid)
        expect("## Safety" in body,
               "%s: states its read-only guardrails in its own SKILL.md" % sid)
        expect(len(lines) <= 150,
               "%s: SKILL.md stays lean (%d lines)" % (sid, len(lines)))

    # The offline analysers claim in their SKILL.md to open no network
    # connection. That is a promise an evaluator can check, so pin it: none of
    # them may import a networking library. (entity-corroboration is excluded:
    # it legitimately consumes search results, and imports urllib.parse for
    # string handling only.)
    import re as _re
    net = _re.compile(
        r"^\s*(?:import|from)\s+(requests|http|socket|urllib\.request)\b", _re.M)
    for sid in ("answer-extractability", "engagement-audit",
                "freshness-provenance", "machine-readability",
                "structured-data"):
        src = open(os.path.join(ROOT, "skills", sid, "scripts", "analyze.py"),
                   encoding="utf-8").read()
        expect(not net.search(src),
               "%s imports no networking library (it is snapshot-pure)" % sid)

    # Manifest hygiene: exactly one entrypoint, every declared path real.
    mani = json.load(open(os.path.join(ROOT, "marketplace.json"), encoding="utf-8"))
    entries = [s for s in mani["skills"] if s.get("entrypoint")]
    expect(len(entries) == 1, "manifest marks exactly one entrypoint")
    expect(all(os.path.isfile(os.path.join(ROOT, s["path"], "SKILL.md"))
               for s in mani["skills"]),
           "every manifest path resolves to a real skill folder")
    expect({s["id"] for s in mani["skills"]} ==
           {os.path.basename(os.path.dirname(f)) for f in skill_files},
           "manifest lists exactly the skill folders present (no orphans)")

    # -- Proactive-recommendation relevance ----------------------------------
    # The standing set is mechanism-based and mostly universal, but two kinds
    # of entry must not be emitted blindly: advice about pages when no page was
    # ever retrieved (hims.com answered 403 to everything, so page-structure
    # advice would be asserted about pages nobody saw), and advice the audit
    # has already raised as a finding, which reads as padding and buries the
    # entry that actually carries the evidence.
    print("\nproactive-recommendation relevance:")
    sys.path.insert(0, os.path.join(ROOT, "skills", "audit-orchestrator",
                                    "scripts"))
    import compose_report as _cr

    def snap_with(pages):
        return {"site": "example.com", "base_url": "https://example.com/",
                "audited_at": "2026-01-01T00:00:00Z", "site_type": "ecommerce",
                "pages": pages}

    live = snap_with([{"url": "https://example.com/", "final_url":
                       "https://example.com/", "status": 200, "iframes": [],
                       "has_autoplay": False}])
    blocked = snap_with([{"url": "https://example.com/", "final_url":
                          "https://example.com/", "status": 403,
                          "iframes": [], "has_autoplay": False}])
    with_media = snap_with([{"url": "https://example.com/", "final_url":
                             "https://example.com/", "status": 200,
                             "iframes": ["https://youtube.com/embed/x"],
                             "has_autoplay": False}])

    ids = lambda snap, fired=frozenset(): [
        r["id"] for r in _cr.select_proactive(snap, set(fired))]

    expect("P-002" in ids(live),
           "page-structure advice is offered when pages were retrieved")
    expect("P-002" not in ids(blocked),
           "page-structure advice is withheld when nothing could be crawled")
    expect(ids(blocked),
           "an unreachable origin still receives off-page advice")
    expect("P-006" not in ids(live),
           "transcript advice is withheld when no media was observed")
    expect("P-006" in ids(with_media),
           "transcript advice appears when the site embeds media")
    expect("P-003" not in ids(live, {"AE-NO-HEADING-ANCHORS"}),
           "advice already raised as a finding is not repeated proactively")
    expect("P-003" in ids(live),
           "that same advice is offered when no finding covers it")
    expect(not [k for r in _cr.select_proactive(live, set())
                for k in r if k in ("requires_pages", "requires_media",
                                    "redundant_if")],
           "internal gating keys never reach the emitted report")
    expect(ids(live) == ids(live),
           "proactive selection is deterministic")

    # -- Actionability invariants -------------------------------------------
    # The fix is the product. A finding an author cannot act on is a complaint,
    # so these assert the properties that make a remedy usable: it says WHERE
    # (affected_urls, unless the claim is genuinely site-level), it says HOW
    # (concrete steps), and it says HOW TO CONFIRM (verification).
    print("\nactionability invariants:")

    # Checks whose claim really is about the whole site, so per-page URLs
    # would be meaningless rather than missing.
    SITE_LEVEL = {
        "ACC-NO-ROBOTS", "ACC-NO-SITEMAP", "ACC-SITEMAP-NOT-ENUMERABLE",
        "ACC-AI-CRAWLER-BLOCKED", "ACC-BLANKET-DISALLOW", "SD-NO-ORGANIZATION",
        "SD-NO-SAMEAS", "EN-NO-SITE-SEARCH", "EC-WEAK-IDENTITY-ANCHORING",
        "EC-INCONSISTENT-SELF-DESCRIPTION", "EC-NO-EXTERNAL-PROFILES",
        "EC-FEW-EXTERNAL-PROFILES",
        "EC-NAME-COLLISION", "EC-SINGLE-SOURCE-CLAIMS", "EC-NAP-INCONSISTENT",
        "MR-RENDER-GAP", "FP-LASTMOD-UNIFORM", "FP-LASTMOD-DISHONEST",
    }
    for label, rep in (("badsite", bad_report), ("goodsite", good_report)):
        missing_where, missing_how, missing_verify = [], [], []
        for fdg in rep["findings"]:
            act = fdg.get("suggested_action") or {}
            if (fdg["check_id"] not in SITE_LEVEL
                    and not (fdg.get("affected_urls") or [])):
                missing_where.append(fdg["check_id"])
            if not [x for x in (act.get("steps") or []) if x.strip()]:
                missing_how.append(fdg["check_id"])
            if not (act.get("verification") or "").strip():
                missing_verify.append(fdg["check_id"])
        expect(not missing_where,
               "%s: every page-level finding names the pages to fix "
               "(offenders: %s)" % (label, missing_where))
        expect(not missing_how,
               "%s: every finding carries concrete remediation steps "
               "(offenders: %s)" % (label, missing_how))
        expect(not missing_verify,
               "%s: every finding says how to verify the fix (offenders: %s)"
               % (label, missing_verify))

    # MR-ALT-COVERAGE reported a bare site-wide ratio and named no page, so an
    # author was told the size of the problem and nothing about where to start.
    alt_snap = {
        "site": "shop.example.com", "base_url": "https://shop.example.com/",
        "audited_at": "2026-01-01T00:00:00Z", "site_type": "ecommerce",
        "render_mode": "static-only", "render_status": "disabled-by-flag",
        "pages": [{
            "url": "https://shop.example.com/p/%d" % i,
            "final_url": "https://shop.example.com/p/%d" % i,
            "status": 200, "raw_html": "<html><body>x</body></html>",
            "text": "Body copy.", "body_text": "Body copy.",
            "headings": [], "page_type": "product", "meta_robots": None,
            "headers": {}, "jsonld_raw": [], "h1": ["A"],
            "images": [{"src": "/img/%d-%d.jpg" % (i, j), "alt": ""}
                       for j in range(6)],
        } for i in range(3)],
    }
    wd_alt = os.path.join(WORK, "unit-alt")
    if os.path.exists(wd_alt):
        _sh.rmtree(wd_alt)
    os.makedirs(wd_alt)
    with open(os.path.join(wd_alt, "snapshot.json"), "w") as fh:
        json.dump(alt_snap, fh)
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "skills", "machine-readability",
                                      "scripts", "analyze.py"),
         "--workdir", wd_alt], capture_output=True)
    with open(os.path.join(wd_alt, "fragments",
                           "machine-readability.json")) as fh:
        alt_frag = json.load(fh)
    _sh.rmtree(wd_alt, ignore_errors=True)
    alt = [x for x in alt_frag["findings"]
           if x["check_id"] == "MR-ALT-COVERAGE"]
    expect(bool(alt) and len(alt[0].get("affected_urls") or []) == 3,
           "MR-ALT-COVERAGE names the pages whose images lack alt text")
    expect(bool(alt) and "Worst pages:" in alt[0]["evidence"],
           "MR-ALT-COVERAGE ranks the worst offending pages in its evidence")

    # -- Summary ------------------------------------------------------------
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n%d/%d assertions passed." % (passed, total))
    if passed != total:
        print("FAILURES:")
        for ok, label in RESULTS:
            if not ok:
                print("  - %s" % label)
        sys.exit(1)
    print("All fixture tests passed.")


if __name__ == "__main__":
    run()
