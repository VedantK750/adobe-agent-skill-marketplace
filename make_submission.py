#!/usr/bin/env python3
"""Build and verify the submission zip. Cross-platform; no external tools.

`make_submission.sh` needs bash and the `zip` binary, neither of which exists on
a stock Windows machine. This does the same job with the standard library, and
verifies rather than assumes: the zip is opened after writing and checked
against marketplace.json, so a skill folder that was renamed but not re-listed
(or listed but not shipped) fails the build instead of reaching a grader.

  python3 make_submission.py                       # -> brand-ai-readiness-audit.zip
  python3 make_submission.py --out custom.zip
"""

import argparse
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SIZE_LIMIT = 50 * 1024 * 1024  # the brief's ceiling

# Everything the marketplace needs to resolve and run, and nothing else.
# The tests ship too: they are the evidence for the engineering-hygiene and
# generalisation criteria, and they need no network to read.
INCLUDE_FILES = ["marketplace.json", "report.schema.json", "README.md",
                 "requirements.txt"]
INCLUDE_DIRS = ["skills", "lib", "references", "tests"]

EXCLUDE_PARTS = {"__pycache__", ".work", "live-results", ".git", ".venv",
                 "node_modules"}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".log", ".zip", ".live.txt")


def keep(rel):
    parts = rel.replace("\\", "/").split("/")
    if any(p in EXCLUDE_PARTS for p in parts):
        return False
    if rel.endswith(EXCLUDE_SUFFIX):
        return False
    return os.path.basename(rel) != ".DS_Store"


def collect():
    out = []
    for name in INCLUDE_FILES:
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            out.append(name)
        else:
            sys.stderr.write("WARNING: %s not found, skipping\n" % name)
    for d in INCLUDE_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in EXCLUDE_PARTS]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                rel = rel.replace("\\", "/")
                if keep(rel):
                    out.append(rel)
    # Deterministic member order, so two builds of the same tree match.
    return sorted(set(out))


def verify(zip_path):
    """Open the built zip and check it against the manifest. Returns problems."""
    problems = []
    with open(os.path.join(ROOT, "marketplace.json"), "r",
              encoding="utf-8") as fh:
        mani = json.load(fh)

    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        bad = z.testzip()
        if bad:
            problems.append("corrupt entry in archive: %s" % bad)

        if "marketplace.json" not in names:
            problems.append("marketplace.json missing from the archive")

        entrypoints = [s for s in mani.get("skills", []) if s.get("entrypoint")]
        if len(entrypoints) != 1:
            problems.append("manifest declares %d entrypoints; exactly 1 required"
                            % len(entrypoints))

        for s in mani.get("skills", []):
            path = s["path"].rstrip("/")
            skill_md = path + "/SKILL.md"
            if skill_md not in names:
                problems.append("%s: SKILL.md missing from the archive"
                                % s["id"])
                continue
            head = z.read(skill_md).decode("utf-8", "replace")[:2000]
            if not head.startswith("---"):
                problems.append("%s: SKILL.md has no YAML frontmatter" % s["id"])
            else:
                block = head.split("---", 2)[1]
                for key in ("name:", "description:"):
                    if key not in block:
                        problems.append("%s: SKILL.md frontmatter missing %s"
                                        % (s["id"], key.rstrip(":")))
                declared = None
                for line in block.splitlines():
                    if line.startswith("name:"):
                        declared = line.split(":", 1)[1].strip()
                if declared and declared != s["id"]:
                    problems.append("%s: SKILL.md name is %r but the manifest "
                                    "lists id %r" % (s["id"], declared, s["id"]))

        # A skill folder shipped but not listed is dead weight a grader will
        # find before we do.
        listed = {s["path"].rstrip("/") for s in mani.get("skills", [])}
        shipped = {n.rsplit("/SKILL.md", 1)[0] for n in names
                   if n.endswith("/SKILL.md")}
        for extra in sorted(shipped - listed):
            problems.append("%s ships a SKILL.md but is not listed in the "
                            "manifest" % extra)

    size = os.path.getsize(zip_path)
    if size > SIZE_LIMIT:
        problems.append("archive is %.1f MB, over the 50 MB limit"
                        % (size / 1e6))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="brand-ai-readiness-audit.zip")
    args = ap.parse_args()

    out = os.path.join(ROOT, args.out) if not os.path.isabs(args.out) else args.out
    if os.path.exists(out):
        os.remove(out)

    members = collect()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in members:
            z.write(os.path.join(ROOT, rel), rel)

    size = os.path.getsize(out)
    print("Built %s" % out)
    print("  %d entries, %.2f MB (limit 50 MB)" % (len(members), size / 1e6))

    problems = verify(out)
    if problems:
        print("\nFAILED verification:")
        for p in problems:
            print("  - %s" % p)
        sys.exit(1)

    # Gate the build on the brief's mechanically checkable requirements too, so
    # a zip that packs correctly but violates the spec cannot be produced by
    # accident on the way out the door.
    import subprocess
    check = os.path.join(ROOT, "tests", "check_compliance.py")
    if os.path.exists(check):
        proc = subprocess.run([sys.executable, check], capture_output=True,
                              text=True)
        if proc.returncode != 0:
            print("\nFAILED brief-compliance check:")
            print(proc.stdout[-2500:])
            sys.exit(1)
        tail = [l for l in proc.stdout.splitlines() if "requirements met" in l]
        print("  brief compliance: %s" % (tail[-1].strip() if tail else "OK"))

    with open(os.path.join(ROOT, "marketplace.json"), encoding="utf-8") as fh:
        mani = json.load(fh)
    entry = next(s["id"] for s in mani["skills"] if s.get("entrypoint"))
    print("  manifest OK: %d skills, entrypoint = %s"
          % (len(mani["skills"]), entry))
    print("  every listed skill ships a valid SKILL.md")
    print("\nSubmission zip OK.")


if __name__ == "__main__":
    main()
