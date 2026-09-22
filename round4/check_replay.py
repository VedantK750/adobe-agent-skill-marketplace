#!/usr/bin/env python3
"""Validate REPLAY_TransformerBusters.txt before submitting it.

Round 4 applies an "unverified floor": a manifest with missing, blank or
unparseable fields means judges cannot corroborate the run, and the submission
sinks regardless of how good the demo was. This checks the things that would
trigger that, so a forgotten placeholder cannot reach a judge.

    python3 round4/check_replay.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "REPLAY_TransformerBusters.txt")

REQUIRED = ["TEST_SITE_URLS", "LLM_MODEL", "AGENT_HARNESS", "ENV_SETUP",
            "TEST_STEPS", "EXPECTED_OUTPUT"]

# Anything that looks like it was meant to be replaced.
PLACEHOLDER = re.compile(r"__FILL|<FILL|TODO|TBD|XXX|<your|YourTeamName|"
                         r"v<|<VERSION>|\.\.\.", re.I)

problems = []
notes = []


def field(text, name):
    """The value of a labelled field, including indented continuation lines."""
    m = re.search(r"(?m)^%s:[ \t]*(.*)$" % re.escape(name), text)
    if not m:
        return None
    lines = [m.group(1)]
    rest = text[m.end():].splitlines()
    for line in rest:
        if re.match(r"^[A-Z_]+:", line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def main():
    if not os.path.exists(MANIFEST):
        print("FAIL: %s not found" % os.path.basename(MANIFEST))
        sys.exit(1)
    text = open(MANIFEST, encoding="utf-8").read()

    for name in REQUIRED:
        val = field(text, name)
        if val is None:
            problems.append("%s: field missing entirely" % name)
        elif not val.strip("# \t\n"):
            problems.append("%s: present but blank" % name)

    # A placeholder left in is the failure this script exists to prevent.
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if PLACEHOLDER.search(line):
            problems.append("line %d still contains a placeholder: %s"
                            % (i, line.strip()[:70]))

    # URLs must be exact and full, not descriptions.
    urls = field(text, "TEST_SITE_URLS") or ""
    found = re.findall(r"https?://[^\s,]+", urls)
    if not found:
        problems.append("TEST_SITE_URLS: no full http(s) URL found")
    for u in found:
        if not re.match(r"^https?://[a-z0-9.-]+\.[a-z]{2,}", u, re.I):
            problems.append("TEST_SITE_URLS: %r is not a full URL" % u)

    # The model must carry a version or date, not just a family name.
    model = field(text, "LLM_MODEL") or ""
    if not re.search(r"\d", model):
        problems.append("LLM_MODEL: no version or date given (%r)" % model[:40])

    harness = field(text, "AGENT_HARNESS") or ""
    if not re.search(r"\d", harness):
        notes.append("AGENT_HARNESS carries no version number: %r" % harness[:50])

    # The report path the manifest promises must be the one the engine writes.
    out = field(text, "EXPECTED_OUTPUT") or ""
    if "audit-report.json" not in out:
        problems.append("EXPECTED_OUTPUT: does not name audit-report.json")

    # The steps must actually point at the entrypoint the manifest declares.
    steps = field(text, "TEST_STEPS") or ""
    if "run_audit.py" not in steps:
        problems.append("TEST_STEPS: never invokes the entrypoint script")
    for u in found:
        host = re.sub(r"^https?://", "", u).rstrip("/")
        if host.split("/")[0] not in steps and u not in steps:
            notes.append("TEST_SITE_URLS lists %s but no step uses it" % u)

    print("REPLAY manifest check - %s" % os.path.basename(MANIFEST))
    for n in notes:
        print("  NOTE: %s" % n)
    if problems:
        print("\n%d problem(s) - judges may not be able to replay this:" % len(problems))
        for p in problems:
            print("  - %s" % p)
        sys.exit(1)
    print("  all %d required fields present, parseable, no placeholders" % len(REQUIRED))
    print("  test URLs: %s" % ", ".join(found))
    print("OK")


if __name__ == "__main__":
    main()
