#!/usr/bin/env python3
"""Large-corpus live-site test suite for the brand-ai-readiness-audit marketplace.

`tests/run_tests.py` proves the checks are *correct* against fixtures whose
ground truth we control. It cannot prove they *generalise*, because a fixture is
by definition a site we designed. This suite closes that gap: it audits a broad
corpus of real, unseen sites and asserts the invariants that must hold on every
one of them, whatever the site turns out to contain.

Two kinds of evidence come out of it.

INVARIANTS (per site, hard pass/fail). None of these reference any specific
site's content, so the suite never becomes fitted to its corpus:

  I1  a schema-valid report is produced at all
  I2  the audit finishes inside the brief's 5-minute budget
  I3  every declared analysis skill wrote a fragment (no analyser crashed)
  I4  summary counts, id ordering and id uniqueness are internally consistent
  I5  every finding carries evidence, a mechanism, and an actionable fix
  I6  prevalence is a coherent ratio (affected <= sampled)
  I7  evidence is grounded: every affected_url was actually fetched
  I8  `critical` is reserved for the pipeline-breaking blockers
  I9  no unrendered format placeholders leak into reader-facing text
  I10 checks account for their own silence (not_applicable / inconclusive)
  I11 no check reports the same defect twice
  I12 the report stays within a readable size

AGGREGATE DIAGNOSTICS (across the corpus, advisory). These are what actually
surface false positives and dead checks, and no single-site run can show them:

  * firing rate per check -- a check that fires on nearly every site is either
    trivially true or a false-positive generator; both are detection defects
  * never-observed checks -- check ids present in the source but never reached
    on any site are untested surface area
  * severity distribution -- a corpus of mainstream, competently built sites
    that comes back mostly `critical` is evidence of severity inflation

Usage:
  python3 tests/live_suite.py                      # full corpus
  python3 tests/live_suite.py --limit 8            # smoke run
  python3 tests/live_suite.py --workers 8 --max-pages 15
  python3 tests/live_suite.py --urls https://a.com https://b.com
  python3 tests/live_suite.py --keep-artifacts     # retain snapshots + reports

Exit code is non-zero if any invariant fails on any site. Network failures are
recorded as site outcomes, not as suite failures: an unreachable site is a
legitimate audit result (ACC-NO-RESPONSE), not a bug in the marketplace.
"""

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse as up
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_AUDIT = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts",
                         "run_audit.py")
VALIDATE = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts",
                        "validate_report.py")
MANIFEST = os.path.join(ROOT, "marketplace.json")
CORPUS = os.path.join(ROOT, "tests", "corpus.txt")
RESULTS = os.path.join(ROOT, "tests", "live-results")

# The brief's ceiling. We assert against the real limit rather than a softer
# internal one, because that is the number the submission is judged on.
RUNTIME_BUDGET_SECONDS = 300

# `critical` means the retrieval pipeline is broken outright: the origin does
# not answer, the crawler is refused entry, or the page carries no readable
# content once inside. Everything else degrades or weakens a signal and caps at
# `high`, however widespread. Kept in sync with severity-model.md; the suite
# fails if any other check reaches critical on a real site.
CRITICAL_ALLOWED = {
    "ACC-NO-RESPONSE",
    "ACC-AI-CRAWLER-BLOCKED",
    "ACC-BLANKET-DISALLOW",
    "ACC-SNIPPET-SUPPRESSED",
    "MR-EMPTY-SHELL",
    "MR-RENDER-GAP",
}

# Unrendered format artefacts. If any of these reach a finding's reader-facing
# text, a format string went unfilled and the report shows a bug to the user.
PLACEHOLDER_PATTERNS = [
    (re.compile(r"%[sdrf]\b"), "unfilled %-format"),
    (re.compile(r"\{\w*\}"), "unfilled brace format"),
    (re.compile(r"\bNone\b"), "literal None"),
    (re.compile(r"\bnan\b"), "literal nan"),
    (re.compile(r"\b0/0\b"), "zero-denominator ratio"),
]

# A report longer than this is not actionable by a human, which is the point of
# the output-design criterion. Well past anything a sane site should produce.
MAX_FINDINGS = 40


# ------------------------------------------------------------------ corpus

def load_corpus(path):
    urls = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def declared_skills():
    """Analysis skills the manifest declares (everything but the entrypoint)."""
    with open(MANIFEST, "r", encoding="utf-8") as fh:
        mani = json.load(fh)
    return [s["id"] for s in mani.get("skills", []) if not s.get("entrypoint")]


def source_check_ids():
    """Every check id that appears in the marketplace source.

    Extracted statically from the first string argument of each f.finding /
    f.na / f.unknown call. Compared against the ids actually observed across the
    corpus, this measures how much of the detection surface the run exercised --
    a check that never appears on any of ~45 varied sites is either dead or so
    narrow it will never generalise, and either way it should be known about.
    """
    ids = set()
    pat = re.compile(r'\.(?:finding|na|unknown)\(\s*\n?\s*"([A-Z][A-Z0-9-]+)"')
    for skill in declared_skills():
        script = os.path.join(ROOT, "skills", skill, "scripts", "analyze.py")
        if not os.path.exists(script):
            continue
        with open(script, "r", encoding="utf-8") as fh:
            ids.update(pat.findall(fh.read()))
    return ids


# ------------------------------------------------------------------ per-site

def audit_site(url, workdir, max_pages, timeout):
    """Run the entrypoint against one URL. Returns (report|None, meta)."""
    if os.path.exists(workdir):
        shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)

    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, RUN_AUDIT, "--url", url, "--workdir", workdir,
             "--max-pages", str(max_pages), "--no-render"],
            capture_output=True, text=True, timeout=timeout)
        rc, stderr = proc.returncode, proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired:
        rc, stderr, timed_out = -1, "hard timeout after %ds" % timeout, True

    elapsed = time.time() - started
    meta = {"url": url, "runtime_seconds": round(elapsed, 1),
            "returncode": rc, "timed_out": timed_out,
            "stderr_tail": (stderr or "")[-1200:]}

    report_path = os.path.join(workdir, "audit-report.json")
    if not os.path.exists(report_path):
        return None, meta
    try:
        with open(report_path, "r", encoding="utf-8") as fh:
            return json.load(fh), meta
    except Exception as exc:
        meta["parse_error"] = "%s: %s" % (type(exc).__name__, exc)
        return None, meta


def crawled_urls(workdir):
    """Every URL the crawler actually touched, for the groundedness check."""
    snap_path = os.path.join(workdir, "snapshot.json")
    if not os.path.exists(snap_path):
        return set()
    with open(snap_path, "r", encoding="utf-8") as fh:
        snap = json.load(fh)
    seen = set()
    for p in snap.get("pages", []):
        for key in ("url", "final_url"):
            if p.get(key):
                seen.add(p[key].rstrip("/"))
    robots = (snap.get("robots") or {}).get("url")
    if robots:
        seen.add(robots.rstrip("/"))
    if snap.get("base_url"):
        seen.add(snap["base_url"].rstrip("/"))
    for sm in (snap.get("sitemap") or {}).get("checked") or []:
        seen.add(sm.rstrip("/"))
    return seen


def text_fields(finding):
    """Reader-facing strings of a finding, for the placeholder scan."""
    action = finding.get("suggested_action") or {}
    out = [finding.get("title"), finding.get("evidence"),
           finding.get("mechanism"), action.get("summary"),
           action.get("expected_impact"), action.get("verification")]
    out.extend(action.get("steps") or [])
    return [s for s in out if isinstance(s, str)]


def check_invariants(url, report, meta, workdir, expected_skills):
    """Return a list of invariant-violation strings. Empty means the site passed."""
    fails = []

    def bad(code, msg):
        fails.append("%s: %s" % (code, msg))

    # I2 -- runtime budget.
    if meta["timed_out"]:
        bad("I2", "hard timeout after %ds" % RUNTIME_BUDGET_SECONDS)
    elif meta["runtime_seconds"] > RUNTIME_BUDGET_SECONDS:
        bad("I2", "runtime %.1fs exceeds the %ds budget"
            % (meta["runtime_seconds"], RUNTIME_BUDGET_SECONDS))

    # I1 -- a report exists. Everything below needs one.
    if report is None:
        bad("I1", "no audit-report.json produced (rc=%s) %s"
            % (meta["returncode"], meta["stderr_tail"][-300:]))
        return fails

    proc = subprocess.run([sys.executable, VALIDATE, "--report",
                           os.path.join(workdir, "audit-report.json")],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        bad("I1", "schema validation failed: %s"
            % (proc.stderr or "").strip()[:400])

    # I3 -- every declared analyser ran to completion.
    frag_dir = os.path.join(workdir, "fragments")
    written = set()
    if os.path.isdir(frag_dir):
        written = {n[:-5] for n in os.listdir(frag_dir) if n.endswith(".json")}
    missing = sorted(set(expected_skills) - written)
    if missing:
        bad("I3", "analyser(s) produced no fragment (crashed): %s"
            % ", ".join(missing))

    findings = report.get("findings", [])
    summary = report.get("summary", {})

    # I4 -- internal consistency of the summary and ids.
    if summary.get("total_findings") != len(findings):
        bad("I4", "summary.total_findings=%s but %d findings present"
            % (summary.get("total_findings"), len(findings)))
    for sev in ("critical", "high", "medium", "low"):
        actual = sum(1 for f in findings if f.get("severity") == sev)
        if sev in summary and summary[sev] != actual:
            bad("I4", "summary.%s=%s but %d findings have that severity"
                % (sev, summary[sev], actual))
    ids = [f.get("id") for f in findings]
    if ids != sorted(ids):
        bad("I4", "finding ids are not in ascending order")
    if len(set(ids)) != len(ids):
        bad("I4", "duplicate finding ids: %s"
            % [i for i, c in Counter(ids).items() if c > 1])

    # I12 -- report stays readable.
    if len(findings) > MAX_FINDINGS:
        bad("I12", "%d findings exceeds the %d-finding readability ceiling"
            % (len(findings), MAX_FINDINGS))

    known = crawled_urls(workdir)
    seen_checks = []

    for f in findings:
        cid = f.get("check_id", f.get("id", "?"))
        seen_checks.append(cid)

        # I5 -- every finding is evidenced and actionable.
        action = f.get("suggested_action") or {}
        if not (f.get("evidence") or "").strip():
            bad("I5", "%s has empty evidence" % cid)
        if not (f.get("mechanism") or "").strip():
            bad("I5", "%s has empty mechanism" % cid)
        if not (action.get("summary") or "").strip():
            bad("I5", "%s has no suggested_action.summary" % cid)
        if not (action.get("steps") or []):
            bad("I5", "%s has no remediation steps" % cid)
        if action.get("priority") != f.get("severity"):
            bad("I5", "%s action priority %r != severity %r"
                % (cid, action.get("priority"), f.get("severity")))

        # I6 -- prevalence is a coherent ratio.
        prev = f.get("prevalence") or {}
        aff, samp = prev.get("affected", 0), prev.get("sampled", 0)
        if isinstance(aff, int) and isinstance(samp, int) and aff > samp:
            bad("I6", "%s reports affected=%d > sampled=%d" % (cid, aff, samp))

        # I7 -- evidence groundedness. Every URL a finding blames must be one
        # the crawler actually fetched. This is the check that would catch a
        # finding citing a page that was never seen.
        for u in f.get("affected_urls") or []:
            if u and u.rstrip("/") not in known:
                bad("I7", "%s cites %s, which was never fetched" % (cid, u))

        # I8 -- critical is reserved for pipeline blockers.
        if f.get("severity") == "critical" and cid not in CRITICAL_ALLOWED:
            bad("I8", "%s reached `critical` but is not a pipeline blocker" % cid)

        # I9 -- no unrendered format artefacts in reader-facing text.
        for s in text_fields(f):
            for pat, label in PLACEHOLDER_PATTERNS:
                if pat.search(s):
                    bad("I9", "%s leaks %s in: %r" % (cid, label, s[:110]))
                    break

    # I11 -- one defect, one finding.
    dupes = [c for c, n in Counter(seen_checks).items() if n > 1]
    if dupes:
        bad("I11", "the same check reported more than once: %s" % dupes)

    # I10 -- checks account for their silence. Only meaningful where the site
    # actually responded; an unreachable host legitimately has little to say.
    unreachable = any(f.get("check_id") == "ACC-NO-RESPONSE" for f in findings)
    if not unreachable and not report.get("not_applicable"):
        bad("I10", "no not_applicable records: checks did not explain their "
                   "silence")

    return fails


def run_one(url, outdir, max_pages, keep):
    slug = re.sub(r"[^a-z0-9._-]+", "-",
                  (up.urlparse(url).netloc + up.urlparse(url).path).lower()
                  ).strip("-")[:70] or "site"
    workdir = os.path.join(outdir, "work", slug)
    expected = declared_skills()

    report, meta = audit_site(url, workdir, max_pages,
                              timeout=RUNTIME_BUDGET_SECONDS)
    fails = check_invariants(url, report, meta, workdir, expected)

    row = {
        "url": url,
        "slug": slug,
        "runtime_seconds": meta["runtime_seconds"],
        "invariant_failures": fails,
        "passed": not fails,
    }
    if report:
        row.update({
            "site": report.get("site"),
            "site_type": (report.get("audit_meta") or {}).get("site_type"),
            "pages_crawled": (report.get("audit_meta") or {}).get("pages_crawled"),
            "page_types_seen": (report.get("audit_meta") or {}).get(
                "page_types_seen", []),
            "summary": report.get("summary"),
            "findings": [{"check_id": f.get("check_id"),
                          "severity": f.get("severity"),
                          "category": f.get("category"),
                          "confidence": f.get("confidence")}
                         for f in report.get("findings", [])],
            "not_applicable": [x["check_id"] for x in
                               report.get("not_applicable", [])],
            "inconclusive": [x["check_id"] for x in
                             report.get("inconclusive", [])],
        })
        # The report is always kept: it is a few KB and it is the only way to
        # investigate an aggregate signal after the fact. The snapshot is what
        # costs disk (megabytes of raw HTML per site, which at corpus scale runs
        # to gigabytes), so that is what --keep-artifacts controls.
        shutil.copy(os.path.join(workdir, "audit-report.json"),
                    os.path.join(outdir, "reports", slug + ".json"))
    else:
        row["error"] = meta["stderr_tail"][-500:]

    if not keep:
        shutil.rmtree(workdir, ignore_errors=True)
    return row


# ------------------------------------------------------------------ aggregate

def aggregate(rows, all_check_ids):
    """Cross-site diagnostics: the false-positive and coverage lens."""
    audited = [r for r in rows if r.get("summary")]
    n = len(audited)

    fired = Counter()
    fired_sites = defaultdict(list)
    observed = set()
    sev_totals = Counter()

    for r in audited:
        for cid in {f["check_id"] for f in r["findings"]}:
            fired[cid] += 1
            fired_sites[cid].append(r["site"] or r["url"])
        for f in r["findings"]:
            sev_totals[f["severity"]] += 1
        observed.update(f["check_id"] for f in r["findings"])
        observed.update(r.get("not_applicable", []))
        observed.update(r.get("inconclusive", []))

    rates = {cid: round(100.0 * c / n, 1) for cid, c in fired.items()} if n else {}

    # A check firing on nearly every site is a detection defect either way: if
    # the finding is real everywhere it is not diagnostic, and if it is not, it
    # is a false positive with wide reach. Flag it for review; do not fail on
    # it, because a genuinely near-universal web defect does exist.
    ubiquitous = sorted([c for c, r in rates.items() if r >= 90.0],
                        key=lambda c: -rates[c])
    # A check that never fired on ~45 varied sites is untested surface area.
    never_fired = sorted(set(all_check_ids) - set(fired))
    # Worse: a check id in the source that was never reached in ANY bucket --
    # not as a finding, not as not_applicable, not as inconclusive.
    never_reached = sorted(set(all_check_ids) - observed)

    findings_per_site = sorted(r["summary"]["total_findings"] for r in audited)
    median = (findings_per_site[len(findings_per_site) // 2]
              if findings_per_site else 0)

    # A cluster of "the site did not respond" is far more often a fact about the
    # machine running the suite than about the sites. At high concurrency the
    # local link, resolver or an upstream rate limiter saturates, and unrelated
    # hosts start timing out together -- on one 785-site run at 20 workers, 112
    # sites reported ACC-NO-RESPONSE in a contiguous alphabetical block, which
    # is the giveaway: the corpus is processed in order, so a run of adjacent
    # failures is a time window, not a property of those brands. Say so, loudly,
    # rather than letting a harness artefact be read as 112 broken sites.
    no_response = [r for r in audited
                   if any(f["check_id"] == "ACC-NO-RESPONSE"
                          for f in r["findings"])]
    nr_share = (100.0 * len(no_response) / n) if n else 0.0

    # Crawl depth is the confounder behind almost every misleading aggregate.
    # Nearly all findings are drawn from a page sample, and the small-sample gate
    # holds site-wide claims silent below three content pages -- so if depth
    # collapses, firing rates fall across the board and it looks exactly like a
    # detection improvement. It also moves site type: with only a home page
    # sampled there is no product or category evidence, so storefronts read as
    # `unknown`.
    #
    # This is not theoretical. Running this corpus four times in a few hours
    # drew rate limiting from shared commerce CDNs -- robots.txt answering 403,
    # 429, 420 -- and median depth fell from 10 pages to 1. The resulting
    # distribution shift was very nearly diagnosed as a classifier regression
    # and "fixed". Report depth alongside every rate so the comparison can be
    # thrown out rather than believed.
    depths = sorted((r.get("pages_crawled") or 0) for r in audited)
    depth_median = depths[len(depths) // 2] if depths else 0
    one_page_share = (100.0 * sum(1 for d in depths if d <= 1) / len(depths)
                      if depths else 0.0)

    return {
        "sites_attempted": len(rows),
        "sites_audited": n,
        "sites_passing_invariants": sum(1 for r in rows if r["passed"]),
        "runtime_seconds_max": max((r["runtime_seconds"] for r in rows),
                                   default=0),
        "runtime_seconds_mean": (round(sum(r["runtime_seconds"] for r in rows)
                                       / len(rows), 1) if rows else 0),
        "findings_per_site": {
            "min": findings_per_site[0] if findings_per_site else 0,
            "median": median,
            "max": findings_per_site[-1] if findings_per_site else 0,
        },
        "severity_totals": dict(sev_totals),
        "sites_with_a_critical": sum(1 for r in audited
                                     if r["summary"]["critical"] > 0),
        "check_firing_rate_pct": dict(sorted(rates.items(),
                                             key=lambda kv: -kv[1])),
        "checks_firing_on_90pct_or_more": ubiquitous,
        "checks_never_fired": never_fired,
        "checks_never_reached_in_any_bucket": never_reached,
        "check_ids_in_source": len(all_check_ids),
        "no_response_sites": len(no_response),
        "no_response_share_pct": round(nr_share, 1),
        "network_saturation_suspected": nr_share > 10.0,
        "pages_crawled_median": depth_median,
        "sites_with_one_page_pct": round(one_page_share, 1),
        # Only meaningful over a real sample. On a handful of sites a single
        # legitimately one-page site (a placeholder, a JS shell) swings the
        # share past any threshold, and a warning that cries wolf on every
        # smoke run is one nobody reads on the run that matters.
        "shallow_crawl_suspected": (len(depths) >= 20
                                    and (depth_median < 3
                                         or one_page_share > 35.0)),
    }


def write_markdown(path, agg, rows):
    L = ["# Live corpus audit — results", ""]
    L.append("Run: %s" % datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"))
    L.append("")
    L.append("| metric | value |")
    L.append("|---|---|")
    L.append("| sites attempted | %d |" % agg["sites_attempted"])
    L.append("| sites audited (report produced) | %d |" % agg["sites_audited"])
    L.append("| sites passing all invariants | %d / %d |"
             % (agg["sites_passing_invariants"], agg["sites_attempted"]))
    L.append("| slowest audit | %.1fs (budget %ds) |"
             % (agg["runtime_seconds_max"], RUNTIME_BUDGET_SECONDS))
    L.append("| mean audit runtime | %.1fs |" % agg["runtime_seconds_mean"])
    L.append("| median pages crawled | %d%s |"
             % (agg["pages_crawled_median"],
                " **(shallow — rates not comparable)**"
                if agg["shallow_crawl_suspected"] else ""))
    L.append("| sites yielding <=1 page | %.0f%% |"
             % agg["sites_with_one_page_pct"])
    L.append("| findings per site (min/median/max) | %d / %d / %d |"
             % (agg["findings_per_site"]["min"],
                agg["findings_per_site"]["median"],
                agg["findings_per_site"]["max"]))
    L.append("| sites with a critical finding | %d / %d |"
             % (agg["sites_with_a_critical"], agg["sites_audited"]))
    L.append("| check ids in source | %d |" % agg["check_ids_in_source"])
    L.append("")

    L.append("## Per-site results")
    L.append("")
    L.append("| site | type | pages | findings | C/H/M/L | runtime | invariants |")
    L.append("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: r["url"]):
        s = r.get("summary")
        if s:
            counts = "%d/%d/%d/%d" % (s["critical"], s["high"], s["medium"],
                                      s["low"])
            L.append("| %s | %s | %s | %d | %s | %.0fs | %s |" % (
                r.get("site") or r["url"], r.get("site_type", "-"),
                r.get("pages_crawled", "-"), s["total_findings"], counts,
                r["runtime_seconds"],
                "pass" if r["passed"] else "**FAIL (%d)**"
                % len(r["invariant_failures"])))
        else:
            L.append("| %s | - | - | - | - | %.0fs | **NO REPORT** |"
                     % (r["url"], r["runtime_seconds"]))
    L.append("")

    L.append("## Check firing rate across the corpus")
    L.append("")
    L.append("Share of audited sites on which each check fired. Near-100% is a "
             "review signal: a check that fires everywhere is not diagnostic. "
             "0% means the check was never exercised by this corpus.")
    L.append("")
    L.append("| check | fired on % of sites |")
    L.append("|---|---|")
    for cid, rate in agg["check_firing_rate_pct"].items():
        L.append("| %s | %.0f%% |" % (cid, rate))
    L.append("")

    if agg["checks_firing_on_90pct_or_more"]:
        L.append("### Review: fires on >=90% of sites")
        L.append("")
        for cid in agg["checks_firing_on_90pct_or_more"]:
            L.append("- `%s` (%.0f%%)" % (cid, agg["check_firing_rate_pct"][cid]))
        L.append("")

    if agg["checks_never_fired"]:
        L.append("### Never fired on this corpus")
        L.append("")
        L.append(", ".join("`%s`" % c for c in agg["checks_never_fired"]))
        L.append("")

    if agg["checks_never_reached_in_any_bucket"]:
        L.append("### Never reached in any bucket (untested surface area)")
        L.append("")
        L.append(", ".join("`%s`" % c
                           for c in agg["checks_never_reached_in_any_bucket"]))
        L.append("")

    failed = [r for r in rows if not r["passed"]]
    if failed:
        L.append("## Invariant failures")
        L.append("")
        for r in failed:
            L.append("### %s" % r["url"])
            for msg in r["invariant_failures"]:
                L.append("- %s" % msg)
            L.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--urls", nargs="*", help="Audit these URLs instead of the corpus.")
    ap.add_argument("--limit", type=int, default=0, help="Audit only the first N.")
    ap.add_argument("--workers", type=int, default=6,
                    help="Concurrent audits. Each targets a different host, so "
                         "this adds no load to any one site.")
    ap.add_argument("--max-pages", type=int, default=12,
                    help="Crawl cap per site. Lower than production on purpose: "
                         "the suite tests invariants, not crawl depth.")
    ap.add_argument("--keep-artifacts", action="store_true",
                    help="Keep each site's snapshot and report for inspection.")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    urls = args.urls or load_corpus(args.corpus)
    if args.limit:
        urls = urls[:args.limit]
    if not urls:
        raise SystemExit("no URLs to audit")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    outdir = args.outdir or os.path.join(RESULTS, stamp)
    os.makedirs(os.path.join(outdir, "reports"), exist_ok=True)
    os.makedirs(os.path.join(outdir, "work"), exist_ok=True)

    all_check_ids = source_check_ids()
    print("Live corpus suite: %d sites, %d workers, max %d pages/site"
          % (len(urls), args.workers, args.max_pages))
    print("%d check ids found in source. Results -> %s\n"
          % (len(all_check_ids), outdir))

    rows = []
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(run_one, u, outdir, args.max_pages,
                             args.keep_artifacts): u for u in urls}
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            url = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {"url": url, "slug": "?", "runtime_seconds": 0,
                       "passed": False,
                       "invariant_failures": ["HARNESS: %s: %s"
                                              % (type(exc).__name__, exc)]}
            rows.append(row)
            s = row.get("summary")
            status = "ok  " if row["passed"] else "FAIL"
            print("[%2d/%2d] %s %-42s %s  %4.0fs  %s" % (
                i, len(urls), status, (row.get("site") or url)[:42],
                ("%2d findings" % s["total_findings"]) if s else "  NO REPORT",
                row["runtime_seconds"],
                "" if row["passed"] else row["invariant_failures"][0][:90]))

    agg = aggregate(rows, all_check_ids)
    agg["wall_clock_seconds"] = round(time.time() - started, 1)

    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"aggregate": agg, "sites": rows}, fh, indent=2)
    write_markdown(os.path.join(outdir, "SUMMARY.md"), agg, rows)

    if not args.keep_artifacts:
        shutil.rmtree(os.path.join(outdir, "work"), ignore_errors=True)

    # ---------------------------------------------------------------- report
    print("\n" + "=" * 72)
    print("%d/%d sites produced a report; %d/%d passed every invariant."
          % (agg["sites_audited"], agg["sites_attempted"],
             agg["sites_passing_invariants"], agg["sites_attempted"]))
    print("Slowest audit %.1fs (budget %ds). Findings per site: %d / %d / %d "
          "(min/median/max)."
          % (agg["runtime_seconds_max"], RUNTIME_BUDGET_SECONDS,
             agg["findings_per_site"]["min"], agg["findings_per_site"]["median"],
             agg["findings_per_site"]["max"]))
    print("Sites with a critical finding: %d/%d."
          % (agg["sites_with_a_critical"], agg["sites_audited"]))

    if agg["shallow_crawl_suspected"]:
        print("\nWARNING - median crawl depth is %d page(s); %.0f%% of sites "
              "yielded one page or none."
              % (agg["pages_crawled_median"], agg["sites_with_one_page_pct"]))
        print("  Treat every firing rate in this run as UNCOMPARABLE to other")
        print("  runs. Most checks generalise from a page sample and stay")
        print("  silent below three pages, so a shallow crawl lowers rates")
        print("  across the board and mimics a detection improvement; it also")
        print("  pushes storefronts into site type `unknown`. Usual causes are")
        print("  rate limiting from repeated corpus runs (robots.txt answering")
        print("  403/429/420) or local network contention. Re-run later, or")
        print("  with fewer --workers, before drawing any conclusion.")

    if agg["network_saturation_suspected"]:
        print("\nWARNING - %d sites (%.0f%%) reported ACC-NO-RESPONSE."
              % (agg["no_response_sites"], agg["no_response_share_pct"]))
        print("  At this share the cause is usually the machine running the")
        print("  suite, not the sites: high concurrency saturates the local")
        print("  link or resolver and unrelated hosts time out together. Check")
        print("  whether the affected sites are adjacent in corpus order -- a")
        print("  contiguous block is a time window, not a property of those")
        print("  brands. Re-run with fewer --workers before believing it.")

    if agg["checks_firing_on_90pct_or_more"]:
        print("\nREVIEW - checks firing on >=90%% of sites (not diagnostic):")
        for cid in agg["checks_firing_on_90pct_or_more"]:
            print("  %-28s %.0f%%" % (cid, agg["check_firing_rate_pct"][cid]))
    if agg["checks_never_reached_in_any_bucket"]:
        print("\nREVIEW - check ids never reached in any bucket:")
        for cid in agg["checks_never_reached_in_any_bucket"]:
            print("  %s" % cid)

    failed = [r for r in rows if not r["passed"]]
    if failed:
        print("\nINVARIANT FAILURES on %d site(s):" % len(failed))
        for r in failed:
            print("  %s" % r["url"])
            for msg in r["invariant_failures"][:6]:
                print("    - %s" % msg)
        print("\nDetail: %s" % os.path.join(outdir, "SUMMARY.md"))
        sys.exit(1)

    print("\nAll invariants held on every site. Detail: %s"
          % os.path.join(outdir, "SUMMARY.md"))


if __name__ == "__main__":
    main()
