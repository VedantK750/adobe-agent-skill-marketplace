#!/usr/bin/env bash
# Build the submission zip: the marketplace root, minus build artifacts and
# working files. Run from the repository root.
set -euo pipefail

OUT="${1:-brand-ai-readiness-audit.zip}"
rm -f "$OUT"

# Everything the marketplace needs to be resolved and run, and nothing else.
zip -r "$OUT" \
  marketplace.json \
  report.schema.json \
  README.md \
  lib \
  skills \
  references \
  tests \
  -x '*/__pycache__/*' '*.pyc' 'tests/.work/*' '*.log' '.DS_Store' \
  >/dev/null

echo "Built $OUT"
python3 - "$OUT" <<'PY'
import sys, zipfile, os
p = sys.argv[1]
size = os.path.getsize(p)
print("Size: %.2f MB (limit 50 MB) -> %s" % (
    size / 1e6, "OK" if size < 50 * 1024 * 1024 else "TOO BIG"))
with zipfile.ZipFile(p) as z:
    names = z.namelist()
print("Entries:", len(names))
# Sanity: manifest and every listed skill folder present at the root.
import json
mani = json.loads(open("marketplace.json").read())
missing = [s["path"] for s in mani["skills"]
           if not any(n.startswith(s["path"] + "/") for n in names)]
print("All skills present in zip:", not missing, missing or "")
assert "marketplace.json" in names
assert not missing
assert size < 50 * 1024 * 1024
print("Submission zip OK.")
PY
