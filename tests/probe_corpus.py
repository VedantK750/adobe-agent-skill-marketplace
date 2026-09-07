#!/usr/bin/env python3
"""Filter a candidate corpus down to hosts that actually answer.

A full audit costs 20-130 seconds per site. A candidate list of a thousand
consumer brands is always partly stale -- brands fold, rebrand, move domain or
park -- and every dead entry burns three retries times a twelve-second timeout
before the suite records the obvious. Probing first with one short request per
host turns an hour of wasted budget into about a minute.

This is a corpus-maintenance tool, not part of the audit. It makes exactly one
GET per host, honours nothing else, and records only whether a status came back.

  python3 tests/probe_corpus.py --in tests/corpus-d2c.txt \
                               --out tests/corpus-d2c.live.txt

Writes the live subset, and prints why each rejection was rejected so a
genuinely interesting site is not dropped by a transient failure without
anyone noticing.
"""

import argparse
import concurrent.futures
import os
import re
import sys
import urllib.parse as up
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TIMEOUT = 8
UA = ("brand-ai-readiness-audit-probe/1.0 (corpus liveness check; "
      "one request per host)")


def normalise(raw):
    """Clean a hand-written candidate line into a URL, or None if unusable.

    Hand-maintained lists pick up stray spaces inside hostnames. A space is
    never valid in a host, and the intended domain is unambiguous, so close it
    rather than discarding a real brand over a typo.
    """
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        p = up.urlparse(raw)
    except ValueError:
        return None
    host = (p.netloc or "").replace(" ", "").lower()
    if not host or "." not in host:
        return None
    if not re.fullmatch(r"[a-z0-9.\-]+(:\d+)?", host):
        return None
    return up.urlunparse(p._replace(netloc=host, scheme=p.scheme.lower()))


def dedupe_key(url):
    """Two entries pointing at the same site should be probed once."""
    p = up.urlparse(url)
    host = p.netloc[4:] if p.netloc.startswith("www.") else p.netloc
    return host + (p.path.rstrip("/") or "")


def _variants(url):
    """The URL, then the same URL with the www prefix toggled.

    A hand-written list guesses at the www prefix, and guessing wrong looks
    exactly like a dead brand: many certificates cover the apex but not `www.`
    (or the reverse), which surfaces as SSLError rather than as a redirect. The
    site is fine; only our spelling of its host was wrong. Trying both recovered
    around forty real brands on the first pass of this corpus.
    """
    yield url
    p = up.urlparse(url)
    if p.netloc.startswith("www."):
        alt = p.netloc[4:]
    else:
        alt = "www." + p.netloc
    yield up.urlunparse(p._replace(netloc=alt))


def probe(url):
    import requests
    last = "error"
    for candidate in _variants(url):
        try:
            r = requests.get(candidate, timeout=TIMEOUT, allow_redirects=True,
                             headers={"User-Agent": UA,
                                      "Accept": "text/html,*/*;q=0.8"})
            # Any HTTP status means a host answered -- including 403, which is
            # itself an interesting audit subject (a bot filter refusing
            # crawlers is a real discoverability defect, not a dead site). Only
            # 404/410 on the home page means there is nothing here to audit.
            if r.status_code in (404, 410):
                last = "home page %d" % r.status_code
                continue
            # Report the spelling that worked, so the saved corpus is the one
            # the audit suite should actually use.
            return candidate, True, str(r.status_code)
        except Exception as exc:
            last = type(exc).__name__
    return url, False, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src",
                    default=os.path.join(ROOT, "tests", "corpus-d2c.txt"))
    ap.add_argument("--out", dest="dst",
                    default=os.path.join(ROOT, "tests", "corpus-d2c.live.txt"))
    ap.add_argument("--workers", type=int, default=40)
    args = ap.parse_args()

    seen, candidates, malformed = set(), [], 0
    with open(args.src, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip().startswith("#") or not line.strip():
                continue
            url = normalise(line)
            if url is None:
                malformed += 1
                continue
            k = dedupe_key(url)
            if k in seen:
                continue
            seen.add(k)
            candidates.append(url)

    print("%d unique candidates (%d unusable lines). Probing with %d workers..."
          % (len(candidates), malformed, args.workers))

    live, dead, reasons = [], [], Counter()
    with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
        for i, (url, ok, why) in enumerate(
                ex.map(probe, candidates), 1):
            if ok:
                live.append(url)
            else:
                dead.append((url, why))
                reasons[why] += 1
            if i % 100 == 0:
                print("  %d/%d probed, %d live" % (i, len(candidates), len(live)))

    live.sort()
    with open(args.dst, "w", encoding="utf-8") as fh:
        fh.write("# Live subset of %s, probed %d candidates.\n"
                 "# Regenerate with: python3 tests/probe_corpus.py\n"
                 % (os.path.basename(args.src), len(candidates)))
        for u in live:
            fh.write(u + "\n")

    print("\n%d live / %d probed -> %s" % (len(live), len(candidates), args.dst))
    print("\nRejections by reason:")
    for why, n in reasons.most_common():
        print("  %-28s %d" % (why, n))
    if dead:
        print("\nFirst 40 rejected:")
        for url, why in dead[:40]:
            print("  %-52s %s" % (url[:52], why))


if __name__ == "__main__":
    main()
