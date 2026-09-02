#!/usr/bin/env python3
"""Validate an audit report against report.schema.json.

Uses jsonschema when installed. When it is not, falls back to a minimal
built-in check of the fields the contest brief requires, so validation still
runs on a machine with no optional dependencies. The fallback is deliberately
narrow: it verifies the required shape rather than pretending to be a full
JSON Schema implementation.
"""

import argparse
import json
import os
import re
import sys

SEVERITIES = {"critical", "high", "medium", "low"}


def builtin_validate(report):
    errors = []

    for key in ("site", "audited_at", "summary", "findings"):
        if key not in report:
            errors.append("missing top-level key: %s" % key)
    if errors:
        return errors

    summary = report["summary"]
    for key in ("total_findings", "critical", "high", "medium"):
        if key not in summary:
            errors.append("summary missing key: %s" % key)

    if not isinstance(report["findings"], list):
        errors.append("findings must be a list")
        return errors

    if isinstance(summary.get("total_findings"), int) and \
            summary["total_findings"] != len(report["findings"]):
        errors.append("summary.total_findings (%s) != len(findings) (%d)"
                      % (summary["total_findings"], len(report["findings"])))

    counted = {s: 0 for s in SEVERITIES}
    seen_ids = set()

    for i, f in enumerate(report["findings"]):
        where = "findings[%d]" % i
        for key in ("id", "title", "severity", "evidence", "suggested_action"):
            if key not in f:
                errors.append("%s missing required field: %s" % (where, key))
        fid = f.get("id", "")
        if fid and not re.match(r"^F-\d{3,}$", fid):
            errors.append("%s id %r does not match F-NNN" % (where, fid))
        if fid in seen_ids:
            errors.append("%s duplicate id %r" % (where, fid))
        seen_ids.add(fid)
        sev = f.get("severity")
        if sev not in SEVERITIES:
            errors.append("%s severity %r not one of %s"
                          % (where, sev, sorted(SEVERITIES)))
        else:
            counted[sev] += 1
        if not (f.get("evidence") or "").strip():
            errors.append("%s evidence is empty" % where)
        action = f.get("suggested_action")
        if not isinstance(action, dict):
            errors.append("%s suggested_action must be an object" % where)
        else:
            if not (action.get("summary") or "").strip():
                errors.append("%s suggested_action.summary is empty" % where)
            if action.get("priority") not in SEVERITIES:
                errors.append("%s suggested_action.priority %r invalid"
                              % (where, action.get("priority")))

    for sev in ("critical", "high", "medium", "low"):
        if sev in summary and summary[sev] != counted[sev]:
            errors.append("summary.%s (%s) != actual count (%d)"
                          % (sev, summary[sev], counted[sev]))

    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--schema", default=None)
    args = ap.parse_args()

    with open(args.report, "r", encoding="utf-8") as fh:
        report = json.load(fh)

    schema_path = args.schema or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "report.schema.json")

    errors = []
    engine = "builtin"
    try:
        import jsonschema
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        validator = jsonschema.Draft7Validator(schema)
        errors = ["%s: %s" % ("/".join(str(x) for x in e.path), e.message)
                  for e in validator.iter_errors(report)]
        engine = "jsonschema"
        # Cross-field consistency is not expressible in the schema.
        errors.extend(e for e in builtin_validate(report) if "!=" in e)
    except ImportError:
        errors = builtin_validate(report)

    if errors:
        sys.stderr.write("[validate:%s] INVALID - %d problem(s):\n"
                         % (engine, len(errors)))
        for e in errors[:25]:
            sys.stderr.write("  - %s\n" % e)
        sys.exit(1)

    sys.stderr.write("[validate:%s] OK - %d findings, schema-valid\n"
                     % (engine, len(report.get("findings", []))))


if __name__ == "__main__":
    main()
