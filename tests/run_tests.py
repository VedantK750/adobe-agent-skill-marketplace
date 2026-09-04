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
