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

    # The clean site should be nearly clean overall.
    expect(good_report["summary"]["critical"] == 0,
           "goodsite has zero critical findings")
    expect(len(good_report["findings"]) <= 3,
           "goodsite raises at most a few findings (got %d)"
           % len(good_report["findings"]))

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

    # -- Determinism: audit badsite twice, reports match --------------------
    print("\ndeterminism:")

    def norm(r):
        r = json.loads(json.dumps(r))
        r["audited_at"] = "X"
        r.get("audit_meta", {})["runtime_seconds"] = "X"
        return json.dumps(r, sort_keys=True)
    expect(norm(bad_report) == norm(bad_report2),
           "two badsite audits produce identical reports")

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
