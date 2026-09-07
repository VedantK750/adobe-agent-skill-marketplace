#!/usr/bin/env python3
"""Run the whole marketplace end to end.

Order matters: acquisition first, because everything else reads its snapshot.
A skill that fails is recorded and the pipeline continues, so one broken
analyser degrades the report rather than losing it.
"""

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SKILLS = os.path.join(ROOT, "skills")
MANIFEST = os.path.join(ROOT, "marketplace.json")

# The order analysers run in. Acquisition must be first (it writes the snapshot
# every other skill reads); the rest are ordered so that a skill which explains
# *why* a later skill stayed silent runs first (readability before
# extractability, so "no extractable text" is already on record). The
# orchestrator does not invent this list — it intersects this order with the
# skills the manifest actually declares, so the manifest stays the single
# source of truth for what the marketplace contains.
ANALYSIS_ORDER = [
    "site-acquisition",
    "machine-readability",
    "structured-data",
    "answer-extractability",
    "entity-corroboration",
    "freshness-provenance",
    "engagement-audit",
]


def load_manifest():
    """Read marketplace.json and return (entrypoint_id, [non_entrypoint_ids]).

    Composition is manifest-driven: the set of skills the orchestrator runs is
    exactly the set the manifest declares (minus the entrypoint, which is the
    orchestrator itself). Adding or removing a skill in marketplace.json changes
    the pipeline with no code edit here — which is what makes the eight skills a
    genuine marketplace rather than a hardcoded call graph.
    """
    with open(MANIFEST, "r", encoding="utf-8") as fh:
        mani = json.load(fh)
    entry = None
    others = []
    for s in mani.get("skills", []):
        sid = s.get("id")
        if s.get("entrypoint"):
            entry = sid
        else:
            others.append(sid)
    return entry, others


def analyser_script(skill_id):
    """Resolve a skill's analysis entry point by the marketplace convention.

    Every analysis skill exposes scripts/analyze.py taking --workdir. Acquisition
    is the one exception: its entry point is crawl.py (it also needs --url and
    --max-pages), because it produces the snapshot rather than reading it.
    """
    if skill_id == "site-acquisition":
        return os.path.join(SKILLS, skill_id, "scripts", "crawl.py")
    return os.path.join(SKILLS, skill_id, "scripts", "analyze.py")


def run(cmd, label):
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        sys.stderr.write("[%s] FAILED (rc=%d)\n%s\n"
                         % (label, proc.returncode, proc.stdout[-1500:]))
        return False
    sys.stderr.write("[%s] done in %.1fs\n" % (label, time.time() - started))
    return True


def to_markdown(report):
    L = []
    a = report["audit_meta"]
    s = report["summary"]
    L.append("# AI-Readiness Audit: %s\n" % report["site"])
    L.append("Audited %s | %d pages | site type: %s | render: %s\n"
             % (report["audited_at"], a["pages_crawled"], a["site_type"],
                a["render_mode"]))
    L.append("**%d findings** - %d critical, %d high, %d medium, %d low "
             "(%d discoverability, %d engagement)\n"
             % (s["total_findings"], s["critical"], s["high"], s["medium"],
                s["low"], s["by_category"]["discoverability"],
                s["by_category"]["engagement"]))

    L.append("\n## Findings\n")
    for f in report["findings"]:
        L.append("### %s  %s - %s\n" % (f["id"], f["severity"].upper(), f["title"]))
        L.append("*%s | confidence: %s | detected by: %s*\n"
                 % (f["category"], f["confidence"], f["detected_by"]))
        L.append("**Why it matters.** %s\n" % f["mechanism"])
        L.append("**Evidence.** %s\n" % f["evidence"])
        if f.get("affected_urls"):
            L.append("**Affected.** %s\n"
                     % ", ".join(f["affected_urls"][:5]))
        act = f["suggested_action"]
        L.append("**Fix (%s priority, %s effort).** %s\n"
                 % (act.get("priority"), act.get("effort", "n/a"),
                    act.get("summary")))
        for step in act.get("steps", []):
            L.append("- %s" % step)
        if act.get("verification"):
            L.append("\n*Verify:* %s\n" % act["verification"])
        L.append("")

    L.append("\n## Proactive recommendations\n")
    for r in report["proactive_recommendations"]:
        L.append("### %s  %s (%s priority, %s effort)\n"
                 % (r["id"], r["title"], r["priority"], r["effort"]))
        L.append("%s\n" % r["rationale"])
        for step in r.get("steps", []):
            L.append("- %s" % step)
        L.append("")

    if report.get("not_applicable"):
        L.append("\n## Checks that ran and did not apply\n")
        for x in report["not_applicable"]:
            L.append("- `%s` - %s" % (x["check_id"], x["reason"]))
    if report.get("inconclusive"):
        L.append("\n## Checks that could not be evaluated\n")
        for x in report["inconclusive"]:
            L.append("- `%s` - %s" % (x["check_id"], x["reason"]))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Run the full audit pipeline.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--markdown", action="store_true",
                    help="Also write audit-report.md alongside the JSON.")
    args = ap.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    started = time.time()
    py = sys.executable

    # The manifest is the source of truth for which skills exist. We run exactly
    # those, in the defined analysis order; a manifest skill with no known order
    # is still run (appended), and an ordered skill absent from the manifest is
    # skipped. This is what makes the pipeline follow the marketplace rather than
    # a hardcoded list.
    entry, manifest_skills = load_manifest()
    declared = set(manifest_skills)
    ordered = [s for s in ANALYSIS_ORDER if s in declared]
    ordered += [s for s in manifest_skills if s not in ANALYSIS_ORDER]

    if "site-acquisition" not in declared:
        sys.stderr.write("[pipeline] manifest declares no site-acquisition skill; "
                         "cannot produce a snapshot\n")
        sys.exit(1)

    # 1. Acquisition first: it produces the snapshot everything else reads.
    crawl = [py, analyser_script("site-acquisition"),
             "--url", args.url, "--workdir", args.workdir,
             "--max-pages", str(args.max_pages)]
    if args.no_render:
        crawl.append("--no-render")
    if not run(crawl, "site-acquisition:crawl"):
        sys.exit(1)

    # 2. Every declared analysis skill, each an independent unit reading the
    #    shared snapshot. site-acquisition is included here too: crawl.py above
    #    produced the snapshot, and its analyze.py is what turns the crawl
    #    evidence (robots rules, redirects, canonicals) into findings. A skill
    #    that fails is recorded by `run` and the pipeline continues, so one
    #    broken analyser degrades the report rather than losing it.
    for skill in ordered:
        run([py, os.path.join(SKILLS, skill, "scripts", "analyze.py"),
             "--workdir", args.workdir], skill)

    out = os.path.join(args.workdir, "audit-report.json")
    if not run([py, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "compose_report.py"),
                "--workdir", args.workdir, "--out", out], "compose"):
        sys.exit(1)

    # Validation is a gate, not a log line. The report is still written -- it is
    # the artefact a human needs in order to see what went wrong -- but the exit
    # code has to carry the failure, or a caller that only checks the return
    # value ships an invalid report believing it passed.
    valid = run([py, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "validate_report.py"), "--report", out],
                "validate")

    if args.markdown:
        with open(out, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        md = os.path.join(args.workdir, "audit-report.md")
        with open(md, "w", encoding="utf-8") as fh:
            fh.write(to_markdown(report))
        sys.stderr.write("[markdown] -> %s\n" % md)

    sys.stderr.write("[pipeline] total %.1fs\n" % (time.time() - started))
    print(out)

    if not valid:
        sys.stderr.write(
            "[pipeline] the report at %s FAILED schema validation. It has been "
            "written so the problem can be inspected, but it must not be "
            "presented as an audit result until the offending fragment is "
            "fixed and the report recomposed.\n" % out)
        sys.exit(2)


if __name__ == "__main__":
    main()
