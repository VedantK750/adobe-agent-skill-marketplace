#!/usr/bin/env python3
"""Compose every skill's fragment into one schema-valid audit report.

Severity is computed here, centrally, from the impact/prevalence/importance
inputs each skill supplies. Skills never assign their own severity: that
would make the scale drift between skills and make the report
non-reproducible. The model is documented in references/severity-model.md and
implemented once, below.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
import auditlib as A  # noqa: E402

# impact -> base severity
BASE = {"blocking": "critical", "degrading": "high", "weakening": "medium"}

IMPORTANCE_BUMP = {"critical": 1, "high": 1, "normal": 0, "low": -1}


def shift(severity, steps):
    """Move along the severity scale; positive = more severe."""
    i = A.SEV_RANK[severity] - steps
    i = max(0, min(len(A.SEVERITIES) - 1, i))
    return A.SEVERITIES[i]


MIN_DENOMINATOR = 5   # below this, a prevalence ratio is not meaningful
MAX_UPWARD_SHIFT = 1  # modifiers may raise severity by at most one level


def compute_severity(finding):
    impact = finding.get("impact", "weakening")
    sev = BASE.get(impact, "medium")
    prev = finding.get("prevalence") or {}
    affected = prev.get("affected") or 0
    sampled = prev.get("sampled") or 0

    up, down = 0, 0

    # Prevalence, but only where the denominator supports a ratio. A
    # site-level singleton (1 of 1) is not "100% prevalent"; it is one fact
    # about the site, and treating it as universal was inflating severity.
    if sampled >= MIN_DENOMINATOR:
        share = affected / float(sampled)
        if share >= 0.8:
            up += 1
        elif share <= 0.2:
            down += 1

    if IMPORTANCE_BUMP.get(finding.get("page_importance", "normal"), 0) > 0:
        up += 1
    elif IMPORTANCE_BUMP.get(finding.get("page_importance", "normal"), 0) < 0:
        down += 1

    # Confidence only ever lowers severity; a heuristic result should not
    # outrank a directly observed one.
    if finding.get("confidence") == "medium":
        down += 1
    elif finding.get("confidence") == "low":
        down += 2

    sev = shift(sev, min(up, MAX_UPWARD_SHIFT) - down)

    # `critical` is reserved for defects that break the retrieval pipeline
    # outright: the crawler is refused, or the content is unreadable. Nothing
    # that merely degrades or weakens a signal can reach it, however
    # widespread. This keeps the top of the scale meaningful to a reader
    # deciding what to fix first.
    if impact != "blocking" and sev == "critical":
        sev = "high"
    return sev


def dedupe(findings):
    """Collapse findings that describe the same root cause.

    A client-rendered site trips both MR-RENDER-GAP and MR-EMPTY-SHELL. They
    are one problem with one fix, so reporting both inflates the count and
    reads as a false positive to anyone who checks.
    """
    groups = [
        {"MR-RENDER-GAP", "MR-EMPTY-SHELL"},
        {"ACC-BLANKET-DISALLOW", "ACC-AI-CRAWLER-BLOCKED"},
    ]
    by_check = {f["check_id"]: f for f in findings}
    drop = set()
    for group in groups:
        present = [c for c in group if c in by_check]
        if len(present) > 1:
            keep = max(present,
                       key=lambda c: -A.SEV_RANK[by_check[c]["severity"]])
            for c in present:
                if c != keep:
                    drop.add(c)
                    by_check[keep].setdefault("also_indicated_by", []).append(c)
    return [f for f in findings if f["check_id"] not in drop]


PROACTIVE = [
    {
        "id": "P-001",
        "title": "Publish a canonical facts page and an llms.txt",
        "rationale": "Gives every consumer one authoritative, plain-text "
                     "source for the brand's core claims, so corroboration "
                     "starts from a single consistent statement rather than "
                     "from whatever page happened to be fetched.",
        "priority": "medium",
        "effort": "low",
        "steps": [
            "Create a page stating name, category, what the brand does, who "
            "for, location, founding year and how to get in touch, in plain "
            "sentences.",
            "Serve /llms.txt in Markdown, linking the highest-value pages with "
            "one-line descriptions.",
            "Reuse the same wording in Organization.description and in every "
            "external profile so corroboration is exact rather than approximate.",
        ],
    },
    {
        "id": "P-002",
        "title": "Adopt the answer-block pattern site-wide",
        "rationale": "A question-shaped heading followed by a short, "
                     "self-contained answer is the most reliably quotable "
                     "structure available, because the heading supplies the "
                     "query match and the sentence supplies the citable text.",
        "priority": "high",
        "effort": "medium",
        "steps": [
            "For each page, list the questions it should own.",
            "Add an H2 phrased as the question and answer it in 30-50 words "
            "directly beneath.",
            "Keep the answer free of pronouns that refer outside the block.",
        ],
    },
    {
        "id": "P-003",
        "title": "Add stable heading anchors across the site",
        "rationale": "Lets a citation point at the exact section that answers "
                     "the question rather than at the page, which makes the "
                     "page a more useful and more frequently chosen source.",
        "priority": "medium",
        "effort": "low",
        "steps": ["Generate slug ids for every H2 and H3 at build time.",
                  "Keep ids stable across edits so existing citations survive."],
    },
    {
        "id": "P-004",
        "title": "Build the entity graph: sameAs plus a Wikidata presence",
        "rationale": "Anchors the brand against similarly named entities. "
                     "Without a distinguishing anchor, systems conflate "
                     "same-named organisations and attribute facts to the "
                     "wrong one.",
        "priority": "medium",
        "effort": "medium",
        "steps": ["List every official profile in Organization.sameAs.",
                  "Establish or correct a Wikidata item where notability allows.",
                  "State the disambiguating category and location in prose on "
                  "the home page."],
    },
    {
        "id": "P-005",
        "title": "Convert image-rendered data into HTML tables",
        "rationale": "Specification sheets, price lists and charts delivered "
                     "as images carry facts that no text extractor can read, "
                     "however prominent they are on screen.",
        "priority": "medium",
        "effort": "medium",
        "steps": ["Inventory images that carry data rather than decoration.",
                  "Re-render each as an HTML table with the same values.",
                  "Keep the image as visual reinforcement if wanted."],
    },
    {
        "id": "P-006",
        "title": "Publish transcripts for video and audio",
        "rationale": "Converts substance that currently exists only in "
                     "non-text media into extractable, quotable text.",
        "priority": "low",
        "effort": "medium",
        "steps": ["Generate transcripts and publish them on the same page.",
                  "Add headings inside long transcripts so sections chunk well."],
    },
    {
        "id": "P-007",
        "title": "Run a corroboration programme for the canonical facts",
        "rationale": "A claim that appears only on the brand's own site is "
                     "treated as fragile. Agreement across unrelated domains "
                     "is what makes a fact repeatable.",
        "priority": "high",
        "effort": "high",
        "steps": [
            "Fix the canonical wording of each core fact.",
            "Claim and complete listings on the authoritative directories for "
            "the sector, using that exact wording.",
            "Pursue mentions on domains with no commercial tie to the brand.",
        ],
    },
    {
        "id": "P-008",
        "title": "Add comparison, alternatives and glossary pages",
        "rationale": "Comparative and definitional questions are among the "
                     "most common asked of assistants, and pages built to "
                     "answer them directly are cited disproportionately often.",
        "priority": "medium",
        "effort": "medium",
        "steps": ["Write honest comparison pages including where the brand is "
                  "not the right choice.",
                  "Publish a glossary defining the terms the sector uses."],
    },
    {
        "id": "P-009",
        "title": "Maintain a changelog with honest dateModified values",
        "rationale": "Gives a defensible freshness signal that survives "
                     "scrutiny, unlike a build-time timestamp applied to every "
                     "page at once.",
        "priority": "low",
        "effort": "low",
        "steps": ["Record content-change timestamps per page.",
                  "Publish a changelog for substantive updates."],
    },
    {
        "id": "P-010",
        "title": "Front-load readable text in outbound email",
        "rationale": "Inbox summarisers build from message text. Substance "
                     "carried by images, or buried beneath filler, is dropped "
                     "from the summary the recipient actually reads.",
        "priority": "low",
        "effort": "low",
        "steps": ["Put the key message in the first readable lines as text.",
                  "Never carry the core offer in an image alone.",
                  "Keep preheader text meaningful rather than decorative."],
    },
]


def compose(workdir, out_path):
    snap = A.load_snapshot(workdir)
    fragments = A.load_fragments(workdir)

    raw, na, unknown, skills_run = [], [], [], []
    for frag in fragments:
        skills_run.append(frag.get("skill"))
        raw.extend(frag.get("findings", []))
        na.extend(frag.get("not_applicable", []))
        unknown.extend(frag.get("inconclusive", []))

    for f in raw:
        f["severity"] = compute_severity(f)
        action = f.get("suggested_action") or {}
        action.pop("priority_hint", None)
        action["priority"] = f["severity"]
        f["suggested_action"] = action

    findings = dedupe(raw)

    # Deterministic ordering: severity, then effort, then check id.
    effort_rank = {"low": 0, "medium": 1, "high": 2}
    findings.sort(key=lambda f: (
        A.SEV_RANK[f["severity"]],
        effort_rank.get((f.get("suggested_action") or {}).get("effort"), 1),
        f["check_id"],
    ))

    out = []
    for i, f in enumerate(findings, start=1):
        item = {
            "id": "F-%03d" % i,
            "check_id": f["check_id"],
            "title": f["title"],
            "severity": f["severity"],
            "confidence": f.get("confidence", "high"),
            "category": f.get("category", "discoverability"),
            "detected_by": f.get("skill"),
            "mechanism": f.get("mechanism", ""),
            "evidence": f.get("evidence", ""),
            "affected_urls": f.get("affected_urls", []),
            "prevalence": f.get("prevalence", {}),
            "suggested_action": f.get("suggested_action", {}),
        }
        if f.get("also_indicated_by"):
            item["also_indicated_by"] = f["also_indicated_by"]
        out.append(item)

    counts = {s: sum(1 for f in out if f["severity"] == s) for s in A.SEVERITIES}

    report = {
        "site": snap.get("site"),
        "audited_at": snap.get("audited_at"),
        "audit_meta": {
            "pages_crawled": snap.get("crawl", {}).get("pages_crawled", 0),
            "render_mode": snap.get("render_mode", "static-only"),
            "robots_respected": bool(snap.get("robots_respected", True)),
            "site_type": snap.get("site_type", "unknown"),
            "skills_run": sorted(set(skills_run)),
            "runtime_seconds": snap.get("crawl", {}).get("runtime_seconds", 0),
            "page_types_seen": sorted({p.get("page_type") for p in
                                       snap.get("pages", []) if p.get("page_type")}),
        },
        "summary": {
            "total_findings": len(out),
            "critical": counts["critical"],
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "by_category": {
                "discoverability": sum(1 for f in out
                                       if f["category"] == "discoverability"),
                "engagement": sum(1 for f in out if f["category"] == "engagement"),
            },
        },
        "findings": out,
        "proactive_recommendations": PROACTIVE,
        "not_applicable": sorted(na, key=lambda x: x["check_id"]),
        "inconclusive": sorted(unknown, key=lambda x: x["check_id"]),
    }

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(args.workdir, "audit-report.json")
    r = compose(args.workdir, out)
    sys.stderr.write(
        "[compose] %d findings (%d critical, %d high, %d medium, %d low) -> %s\n"
        % (r["summary"]["total_findings"], r["summary"]["critical"],
           r["summary"]["high"], r["summary"]["medium"], r["summary"]["low"], out))


if __name__ == "__main__":
    main()
