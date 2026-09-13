---
name: machine-readability
description: Detects content that a human can see but a machine cannot read - JavaScript render gaps where text exists only after scripts run, facts locked inside images with no alt text, missing heading and landmark semantics, and substance trapped in iframes. Use as part of a brand AI-readiness audit, after site-acquisition has produced the evidence snapshot.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Machine Readability

## When to use
After `site-acquisition`. Reads `snapshot.json`; never touches the network.

## The mechanism
Step two of the pipeline: once a machine is inside, can it read the page? A
page that looks complete to a person is not always complete to a program.
Every check below asks the same question differently — is the substance
present as text in what a non-browser client receives, or does it exist only
for a human looking at a rendered screen?

## Checks
- `MR-RENDER-GAP` — the headline check. Diffs raw-HTML text against rendered
  DOM text per page and reports the delta. Many fetchers do not execute
  JavaScript, so client-injected content arrives empty. Requires a headless
  browser; without one this reports `inconclusive` and `MR-EMPTY-SHELL` acts
  as the static proxy.
- `MR-EMPTY-SHELL` — many script tags, almost no body text. The signature of
  a client-rendered application shell, detectable without a browser.
- `MR-FACTS-IN-IMAGES` — pricing, hours or spec images with no alt text on
  text-sparse pages. The fact is on screen and absent from the document.
- `MR-ALT-COVERAGE` — content images without alt text, excluding icons,
  logos, spacers and other decoration by filename.
- `MR-NO-H1` / `MR-MULTI-H1` — absent or competing top-level headings weaken
  topic assignment.
- `MR-NO-MAIN-LANDMARK` — without `<main>`, extractors cannot separate body
  copy from navigation, so chunks are diluted with boilerplate.
- `MR-IFRAME-CONTENT` — substance delivered by a frame belongs to another
  document and is generally not followed.

## Avoiding false positives
Decorative images are excluded by filename pattern before alt coverage is
computed. Alt coverage is not assessed at all below ten content images.
Percentage thresholds, not absolute counts, so small sites are judged on the
same basis as large ones.

## Run
`python3 scripts/analyze.py --workdir DIR`

## Safety
Recommend-only: this skill reports, it never changes the audited site. It is a
pure function of `snapshot.json` — it opens no network connection at all, so it
cannot issue a request of any kind, authenticated or otherwise. It writes only
its own fragment inside the working directory.

## Output
`fragments/machine-readability.json` — findings, not-applicable and
inconclusive records for the orchestrator to compose.
