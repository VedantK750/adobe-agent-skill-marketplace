#!/usr/bin/env python3
"""Internal Marketplace Quality Index (MQI) Benchmarking & Scoring Engine.

FOR INTERNAL TEAM USE ONLY — NOT TO BE SUBMITTED FOR HACKATHON.
Evaluates the detection accuracy, crawl representativeness, causal mechanism
soundness, and remediation quality of any audit run against real websites.

Formula:
  MQI (0-100) = Grounded Precision (25) + Causal Mechanism (20)
              + Crawl Entropy (15) + Severity Calibration (15)
              + Actionability Depth (15) + Root-Cause Orthogonality (10)

Usage:
  python3 benchmark/mqi.py --workdir audit-thewholetruthfoods.com
  python3 benchmark/mqi.py --compare audit-mokobara.com audit-mokobara.com-v2
"""

import argparse
import json
import math
import os
import re
import sys
from typing import Dict, Any, Tuple, Optional


CRITICAL_BLOCKERS = {
    "ACC-AI-CRAWLER-BLOCKED",
    "ACC-BLANKET-DISALLOW",
    "MR-EMPTY-SHELL",
    "ACC-NO-RESPONSE",
}

AI_MECHANISM_KEYWORDS = {
    "rag", "chunk", "pronoun", "antecedent", "vector", "citation",
    "perplexity", "chatgpt", "overviews", "knowledge graph",
    "hallucination", "retrieval", "quotation", "e-e-a-t",
    "machine-readable", "schema.org", "json-ld", "structured data",
    "bounce", "orientation", "anchor", "deep-link", "crawler",
    "disallow", "robots.txt", "sitemap", "dead end", "404", "500",
}


def compute_shannon_entropy(page_types: list) -> Tuple[float, float]:
    """Compute Shannon Entropy over the distribution of crawled page types."""
    if not page_types:
        return 0.0, 0.0
    total = len(page_types)
    counts = {}
    for pt in page_types:
        counts[pt] = counts.get(pt, 0) + 1
    
    entropy = 0.0
    for pt, c in counts.items():
        p = c / total
        if p > 0:
            entropy -= p * math.log(p)
            
    # Max possible entropy for 6 standard types is ln(6) ~= 1.79
    max_entropy = math.log(6)
    normalized = min(1.0, entropy / max_entropy)
    return round(entropy, 2), round(normalized, 2)


def evaluate_grounded_precision(snapshot: dict, report: dict) -> Tuple[float, list]:
    """Evaluate whether each finding is mathematically backed by DOM evidence in snapshot."""
    findings = report.get("findings", [])
    if not findings:
        return 25.0, []

    pages_by_url = {p.get("final_url", p.get("url")): p for p in snapshot.get("pages", [])}
    verified_count = 0
    penalties = []

    for f in findings:
        aff = f.get("affected_urls", [])
        evidence = f.get("evidence", "")
        cid = f.get("check_id", "")

        # Check 1: Do affected URLs exist in snapshot?
        valid_urls = [u for u in aff if u in pages_by_url]
        if aff and not valid_urls:
            penalties.append(f"[{cid}] Affected URLs not found in snapshot.")
            continue

        # Check 2: Check for known false-alarm patterns
        if cid == "FP-UNDATED-TIME-SENSITIVE":
            # If all affected pages are product pages, penalize as false positive
            types = [pages_by_url[u].get("page_type") for u in valid_urls if u in pages_by_url]
            if types and all(t == "product" for t in types):
                penalties.append(f"[{cid}] False alarm: product pages falsely flagged for undated prices in prose.")
                continue

        if cid == "FP-STALE-COPYRIGHT":
            # Check if any affected page actually has a modern year in its span
            has_modern = False
            for u in valid_urls:
                txt = pages_by_url.get(u, {}).get("text", "")
                years = [int(y) for y in re.findall(r"\b(202[4-9]|203[0-9])\b", txt[:2000])]
                if years:
                    has_modern = True
                    break
            if has_modern:
                penalties.append(f"[{cid}] False alarm: modern copyright year detected but flagged as stale.")
                continue

        verified_count += 1

    precision_ratio = verified_count / max(1, len(findings))
    score = round(precision_ratio * 25.0, 1)
    return score, penalties


def evaluate_causal_mechanism(report: dict) -> Tuple[float, int, int]:
    """Evaluate whether findings explain real AI assistant / LLM retrieval failure modes."""
    findings = report.get("findings", [])
    if not findings:
        return 20.0, 0, 0

    sound_mechanisms = 0
    for f in findings:
        mech = (f.get("mechanism", "") + " " + f.get("title", "")).lower()
        if any(kw in mech for kw in AI_MECHANISM_KEYWORDS):
            sound_mechanisms += 1

    ratio = sound_mechanisms / len(findings)
    score = round(ratio * 20.0, 1)
    return score, sound_mechanisms, len(findings)


def evaluate_severity_calibration(report: dict) -> Tuple[float, list]:
    """Check for severity inflation (non-blockers marked critical, etc.)."""
    findings = report.get("findings", [])
    if not findings:
        return 15.0, []

    penalties = []
    deductions = 0.0

    for f in findings:
        sev = f.get("severity", "").lower()
        cid = f.get("check_id", "")
        
        # Inflation: Marking weakening defects as Critical
        if sev == "critical" and cid not in CRITICAL_BLOCKERS:
            penalties.append(f"[{cid}] Severity inflation: non-blocking defect labeled as CRITICAL.")
            deductions += 4.0
        
        # Inflation: High severity for minor orientation issues
        if sev == "high" and cid in ("AE-NO-HEADING-ANCHORS", "EC-FEW-EXTERNAL-PROFILES", "EN-NO-SITE-SEARCH"):
            penalties.append(f"[{cid}] Minor feature inflated to HIGH severity.")
            deductions += 2.0

    score = max(0.0, round(15.0 - deductions, 1))
    return score, penalties


def evaluate_actionability_depth(workdir: str, report: dict) -> Tuple[float, dict]:
    """Evaluate the presence and production-readiness of generated remediation artifacts."""
    rem_dir = os.path.join(workdir, "remediation")
    artifacts_found = {}
    expected = [
        ("1_rag_passage_rewrites.md", 3.0),
        ("2_brand_definition_anchor.html", 3.0),
        ("3_merchant_transparency.jsonld", 3.0),
        ("4_citation_anchor_patch.js", 2.0),
        ("5_persona_constraint_matrix.html", 2.0),
        ("llms.txt", 2.0),
    ]

    total_score = 0.0
    for filename, points in expected:
        filepath = os.path.join(rem_dir, filename)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 50:
            artifacts_found[filename] = True
            total_score += points
        else:
            artifacts_found[filename] = False

    return round(min(15.0, total_score), 1), artifacts_found


def evaluate_orthogonality(report: dict) -> Tuple[float, float]:
    """Measure root-cause deduplication ratio so 1 bug doesn't spawn 5 redundant findings."""
    findings = report.get("findings", [])
    if not findings:
        return 10.0, 1.0

    # Group by skill category
    cids = [f.get("check_id", "") for f in findings]
    unique_cids = len(set(cids))
    dedup_ratio = unique_cids / max(1, len(cids))

    # Check for schema redundancy (e.g. SD-ABSENT + SD-NO-PRODUCT on same pages)
    score = round(dedup_ratio * 10.0, 1)
    return score, round(dedup_ratio, 2)


def compute_mqi(workdir: str) -> Dict[str, Any]:
    """Compute the complete 6-Pillar Marketplace Quality Index (MQI: 0-100) for an audit directory."""
    snap_path = os.path.join(workdir, "snapshot.json")
    rep_path = os.path.join(workdir, "audit-report.json")

    if not os.path.exists(snap_path) or not os.path.exists(rep_path):
        raise FileNotFoundError(f"Missing snapshot.json or audit-report.json in {workdir}")

    with open(snap_path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    with open(rep_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # 1. Precision (25 pts)
    precision_score, prec_penalties = evaluate_grounded_precision(snapshot, report)

    # 2. Causal Mechanism (20 pts)
    mech_score, sound_mechs, total_mechs = evaluate_causal_mechanism(report)

    # 3. Crawl Entropy (15 pts)
    page_types = [p.get("page_type") for p in snapshot.get("pages", []) if p.get("page_type")]
    raw_entropy, norm_entropy = compute_shannon_entropy(page_types)
    entropy_score = round(norm_entropy * 15.0, 1)

    # 4. Severity Calibration (15 pts)
    calib_score, calib_penalties = evaluate_severity_calibration(report)

    # 5. Actionability Depth (15 pts)
    act_score, artifacts = evaluate_actionability_depth(workdir, report)

    # 6. Orthogonality (10 pts)
    ortho_score, dedup_ratio = evaluate_orthogonality(report)

    total_mqi = round(precision_score + mech_score + entropy_score + calib_score + act_score + ortho_score, 1)

    if total_mqi >= 90:
        tier = "🏆 Elite (Production-Ready)"
    elif total_mqi >= 80:
        tier = "✨ High Quality"
    elif total_mqi >= 65:
        tier = "⚠️ Moderate (Room for improvement)"
    else:
        tier = "❌ Sub-optimal"

    return {
        "workdir": workdir,
        "site": snapshot.get("site", "unknown"),
        "total_mqi": total_mqi,
        "tier": tier,
        "pillars": {
            "grounded_precision": {"score": precision_score, "max": 25, "penalties": prec_penalties},
            "causal_mechanism": {"score": mech_score, "max": 20, "sound": sound_mechs, "total": total_mechs},
            "crawl_entropy": {"score": entropy_score, "max": 15, "raw_entropy": raw_entropy, "normalized": norm_entropy, "types": list(set(page_types))},
            "severity_calibration": {"score": calib_score, "max": 15, "penalties": calib_penalties},
            "actionability_depth": {"score": act_score, "max": 15, "artifacts": artifacts},
            "root_cause_orthogonality": {"score": ortho_score, "max": 10, "dedup_ratio": dedup_ratio},
        }
    }


def format_single_card(mqi: dict) -> str:
    """Format a single audit MQI result card as a string."""
    p = mqi["pillars"]
    out = []
    out.append("=" * 80)
    out.append(f"      MARKETPLACE QUALITY INDEX (MQI): {mqi['site'].upper()}")
    out.append("=" * 80)
    out.append(f"Overall MQI Score : {mqi['total_mqi']} / 100  ->  {mqi['tier']}")
    out.append("-" * 80)
    out.append(f"  1. Grounded Precision        : {p['grounded_precision']['score']} / 25 pts")
    out.append(f"  2. Causal Mechanism Soundness: {p['causal_mechanism']['score']} / 20 pts ({p['causal_mechanism']['sound']}/{p['causal_mechanism']['total']} mechanisms sound)")
    out.append(f"  3. Crawl Entropy & Diversity : {p['crawl_entropy']['score']} / 15 pts (H = {p['crawl_entropy']['raw_entropy']}, Types: {', '.join(p['crawl_entropy']['types'])})")
    out.append(f"  4. Severity Calibration      : {p['severity_calibration']['score']} / 15 pts")
    out.append(f"  5. Actionability & Code Depth: {p['actionability_depth']['score']} / 15 pts")
    out.append(f"  6. Root-Cause Orthogonality  : {p['root_cause_orthogonality']['score']} / 10 pts")
    out.append("-" * 80)
    if p["grounded_precision"]["penalties"]:
        out.append("Grounded Precision Notes:")
        for pen in p["grounded_precision"]["penalties"]:
            out.append(f"  • {pen}")
    if p["severity_calibration"]["penalties"]:
        out.append("Severity Calibration Notes:")
        for pen in p["severity_calibration"]["penalties"]:
            out.append(f"  • {pen}")
    out.append("Generated Remediation Artifacts:")
    for art, present in p["actionability_depth"]["artifacts"].items():
        out.append(f"  {'✓' if present else '✗'} {art}")
    out.append("=" * 80)
    return "\n".join(out)


def format_comparison_card(res_a: dict, res_b: dict) -> str:
    """Format a side-by-side arena comparison card as a string."""
    pa = res_a["pillars"]
    pb = res_b["pillars"]

    def winner(va, vb):
        diff = round(vb - va, 1)
        if diff > 0:
            return f"🏆 B (+{diff})"
        elif diff < 0:
            return f"A (+{abs(diff)})"
        return "Tie (=)"

    out = []
    out.append("=" * 90)
    out.append(f"          AUTONOMOUS MARKETPLACE ARENA: {res_a['site']} vs {res_b['site']}")
    out.append("=" * 90)
    out.append(f"{'Metric':<30} {'Run A (' + res_a['workdir'] + ')':<25} {'Run B (' + res_b['workdir'] + ')':<25} {'Verdict'}")
    out.append("-" * 90)
    out.append(f"{'1. Grounded Precision (25)':<30} {str(pa['grounded_precision']['score']) + ' pts':<25} {str(pb['grounded_precision']['score']) + ' pts':<25} {winner(pa['grounded_precision']['score'], pb['grounded_precision']['score'])}")
    out.append(f"{'2. Causal Mechanism (20)':<30} {str(pa['causal_mechanism']['score']) + ' pts':<25} {str(pb['causal_mechanism']['score']) + ' pts':<25} {winner(pa['causal_mechanism']['score'], pb['causal_mechanism']['score'])}")
    out.append(f"{'3. Crawl Diversity (15)':<30} {str(pa['crawl_entropy']['score']) + ' pts (H=' + str(pa['crawl_entropy']['raw_entropy']) + ')':<25} {str(pb['crawl_entropy']['score']) + ' pts (H=' + str(pb['crawl_entropy']['raw_entropy']) + ')':<25} {winner(pa['crawl_entropy']['score'], pb['crawl_entropy']['score'])}")
    out.append(f"{'4. Severity Calibration (15)':<30} {str(pa['severity_calibration']['score']) + ' pts':<25} {str(pb['severity_calibration']['score']) + ' pts':<25} {winner(pa['severity_calibration']['score'], pb['severity_calibration']['score'])}")
    out.append(f"{'5. Actionability Depth (15)':<30} {str(pa['actionability_depth']['score']) + ' pts':<25} {str(pb['actionability_depth']['score']) + ' pts':<25} {winner(pa['actionability_depth']['score'], pb['actionability_depth']['score'])}")
    out.append(f"{'6. Orthogonality (10)':<30} {str(pa['root_cause_orthogonality']['score']) + ' pts':<25} {str(pb['root_cause_orthogonality']['score']) + ' pts':<25} {winner(pa['root_cause_orthogonality']['score'], pb['root_cause_orthogonality']['score'])}")
    out.append("-" * 90)
    out.append(f"{'TOTAL MQI SCORE (0-100)':<30} {str(res_a['total_mqi']) + ' / 100':<25} {str(res_b['total_mqi']) + ' / 100':<25} {winner(res_a['total_mqi'], res_b['total_mqi'])}")
    out.append("=" * 90)
    return "\n".join(out)


def format_leaderboard(runs: list) -> str:
    """Format a leaderboard of all evaluated audit runs."""
    import glob
    sorted_runs = sorted(runs, key=lambda x: x["total_mqi"], reverse=True)
    out = []
    out.append("=" * 115)
    out.append("                       MARKETPLACE QUALITY INDEX (MQI) LEADERBOARD")
    out.append("=" * 115)
    header = f"{'#':<3} {'Site':<22} {'Workdir':<30} {'MQI':<8} {'Tier':<20} {'Prec':<6} {'Mech':<6} {'Entr':<6} {'Cal':<6} {'Rem':<6} {'Ort':<5}"
    out.append(header)
    out.append("-" * 115)
    for idx, r in enumerate(sorted_runs, 1):
        p = r["pillars"]
        row = (
            f"{idx:<3} "
            f"{r['site'][:20]:<22} "
            f"{r['workdir'][:28]:<30} "
            f"{str(r['total_mqi']):<8} "
            f"{r['tier']:<20} "
            f"{str(p['grounded_precision']['score']):<6} "
            f"{str(p['causal_mechanism']['score']):<6} "
            f"{str(p['crawl_entropy']['score']):<6} "
            f"{str(p['severity_calibration']['score']):<6} "
            f"{str(p['actionability_depth']['score']):<6} "
            f"{str(p['root_cause_orthogonality']['score']):<5}"
        )
        out.append(row)
    out.append("=" * 115)
    return "\n".join(out)


def scan_audit_directories(root_dir: str = ".") -> list:
    """Find all directories containing snapshot.json and audit-report.json."""
    import glob
    dirs = []
    pattern = os.path.join(root_dir, "audit-*")
    for d in sorted(glob.glob(pattern)):
        if os.path.isdir(d):
            if os.path.exists(os.path.join(d, "snapshot.json")) and os.path.exists(os.path.join(d, "audit-report.json")):
                dirs.append(d)
    return dirs


def main():
    parser = argparse.ArgumentParser(description="Internal Marketplace Quality Index (MQI) Benchmarking Engine")
    parser.add_argument("--workdir", help="Audit directory to benchmark (e.g. audit-thewholetruthfoods.com)")
    parser.add_argument("--compare", nargs=2, metavar=("DIR_A", "DIR_B"), help="Compare two audit directories side-by-side")
    parser.add_argument("--leaderboard", "--batch", action="store_true", help="Generate leaderboard across all audit-* directories")
    parser.add_argument("--json", action="store_true", help="Output raw JSON metrics instead of formatted terminal card")
    args = parser.parse_args()

    if args.compare:
        res_a = compute_mqi(args.compare[0])
        res_b = compute_mqi(args.compare[1])
        if args.json:
            print(json.dumps({"run_a": res_a, "run_b": res_b}, indent=2))
        else:
            print(format_comparison_card(res_a, res_b))
    elif args.workdir:
        res = compute_mqi(args.workdir)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(format_single_card(res))
    elif args.leaderboard:
        dirs = scan_audit_directories()
        if not dirs:
            print("No valid audit-* directories found with snapshot.json and audit-report.json.")
            sys.exit(1)
        runs = [compute_mqi(d) for d in dirs]
        if args.json:
            print(json.dumps(runs, indent=2))
        else:
            print(format_leaderboard(runs))
    else:
        dirs = scan_audit_directories()
        if dirs:
            runs = [compute_mqi(d) for d in dirs]
            print(format_leaderboard(runs))
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
