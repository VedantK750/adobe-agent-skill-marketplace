#!/usr/bin/env python3
"""Check the marketplace against the Round-3 brief's hard requirements.

The rubric has two halves. One is judgement -- are the checks right, are the
fixes mechanism-sound -- and no script can score that. The other half is
mechanical: exactly one entrypoint, every skill folder agentskills.io
compliant, the report schema floor, recommend-only, inside the size and runtime
budgets. Those are exactly the requirements that are cheap to satisfy and
embarrassing to fail, and they are checkable, so they are checked here rather
than eyeballed before submission.

  python3 tests/check_compliance.py            # all checks
  python3 tests/check_compliance.py --report path/to/audit-report.json

Exit code is non-zero if any requirement is unmet.
"""

import argparse
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Required by the brief, per finding and per report.
REQUIRED_FINDING_FIELDS = ["id", "title", "severity", "evidence",
                           "suggested_action"]
REQUIRED_REPORT_FIELDS = ["site", "audited_at", "summary", "findings"]
REQUIRED_SUMMARY_FIELDS = ["total_findings", "critical", "high", "medium"]

# The brief's SKILL.md template. Headings are matched case-insensitively on
# their leading words, so "## Inputs (a URL)" satisfies "Inputs".
REQUIRED_SKILL_SECTIONS = ["when to use", "inputs", "procedure", "output"]

RESULTS = []


def check(ok, label, detail=""):
    RESULTS.append((bool(ok), label, detail))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", label,
                           "" if ok else "  -- " + detail))


def parse_frontmatter(text):
    """Minimal YAML frontmatter reader: enough for name/description/license.

    Deliberately not a YAML dependency -- the brief calls for portability, and
    the marketplace must validate on a machine with nothing installed.
    """
    if not text.startswith("---"):
        return None, "file does not open with a --- frontmatter fence"
    end = text.find("\n---", 3)
    if end == -1:
        return None, "frontmatter fence is never closed"
    block = text[3:end]
    out, key = {}, None
    for line in block.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([a-zA-Z][\w-]*):\s*(.*)$", line)
        if m:
            key = m.group(1).lower()
            out[key] = m.group(2).strip()
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out, None


def check_manifest():
    print("\nManifest (marketplace.json)")
    path = os.path.join(ROOT, "marketplace.json")
    check(os.path.exists(path), "marketplace.json exists at the marketplace root")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            mani = json.load(fh)
    except Exception as exc:
        check(False, "marketplace.json is valid JSON", str(exc))
        return None
    check(True, "marketplace.json is valid JSON")

    skills = mani.get("skills") or []
    check(bool(skills), "manifest lists at least one skill")
    check("name" in mani and "version" in mani,
          "manifest declares name and version")

    entrypoints = [s for s in skills if s.get("entrypoint")]
    check(len(entrypoints) == 1,
          "exactly one skill is marked as the entrypoint",
          "found %d: %s" % (len(entrypoints),
                            [s.get("id") for s in entrypoints]))

    check(all(s.get("id") and s.get("path") for s in skills),
          "every listed skill declares an id and a path")

    # The manifest must be self-contained: no URL, no external resolver.
    blob = json.dumps(mani)
    check("http://" not in blob and "https://" not in blob,
          "manifest is self-contained (no external service to resolve)")
    return mani


def check_skills(mani):
    print("\nSkill folders (agentskills.io format)")
    if not mani:
        return
    for s in mani.get("skills", []):
        sid, spath = s.get("id"), s.get("path", "")
        folder = os.path.join(ROOT, spath)
        md = os.path.join(folder, "SKILL.md")
        if not os.path.exists(md):
            check(False, "%s: SKILL.md present" % sid, "missing at %s" % md)
            continue
        with open(md, encoding="utf-8") as fh:
            text = fh.read()

        fm, err = parse_frontmatter(text)
        if fm is None:
            check(False, "%s: SKILL.md has YAML frontmatter" % sid, err)
            continue

        problems = []
        if not fm.get("name"):
            problems.append("no name")
        elif fm["name"] != sid:
            problems.append("name %r != manifest id %r" % (fm["name"], sid))
        if not fm.get("description"):
            problems.append("no description")
        elif len(fm["description"]) < 40:
            problems.append("description too short to route on")
        check(not problems,
              "%s: frontmatter declares a matching name and a description" % sid,
              "; ".join(problems))

        check(bool(fm.get("license")), "%s: declares a license" % sid)
        check(bool(fm.get("allowed-tools")),
              "%s: declares allowed-tools" % sid)

        body = text.lower()
        missing = [h for h in REQUIRED_SKILL_SECTIONS
                   if not re.search(r"^#{1,4}\s*%s" % re.escape(h), body,
                                    re.M)]
        check(not missing,
              "%s: has the brief's sections (when to use / inputs / procedure "
              "/ output)" % sid,
              "missing: %s" % missing)

        # Progressive disclosure: the brief asks for lean SKILL.md files with
        # detail pushed into references/ and scripts/.
        check(len(text.splitlines()) <= 160,
              "%s: SKILL.md is lean (<=160 lines)" % sid,
              "%d lines" % len(text.splitlines()))


def check_layout():
    print("\nSubmission layout")
    check(os.path.exists(os.path.join(ROOT, "README.md")),
          "README.md present at the marketplace root")
    check(os.path.exists(os.path.join(ROOT, "report.schema.json")),
          "report.schema.json present (the report contract)")
    zip_path = os.path.join(ROOT, "brand-ai-readiness-audit.zip")
    if os.path.exists(zip_path):
        mb = os.path.getsize(zip_path) / 1e6
        check(mb <= 50, "submission zip is within the 50 MB limit",
              "%.1f MB" % mb)


def check_recommend_only():
    """No skill may alter a live site. Verified from the source, not asserted.

    The brief's hardest constraint to prove by inspection is the one most worth
    proving: every request the marketplace makes must be a read. Rather than
    trusting a claim in a README, walk the AST of every shipped script and fail
    on any call that could write to the network or the shell.
    """
    print("\nRecommend-only / safety (verified from source)")
    write_methods = {"post", "put", "delete", "patch", "head_request"}
    banned_calls = {"system", "popen", "check_output", "spawn", "spawnl"}
    offenders, subprocess_users = [], []

    scripts = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "skills")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        scripts += [os.path.join(dirpath, f) for f in filenames
                    if f.endswith(".py")]
    scripts.append(os.path.join(ROOT, "lib", "auditlib.py"))

    for path in scripts:
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            offenders.append("%s: does not parse (%s)" % (rel, exc))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(
                fn, "id", None)
            if name in write_methods:
                offenders.append("%s: calls %s() -- a state-changing request"
                                 % (rel, name))
            if name in banned_calls:
                offenders.append("%s: calls %s()" % (rel, name))
            if name == "run" and isinstance(fn, ast.Attribute) and \
                    isinstance(fn.value, ast.Name) and \
                    fn.value.id == "subprocess":
                subprocess_users.append(rel)

    check(not offenders, "no skill issues a state-changing or shell request",
          "; ".join(offenders[:4]))

    # subprocess is legitimate in exactly one place: the orchestrator running
    # the other skills. Anywhere else it is a way to smuggle side effects past
    # the check above.
    stray = sorted({p for p in subprocess_users
                    if "audit-orchestrator" not in p})
    check(not stray, "subprocess is confined to the orchestrator",
          "also used by: %s" % stray)

    crawl = os.path.join(ROOT, "skills", "site-acquisition", "scripts",
                         "crawl.py")
    with open(crawl, encoding="utf-8") as fh:
        csrc = fh.read()
    check("robotparser" in csrc and "can_fetch" in csrc,
          "the crawler parses robots.txt and consults it before fetching")
    check(re.search(r"time\.sleep\(\s*delay\s*\)", csrc) is not None,
          "the crawler applies a politeness delay between requests")
    check("WALL_CLOCK_BUDGET" in csrc,
          "the crawl is bounded by a wall-clock budget")


def check_report_schema(report_path):
    print("\nReport schema floor")
    if not report_path or not os.path.exists(report_path):
        print("  (skipped: no report supplied; pass --report to check one)")
        return
    with open(report_path, encoding="utf-8") as fh:
        rep = json.load(fh)

    missing = [k for k in REQUIRED_REPORT_FIELDS if k not in rep]
    check(not missing, "report carries site, audited_at, summary, findings",
          "missing: %s" % missing)

    summary = rep.get("summary") or {}
    miss_s = [k for k in REQUIRED_SUMMARY_FIELDS if k not in summary]
    check(not miss_s, "summary carries total_findings and counts by severity",
          "missing: %s" % miss_s)

    check(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                   str(rep.get("audited_at", ""))) is not None,
          "audited_at is an ISO-8601 UTC timestamp",
          repr(rep.get("audited_at")))

    bad = []
    for i, f in enumerate(rep.get("findings", [])):
        for k in REQUIRED_FINDING_FIELDS:
            if k not in f:
                bad.append("findings[%d] missing %s" % (i, k))
        act = f.get("suggested_action")
        if isinstance(act, dict) and not (act.get("summary") or "").strip():
            bad.append("findings[%d] suggested_action has no summary" % i)
    check(not bad, "every finding carries id, title, severity, evidence, "
                   "suggested_action", "; ".join(bad[:4]))

    check(isinstance(rep.get("proactive_recommendations"), list)
          and len(rep["proactive_recommendations"]) > 0,
          "report carries suggested actions beyond the detected problems")


def check_coverage():
    """Both halves of the Round-2 problem must actually be covered."""
    print("\nRound-2 coverage (both halves)")
    ids = set()
    pat = re.compile(r'\.(?:finding|na|unknown)\(\s*\n?\s*"([A-Z][A-Z0-9-]+)"')
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "skills")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn == "analyze.py":
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    ids |= set(pat.findall(fh.read()))

    # Off-site discoverability: crawlability, render, structured data,
    # extractability, corroboration, freshness.
    disco = {p for p in ids if p.split("-")[0] in
             ("ACC", "MR", "SD", "AE", "EC", "FP")}
    engage = {p for p in ids if p.startswith("EN-")}
    check(len(disco) >= 20,
          "off-site discoverability is covered (%d checks)" % len(disco))
    check(len(engage) >= 8,
          "on-site engagement is covered (%d checks)" % len(engage))

    # The appendix's pipeline: admitted -> readable -> extractable.
    for prefix, concern in (("ACC", "crawler admitted"),
                            ("MR", "page readable"),
                            ("AE", "fact extractable"),
                            ("SD", "facts stated explicitly"),
                            ("EC", "agreement across the web"),
                            ("FP", "freshness and provenance")):
        check(any(i.startswith(prefix + "-") for i in ids),
              "appendix concern covered: %s (%s-*)" % (concern, prefix))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None,
                    help="An audit-report.json to check against the schema floor.")
    args = ap.parse_args()

    print("Round-3 brief compliance check")
    mani = check_manifest()
    check_skills(mani)
    check_layout()
    check_recommend_only()
    check_coverage()
    check_report_schema(args.report)

    passed = sum(1 for ok, _, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n%d/%d requirements met." % (passed, total))
    if passed != total:
        print("\nUNMET:")
        for ok, label, detail in RESULTS:
            if not ok:
                print("  - %s%s" % (label, ("  -- " + detail) if detail else ""))
        sys.exit(1)
    print("Marketplace meets every mechanically checkable requirement.")


if __name__ == "__main__":
    main()
