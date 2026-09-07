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
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

    # -- Unreachable-origin regression unit ---------------------------------
    # A host that answers nothing (DNS failure, refused connection, bot filter
    # dropping non-browser agents) used to be misdiagnosed: the robots and
    # sitemap checks each reported their own symptom ("No robots.txt served",
    # "No usable XML sitemap"), asserting facts about markup that was never
    # observed. The correct behaviour is one blocking finding naming the true
    # root cause, with the response-dependent checks recording `inconclusive`.
    print("\nunreachable-origin regression unit:")

    def run_acquisition(snapshot):
        wd = os.path.join(WORK, "unit-acc")
        if os.path.exists(wd):
            _sh.rmtree(wd)
        os.makedirs(wd)
        with open(os.path.join(wd, "snapshot.json"), "w") as fh:
            json.dump(snapshot, fh)
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "skills", "site-acquisition",
                                          "scripts", "analyze.py"),
             "--workdir", wd], capture_output=True)
        with open(os.path.join(wd, "fragments",
                               "site-acquisition.json")) as fh:
            frag = json.load(fh)
        _sh.rmtree(wd, ignore_errors=True)
        return frag

    dead_page = {
        "url": "https://dead.example.com/", "final_url": "https://dead.example.com/",
        "status": None, "error": "ConnectionError: name resolution failed",
        "raw_html": "", "redirect_chain": [], "headers": {}, "page_type": "other",
    }
    snap_dead = {
        "site": "dead.example.com", "base_url": "https://dead.example.com/",
        "audited_at": "2026-01-01T00:00:00Z", "site_type": "unknown",
        "render_mode": "static-only", "render_status": "disabled-by-flag",
        "robots": {"url": "https://dead.example.com/robots.txt",
                   "present": False, "status": "ConnectionError"},
        "sitemap": {"found": False, "url_count": 0, "checked": [], "errors": []},
        "sitemap_urls": [], "pages": [dead_page],
    }
    frag_dead = run_acquisition(snap_dead)
    dead_fire = {x["check_id"] for x in frag_dead["findings"]}
    dead_unknown = {x["check_id"] for x in frag_dead["inconclusive"]}
    expect("ACC-NO-RESPONSE" in dead_fire,
           "ACC-NO-RESPONSE fires when the origin returns no HTTP response")
    expect(any(x["check_id"] == "ACC-NO-RESPONSE" and x["impact"] == "blocking"
               for x in frag_dead["findings"]),
           "ACC-NO-RESPONSE carries blocking impact (composes to critical)")
    expect("ACC-NO-ROBOTS" not in dead_fire
           and "ACC-NO-ROBOTS" in dead_unknown,
           "ACC-NO-ROBOTS is inconclusive, not a finding, on a dead origin")
    expect("ACC-NO-SITEMAP" not in dead_fire
           and "ACC-NO-SITEMAP" in dead_unknown,
           "ACC-NO-SITEMAP is inconclusive, not a finding, on a dead origin")

    # The converse: a live origin that genuinely serves no robots.txt must
    # still report it. Suppressing the symptom must be conditional on the
    # transport failure, not a blanket softening of the check.
    live_page = dict(dead_page, status=200, error=None,
                     raw_html="<html><body><p>Hello.</p></body></html>")
    snap_live = dict(snap_dead, pages=[live_page])
    frag_live = run_acquisition(snap_live)
    live_fire = {x["check_id"] for x in frag_live["findings"]}
    expect("ACC-NO-RESPONSE" not in live_fire,
           "ACC-NO-RESPONSE stays silent when the origin does respond")
    expect("ACC-NO-ROBOTS" in live_fire,
           "ACC-NO-ROBOTS still fires on a live origin serving no robots.txt")
    expect("ACC-NO-SITEMAP" in live_fire,
           "ACC-NO-SITEMAP still fires on a live origin with no sitemap")

    # -- Small-sample gate --------------------------------------------------
    # Found by running the live corpus: an ungated audit of a one-page crawl
    # (a placeholder page, or a site whose bot filter serves the home page and
    # refuses the rest) produced nine to twelve findings, several `high`, all of
    # them site-wide absence claims -- "no structured data anywhere", "every
    # page is a dead end" -- generalised from a single page. A claim about the
    # site needs a sample big enough to be about the site.
    print("\nsmall-sample gate:")
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import auditlib as A

    def content_page(url, extra=None):
        p = {
            "url": url, "final_url": url, "status": 200,
            "raw_html": "<html><body><main><h1>Title</h1>"
                        "<p>Some body copy about the topic.</p></main></body></html>",
            "text": "Title Some body copy about the topic.",
            "body_text": "Title Some body copy about the topic.",
            "headings": [{"level": 1, "text": "Title", "id": None}],
            "images": [], "meta_robots": None, "headers": {}, "canonical": None,
            "page_type": "article", "soft_404": False, "internal_links": 1,
            "outbound_links": [], "jsonld_raw": [], "title": "Title",
            "redirect_chain": [], "bytes": 900, "elapsed_ms": 80,
            "viewport": "width=device-width", "h1": ["Title"],
        }
        p.update(extra or {})
        return p

    def snap_with(n):
        return {
            "site": "small.example.com", "base_url": "https://small.example.com/",
            "audited_at": "2026-01-01T00:00:00Z", "site_type": "publisher",
            "render_mode": "static-only", "render_status": "disabled-by-flag",
            "robots": {"url": "https://small.example.com/robots.txt",
                       "present": True, "status": 200, "ai_agents_blocked": [],
                       "blanket_disallow": False, "sitemaps": []},
            "sitemap": {"found": True, "url_count": n, "checked": [],
                        "errors": [], "lastmod": {}},
            "sitemap_urls": [],
            "pages": [content_page("https://small.example.com/p%d" % i)
                      for i in range(n)],
            "crawl": {"pages_crawled": n, "runtime_seconds": 1.0},
        }

    def fired_across_skills(snapshot):
        wd = os.path.join(WORK, "unit-small")
        if os.path.exists(wd):
            _sh.rmtree(wd)
        os.makedirs(wd)
        with open(os.path.join(wd, "snapshot.json"), "w") as fh:
            json.dump(snapshot, fh)
        for sk in ("site-acquisition", "machine-readability", "structured-data",
                   "answer-extractability", "entity-corroboration",
                   "freshness-provenance", "engagement-audit"):
            subprocess.run(
                [sys.executable,
                 os.path.join(ROOT, "skills", sk, "scripts", "analyze.py"),
                 "--workdir", wd], capture_output=True)
        fired = set()
        for name in os.listdir(os.path.join(wd, "fragments")):
            with open(os.path.join(wd, "fragments", name)) as fh:
                fired |= {x["check_id"] for x in json.load(fh)["findings"]}
        _sh.rmtree(wd, ignore_errors=True)
        return fired

    one_page = fired_across_skills(snap_with(1))
    leaked = sorted(one_page - A.SMALL_SAMPLE_EXEMPT)
    expect(not leaked,
           "a one-page crawl asserts no site-wide claim (leaked: %s)" % leaked)

    # The converse must still hold, or the gate is just a mute button: the same
    # content at a sample the claim can actually be made from still reports.
    many_page = fired_across_skills(snap_with(8))
    expect(len(many_page) > len(one_page),
           "the same content at 8 pages still produces findings (%d vs %d)"
           % (len(many_page), len(one_page)))
    expect("SD-ABSENT" in many_page,
           "SD-ABSENT fires at 8 pages (gate suppresses small samples, not the "
           "check)")

    # An id misspelt in SMALL_SAMPLE_EXEMPT silently re-gates the check it was
    # meant to exempt, and nothing else would notice. Tie the list to the source.
    source_ids = set()
    id_pat = re.compile(r'\.(?:finding|na|unknown)\(\s*\n?\s*"([A-Z][A-Z0-9-]+)"')
    for sk in ("site-acquisition", "machine-readability", "structured-data",
               "answer-extractability", "entity-corroboration",
               "freshness-provenance", "engagement-audit"):
        with open(os.path.join(ROOT, "skills", sk, "scripts",
                               "analyze.py")) as fh:
            source_ids |= set(id_pat.findall(fh.read()))
    unknown_ids = sorted(A.SMALL_SAMPLE_EXEMPT - source_ids)
    expect(not unknown_ids,
           "every id in SMALL_SAMPLE_EXEMPT exists in the source "
           "(unknown: %s)" % unknown_ids)

    # -- Link extraction ----------------------------------------------------
    # Found on a live corpus run: a hand-written blog with 209 anchors on its
    # home page yielded 0 links, because the extractor required quoted href
    # values. Unquoted attributes are valid HTML5 and common in hand-written and
    # generated markup. The failure was invisible in the worst way -- the crawl
    # ended after the seed page, so every check ran on a one-page sample and the
    # report looked thin rather than broken.
    print("\nlink extraction:")
    sys.path.insert(0, os.path.join(ROOT, "skills", "site-acquisition",
                                    "scripts"))
    import crawl as C

    markup = (
        '<html><body>'
        '<a href=/unquoted>unquoted</a>'
        "<a href='/single'>single quoted</a>"
        '<a href="/double">double quoted</a>'
        '<a\n  href="/newline-in-tag">split across lines</a>'
        '<a href="/spaced" >trailing space in tag</a>'
        '<a href="mailto:x@example.com">mail</a>'
        '<a href="#frag">fragment</a>'
        '<a href="javascript:void(0)">js</a>'
        '<a href="/logo.png">an image, skipped by extension</a>'
        '<a href="https://other.example.org/x">external</a>'
        '</body></html>')
    found = C.links_from(markup, "https://site.example.com/")
    internal = [u for u in found if C.same_site(u, "https://site.example.com/")]

    expect(any(u.endswith("/unquoted") for u in found),
           "an unquoted href is extracted (regression: valid HTML5)")
    expect(any(u.endswith("/single") for u in found)
           and any(u.endswith("/double") for u in found),
           "single- and double-quoted hrefs are both extracted")
    expect(any(u.endswith("/newline-in-tag") for u in found),
           "an href on a continuation line inside the tag is extracted")
    # The five internal document links; /logo.png is dropped by extension and
    # the mailto/fragment/javascript hrefs never become URLs at all.
    expect(len(internal) == 5,
           "exactly the 5 internal document links are kept (got %d: %s)"
           % (len(internal), internal))
    expect(not any("mailto" in u or "javascript" in u or "#frag" in u
                   for u in found),
           "mailto, javascript and fragment hrefs are excluded")
    expect(not any(u.endswith(".png") for u in found),
           "non-document extensions are excluded")
    expect(any("other.example.org" in u for u in found),
           "external links are still returned (the caller partitions them)")

    # -- D2C false-positive regressions -------------------------------------
    # All three found by running the live suite over a corpus weighted toward
    # direct-to-consumer storefronts. Each fired on a pattern that is standard
    # on commerce sites and that contradicts the check's own stated mechanism.
    print("\nD2C false-positive regressions:")
    # Every skill exposes a module named `analyze`, so a plain import would
    # resolve by sys.path order rather than by which skill is meant. Load each
    # from its own file path instead.
    import importlib.util as _ilu

    def load(skill, name):
        path = os.path.join(ROOT, "skills", skill, "scripts", "analyze.py")
        spec = _ilu.spec_from_file_location(name, path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    mr = load("machine-readability", "mr_analyze")
    en = load("engagement-audit", "en_analyze")

    # (a) Autoplay: the mechanism is unrequested SOUND. Muted autoplay is the
    # standard hero-video pattern and is a precondition of autoplay working at
    # all in current browsers. On a live corpus, 17 of 17 autoplaying elements
    # were muted, so every firing was a false positive.
    muted_html = ('<video autoplay muted loop playsinline><source src="a.mp4">'
                  '</video>')
    muted_reordered = '<video class="hero" muted autoplay playsinline></video>'
    loud_html = '<video autoplay loop><source src="a.mp4"></video>'
    loud_audio = '<audio autoplay src="x.mp3"></audio>'
    expect(en.unmuted_autoplay(muted_html) == [],
           "muted autoplay video is NOT reported as unrequested sound")
    expect(en.unmuted_autoplay(muted_reordered) == [],
           "muted is detected when written before autoplay in the tag")
    expect(len(en.unmuted_autoplay(loud_html)) == 1,
           "genuinely unmuted autoplay video IS still reported")
    expect(len(en.unmuted_autoplay(loud_audio)) == 1,
           "unmuted autoplay audio IS still reported")

    # (b) Iframes: a tag-manager pixel or chat launcher carries no substance.
    # 17 of 25 frames that tripped the old check were googletagmanager.com.
    noise = ["https://www.googletagmanager.com/ns.html?id=GTM-XYZ",
             "https://widget.intercom.io/frame",
             "https://cdn.cookielaw.org/banner.html",
             "https://js.stripe.com/v3/elements-inner-card.html",
             "about:blank", ""]
    real = ["https://www.youtube.com/embed/abc123", "/embedded-guide.html"]
    expect(mr.content_bearing_iframes(noise) == [],
           "tag-manager, chat, consent and payment frames are not counted as "
           "trapped content")
    expect(len(mr.content_bearing_iframes(noise + real)) == 2,
           "a genuine embed and a same-origin frame ARE still counted")

    # (c) CTA: `body_text` strips <form> and <header>, which is exactly where a
    # storefront keeps "Add to cart". Matching the full visible text fixes it.
    store_html = (
        '<html><body><header><a href="/shop">Shop now</a></header>'
        '<main><h1>Merino Runner</h1><p>A shoe made from wool.</p></main>'
        '<form action="/cart/add"><button>Add to cart</button></form>'
        '</body></html>')
    expect(en.CTA_RE.search(A.visible_text(store_html)) is not None,
           "a storefront CTA is found in the full visible text")
    expect(en.CTA_RE.search(A.main_text(store_html)) is None,
           "and is genuinely absent from the chrome-stripped body text "
           "(this is what caused the false positive)")

    # -- Wall-clock budget and error hygiene --------------------------------
    # Found on the 785-site run: four audits blew the brief's 5-minute ceiling
    # because the budget was checked only *between* fetches, so a crawl could
    # pass the check at 179s and then spend another 38s on one request's
    # timeout-and-retry tail. And ACC-NO-RESPONSE evidence read "ConnectionError:
    # None", because several urllib3 exceptions stringify to "None".
    print("\nwall-clock budget and error hygiene:")
    import time as _t

    now = _t.time()
    # Plenty of time left: full timeout, full retries.
    to, rt = C.budgeted(now + 600)
    expect(to == C.DEFAULT_TIMEOUT and rt == C.FETCH_RETRIES,
           "a fetch with ample budget keeps its full timeout and retries")
    # Some time left, but not enough for the retry tail: retries drop first.
    to, rt = C.budgeted(now + 20, timeout=12, retries=2)
    expect(to == 12 and rt < 2,
           "retries are dropped before the timeout when the budget is tight "
           "(got timeout=%s retries=%s)" % (to, rt))
    # Less than one timeout left: the timeout itself shrinks to fit.
    to, rt = C.budgeted(now + 3, timeout=12, retries=2)
    expect(to <= 3.01 and rt == 0,
           "the timeout shrinks to the time remaining (got %s, %s)" % (to, rt))
    # Budget already gone: return immediately rather than starting a long wait.
    to, rt = C.budgeted(now - 5, timeout=12, retries=2)
    expect(to <= 0.5 and rt == 0,
           "an exhausted budget yields a near-zero timeout and no retries")

    class _Silent(Exception):
        def __str__(self):
            return "None"

    expect(C.describe_exception(_Silent()) == "_Silent",
           "an exception stringifying to 'None' is reported by type alone")
    expect(C.describe_exception(None) == "no response",
           "a missing exception reads as 'no response', not 'None'")
    expect("None" not in C.describe_exception(ValueError("")),
           "an empty exception message never renders as literal None")
    long_exc = C.describe_exception(ValueError("x" * 900))
    expect(len(long_exc) < 340,
           "an overlong transport error is truncated for the reader (%d chars)"
           % len(long_exc))

    # -- Storefront page-type classification --------------------------------
    # Found on the D2C corpus: /collections/ pages were classified `product`,
    # because a Shopify grid shows a price per tile and a quick-add control on
    # every tile, and the content heuristic read that as a product detail page.
    # The structured-data check then reported "no Product schema" on a listing,
    # which correctly has none -- a listing of forty items is an ItemList. As
    # /collections/ is the Shopify default path, this hit a large share of the
    # exact sites this audit is most often pointed at.
    print("\nstorefront page-type classification:")
    sys.path.insert(0, os.path.join(ROOT, "skills", "site-acquisition",
                                    "scripts"))
    from classify import classify_page

    def store_page(url, text, links, h2s):
        return {
            "url": url, "final_url": url, "status": 200,
            "raw_html": "<html></html>", "text": text, "body_text": text,
            "headings": [{"level": 2, "text": "S%d" % i, "id": None}
                         for i in range(h2s)],
            "internal_links": links, "images": [], "headers": {},
            "jsonld_raw": [], "title": "t",
        }

    grid_text = ("Add to cart $49.00 Add to cart $59.00 Add to cart $79.00 "
                 "Add to cart $89.00 Sort by Filter")
    detail_text = ("The Pac Kit is a cabin suitcase. $199.00 Add to cart. "
                   "Free shipping and a five year warranty.")
    base = "https://shop.example.com/"

    expect(classify_page(store_page("https://shop.example.com/collections/all",
                                    grid_text, 60, 2), base) == "category",
           "a /collections/ grid with quick-add tiles is a category page")
    expect(classify_page(store_page("https://shop.example.com/collections/sale",
                                    grid_text, 35, 8), base) == "category",
           "a /collections/ page stays a category even with cart controls")
    expect(classify_page(store_page("https://shop.example.com/products/pac-kit",
                                    detail_text, 18, 3), base) == "product",
           "a /products/ detail page is still classified product")
    expect(classify_page(store_page("https://shop.example.com/products/index",
                                    grid_text.replace("Add to cart", "From"),
                                    60, 2), base) == "category",
           "a /products/ URL that is really a dense listing is a category")

    # -- Site type survives the page-type fix -------------------------------
    # The page-level and site-level classifiers are coupled, and the coupling is
    # easy to break silently. Correcting classify_page to stop calling Shopify
    # collection pages `product` collapsed `product_share`, and 212 storefronts
    # fell out of `ecommerce` into `unknown` on a 785-site run. Nothing failed;
    # site type merely gates whole checks, so it quietly changed what ran.
    # Assert both directions: a collections-led storefront is still commerce,
    # and a blog's /category/ archives are still not.
    print("\nsite type vs page type coupling:")
    from classify import classify_site

    shop_pages = [store_page(base + "collections/c%d" % i, grid_text, 50, 3)
                  for i in range(6)]
    shop_pages.append(store_page(base, grid_text, 40, 3))
    for pg in shop_pages:
        pg["page_type"] = classify_page(pg, base)
    expect(classify_site(shop_pages) == "ecommerce",
           "a storefront sampled mostly at /collections/ is still ecommerce "
           "(got %s)" % classify_site(shop_pages))

    blog_text = ("Posted on 12 March. A long read about migrating a database "
                 "without downtime, with notes on replication lag and cutover.")
    blog_pages = [store_page("https://blog.example.com/category/eng/p%d" % i,
                             blog_text, 30, 4) for i in range(6)]
    blog_pages.append(store_page("https://blog.example.com/", blog_text, 30, 4))
    for pg in blog_pages:
        pg["page_type"] = classify_page(pg, "https://blog.example.com/")
    expect(classify_site(blog_pages) != "ecommerce",
           "a blog's /category/ archives do NOT make it a storefront (got %s)"
           % classify_site(blog_pages))

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
